#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_participants.py
Récupère la liste des participants pour chaque cours et met à jour les liens.
"""
import os, re, json, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

MOODLE_URL    = "https://foad-moodle.ensai.fr"
OFFLINE       = Path(__file__).parent / "moodle_offline"
MAPPING_FILE  = OFFLINE / "mapping.json"
PASSWORD_FILE = Path(__file__).parent.parent / "mot de passe moodle.txt"
USERNAME      = "id2813"
DELAY         = 0.3

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0"})

# ── Login ─────────────────────────────────────────────────────────────────────
def login():
    r = session.get(f"{MOODLE_URL}/login/index.php", timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form")
    data = {i.get("name",""): i.get("value","") for i in form.find_all("input") if i.get("name")}
    data.update(username=USERNAME, password=PASSWORD_FILE.read_text().strip(),
                _eventId="submit", geolocation="")
    action = urljoin(r.url, form.get("action",""))
    time.sleep(DELAY)
    r2 = session.post(action, data=data, timeout=30, allow_redirects=True)
    print("Login:", "OK" if "my" in r2.url else r2.url)
    return r2

# ── Récupérer les cours avec IDs via AJAX ─────────────────────────────────────
def get_course_ids(sesskey):
    ajax_url = f"{MOODLE_URL}/lib/ajax/service.php?sesskey={sesskey}"
    payload = [{"index": 0,
                "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                "args": {"offset": 0, "limit": 50, "classification": "all",
                         "sort": "fullname", "customfieldname": "", "customfieldvalue": ""}}]
    time.sleep(DELAY)
    resp = session.post(ajax_url, json=payload, timeout=30)
    result = resp.json()
    if result[0].get("error"):
        raise Exception(f"AJAX error: {result[0]}")
    courses = result[0]["data"]["courses"]
    # fullname → id
    return {c["fullname"]: c["id"] for c in courses}

# ── Charger url_map ───────────────────────────────────────────────────────────
def load_mapping():
    raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    url_map = {}
    for url, local_str in raw.items():
        url_map[url] = Path(local_str)
    return url_map

# ── Scraper une page participants ─────────────────────────────────────────────
def scrape_participants_page(course_id, course_folder, url_map):
    url = f"{MOODLE_URL}/user/index.php?id={course_id}"
    time.sleep(DELAY)
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code} pour course {course_id}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    out_path = OFFLINE / "cours" / course_folder / "participants" / "index.html"

    # Réécrire les liens
    base = MOODLE_URL

    def abs_url(href):
        if not href: return ""
        if href.startswith("http"): return href
        return urljoin(base, href)

    def rel(target):
        try:
            return os.path.relpath(str(target), str(out_path.parent)).replace("\\", "/")
        except ValueError:
            return str(target)

    for tag in soup.find_all("link", rel=True):
        if "stylesheet" in tag.get("rel", []):
            u = abs_url(tag.get("href",""))
            if u in url_map: tag["href"] = rel(url_map[u])

    for tag in soup.find_all("script", src=True):
        u = abs_url(tag["src"])
        if u in url_map: tag["src"] = rel(url_map[u])

    for tag in soup.find_all("img", src=True):
        u = abs_url(tag["src"])
        if u in url_map: tag["src"] = rel(url_map[u])

    for tag in soup.find_all("a", href=True):
        u = abs_url(tag["href"])
        if u in url_map:
            tag["href"] = rel(url_map[u])
        elif u.startswith(base) or tag["href"].startswith("/"):
            tag["href"] = "#"

    for tag in soup.find_all("base"):
        tag.decompose()

    # Injecter nav fix
    nav_fix = """<script>
(function(){
  function patchNav(){
    document.querySelectorAll('[data-key] > a[href]').forEach(function(a){
      var href=a.getAttribute('href');
      if(!href||href==='#') return;
      a.addEventListener('click',function(e){
        e.stopImmediatePropagation();e.preventDefault();window.location.href=href;
      },true);
    });
  }
  document.readyState==='loading'?document.addEventListener('DOMContentLoaded',patchNav):patchNav();
})();
</script>"""
    head = soup.find("head")
    if head:
        head.append(BeautifulSoup(nav_fix, "html.parser"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
    return out_path

# ── Mettre à jour les liens Participants dans les pages de cours ──────────────
def update_participants_links(course_folder, participants_path):
    course_index = OFFLINE / "cours" / course_folder / "index.html"
    if not course_index.exists():
        return False

    content = course_index.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(content, "html.parser")

    changed = False
    for a in soup.find_all("a", href=True):
        if "articipant" in a.get_text(strip=True):
            rel_path = os.path.relpath(str(participants_path), str(course_index.parent)).replace("\\", "/")
            if a["href"] != rel_path:
                a["href"] = rel_path
                changed = True

    if changed:
        course_index.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
    return changed

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    login()

    # Récupérer sesskey
    time.sleep(DELAY)
    r = session.get(f"{MOODLE_URL}/my/", timeout=30)
    m = re.search(r'"sesskey":"([^"]+)"', r.text)
    sesskey = m.group(1) if m else None
    print(f"sesskey: {sesskey}")

    # Récupérer les IDs de cours
    course_ids = get_course_ids(sesskey)
    print(f"{len(course_ids)} cours trouvés avec IDs")

    url_map = load_mapping()

    # Mapper nom Moodle → dossier local
    cours_dir = OFFLINE / "cours"
    local_folders = {p.name for p in cours_dir.iterdir() if p.is_dir()}

    scraped = 0
    for fullname, course_id in sorted(course_ids.items()):
        # Trouver le dossier local correspondant
        folder = None
        for f in local_folders:
            # Nettoyer pour comparer
            clean_f = re.sub(r'[^\w\s]', ' ', f.replace('_', ' ')).lower()
            clean_n = re.sub(r'[^\w\s]', ' ', fullname).lower()
            if clean_n[:20] in clean_f or clean_f[:20] in clean_n:
                folder = f
                break

        if not folder:
            print(f"  DOSSIER INTROUVABLE: {fullname}")
            continue

        print(f"  Scraping participants: {fullname} (id={course_id}) → {folder}")
        out = scrape_participants_page(course_id, folder, url_map)
        if out:
            updated = update_participants_links(folder, out)
            print(f"    → Lien mis à jour: {updated}")
            scraped += 1

    print(f"\nTerminé: {scraped} pages participants sauvegardées")
