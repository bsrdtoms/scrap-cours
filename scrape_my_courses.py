#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_my_courses.py
--------------------
Scrape la vraie page /my/courses depuis Moodle et la sauvegarde localement.
Met ensuite à jour tous les liens data-key="mycourses" pour pointer vers cette page.
"""

import os, re, json, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

MOODLE_URL   = "https://foad-moodle.ensai.fr"
OFFLINE      = Path(__file__).parent / "moodle_offline"
MAPPING_FILE = OFFLINE / "mapping.json"
PASSWORD_FILE = Path(__file__).parent.parent / "mot de passe moodle.txt"
USERNAME     = "id2813"
TARGET_URL   = MOODLE_URL + "/my/courses.php"
LOCAL_PATH   = OFFLINE / "my_courses" / "index.html"
DELAY        = 0.3

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
})

# ── 1. Login ─────────────────────────────────────────────────────────────────
def login(username, password):
    print("Connexion à Moodle...")
    r = session.get(f"{MOODLE_URL}/login/index.php", timeout=30)
    # CAS ?
    if "ssocas" in r.url or "cas" in r.url:
        cas_url = r.url
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        data = {i.get("name",""): i.get("value","") for i in form.find_all("input") if i.get("name")}
        data.update(username=username, password=password, _eventId="submit", geolocation="")
        action = form.get("action","")
        if not action.startswith("http"):
            action = urljoin(cas_url, action)
        time.sleep(DELAY)
        r2 = session.post(action, data=data, timeout=30, allow_redirects=True)
        if "ssocas" in r2.url:
            # 2e tentative avec username court
            soup2 = BeautifulSoup(r2.text, "html.parser")
            form2 = soup2.find("form")
            data2 = {i.get("name",""): i.get("value","") for i in form2.find_all("input") if i.get("name")}
            short = username.split("@")[0] if "@" in username else username
            data2.update(username=short, password=password, _eventId="submit", geolocation="")
            action2 = form2.get("action","")
            if not action2.startswith("http"):
                action2 = urljoin(r2.url, action2)
            time.sleep(DELAY)
            r2 = session.post(action2, data=data2, timeout=30, allow_redirects=True)
        print("  Connexion CAS réussie")
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        tok = soup.find("input", {"name": "logintoken"})
        data = {"username": username, "password": password,
                "logintoken": tok["value"] if tok else "", "anchor": ""}
        time.sleep(DELAY)
        session.post(f"{MOODLE_URL}/login/index.php", data=data, timeout=30)
        print("  Connexion standard réussie")

# ── 2. Charger le mapping ────────────────────────────────────────────────────
def load_mapping():
    raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    url_map = {}
    for url, local_str in raw.items():
        url_map[url] = Path(local_str)
    # variantes slash
    extras = {}
    for url, path in url_map.items():
        if url.endswith("/"):
            extras[url.rstrip("/")] = path
        else:
            extras[url + "/"] = path
    url_map.update(extras)
    return url_map

# ── 3. Réécrire les liens ────────────────────────────────────────────────────
def relpath(target, base_file):
    try:
        p = os.path.relpath(str(target), str(Path(base_file).parent))
        return p.replace("\\", "/")
    except ValueError:
        return str(target).replace("\\", "/")

def rewrite(soup, html_path, url_map):
    base = MOODLE_URL
    def abs_url(href):
        if not href: return ""
        if href.startswith("http"): return href
        return urljoin(base, href)

    for tag in soup.find_all("link", rel=True):
        if "stylesheet" in tag.get("rel", []):
            u = abs_url(tag.get("href",""))
            if u in url_map: tag["href"] = relpath(url_map[u], html_path)

    for tag in soup.find_all("script", src=True):
        u = abs_url(tag["src"])
        if u in url_map: tag["src"] = relpath(url_map[u], html_path)

    for tag in soup.find_all("img", src=True):
        u = abs_url(tag["src"])
        if u in url_map: tag["src"] = relpath(url_map[u], html_path)

    for tag in soup.find_all("a", href=True):
        raw = tag["href"]
        u = abs_url(raw)
        if u in url_map:
            tag["href"] = relpath(url_map[u], html_path)
            tag.attrs.pop("title", None)
            tag.attrs.pop("style", None)
        elif u.startswith(base) or raw.startswith("/"):
            tag["href"] = "#"
            tag["title"] = "Non disponible hors ligne"
            tag["style"] = "cursor:default;color:inherit;text-decoration:none;"

    for tag in soup.find_all("base"):
        tag.decompose()

    return soup

# ── 4. Scraper /my/courses ────────────────────────────────────────────────────
def scrape_my_courses(url_map):
    print(f"Téléchargement de {TARGET_URL}...")
    time.sleep(DELAY)
    r = session.get(TARGET_URL, timeout=30)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    print(f"  OK ({len(r.text)} caractères)")

    soup = BeautifulSoup(r.text, "html.parser")

    # Enregistrer dans url_map avant réécriture
    url_map[TARGET_URL]             = LOCAL_PATH
    url_map[TARGET_URL.rstrip("/")] = LOCAL_PATH
    url_map[TARGET_URL + "/"]       = LOCAL_PATH

    soup = rewrite(soup, LOCAL_PATH, url_map)

    # Injecter le shim nav fix
    NAV_FIX = """<script>
/* OFFLINE NAV FIX */
(function(){
  function patchNav(){
    document.querySelectorAll('[data-key] > a[href]').forEach(function(a){
      var href=a.getAttribute('href');
      if(!href||href==='#') return;
      a.addEventListener('click',function(e){
        e.stopImmediatePropagation();e.preventDefault();
        window.location.href=href;
      },true);
    });
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',patchNav);}
  else{patchNav();}
})();
</script>"""
    head = soup.find("head")
    if head:
        head.append(BeautifulSoup(NAV_FIX, "html.parser"))

    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PATH.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
    print(f"  Sauvegardé : {LOCAL_PATH}")
    return url_map

# ── 5. Mettre à jour les liens mycourses dans tous les HTML ──────────────────
def update_mycourses_links():
    print("\nMise à jour des liens data-key='mycourses'...")
    html_files = list(OFFLINE.rglob("*.html"))
    updated = 0
    for html_path in html_files:
        if html_path == LOCAL_PATH:
            continue
        content = html_path.read_text(encoding="utf-8", errors="ignore")
        if 'data-key="mycourses"' not in content and "data-key='mycourses'" not in content:
            continue

        soup = BeautifulSoup(content, "html.parser")
        changed = False
        for li in soup.find_all(attrs={"data-key": "mycourses"}):
            a = li.find("a", href=True)
            if not a:
                continue
            try:
                rel = os.path.relpath(str(LOCAL_PATH), str(html_path.parent)).replace("\\", "/")
            except ValueError:
                rel = str(LOCAL_PATH).replace("\\", "/")

            new_onclick = f"event.stopImmediatePropagation();event.preventDefault();window.location.href='{rel}';return false;"
            if a.get("href") != rel or a.get("onclick") != new_onclick:
                a["href"] = rel
                a["onclick"] = new_onclick
                a.attrs.pop("title", None)
                a.attrs.pop("style", None)
                changed = True

        if changed:
            html_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
            updated += 1

    print(f"  {updated} fichiers mis à jour")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    login(USERNAME, password)

    url_map = load_mapping()
    url_map = scrape_my_courses(url_map)
    update_mycourses_links()

    print("\nTerminé. Recharger http://localhost:8765/ et cliquer 'Mes cours'.")
