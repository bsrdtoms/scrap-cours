#!/usr/bin/env python3
"""
Lanceur pour moodle_scraper.py avec :
- injection directe du cookie MoodleSession
- correction du bug de double-réécriture dans build_index
- scraping des sections d'onglets (?section=N)
- post-traitement pour renommer les fichiers CSS sans extension
"""
import sys
import re
import logging
import argparse
import time
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

sys.path.insert(0, "/tmp/scrap-cours")
from moodle_scraper import MoodleScraper, setup_logging

MOODLE_URL    = "http://moodle-2024.domensai.ecole"
COOKIE_VALUE  = "cig6b4cbd50r1ofdc94f13chgj"
OUTPUT_DIR    = Path(__file__).parent / "moodle-domensai-offline"
LOG_FILE      = Path(__file__).parent / "moodle_scraper_domensai.log"

# ── Correction de build_index (bug double-réécriture) ────────────────────────
def fixed_build_index(self, courses, assets_dir):
    log = logging.getLogger(__name__)
    log.info("\nCréation de la page d'accueil...")
    r = self.get(f"{self.base_url}/my/courses.php") or self.get(f"{self.base_url}/my/")
    if not r:
        self._build_simple_index(courses)
        return

    soup = BeautifulSoup(r.text, "html.parser")
    idx_path = self.output_dir / "index.html"

    # 1. Télécharger les assets (CSS/JS/images) en reécrivant leurs chemins
    for tag in soup.find_all("link", rel=True):
        if "stylesheet" in tag.get("rel", []):
            href = self.abs_url(tag.get("href", ""))
            if href and self.is_moodle_url(href):
                local = self.download_asset(href, assets_dir)
                if local:
                    tag["href"] = self.relpath(local, idx_path)

    for tag in soup.find_all("script", src=True):
        src = self.abs_url(tag["src"])
        if src and self.is_moodle_url(src):
            local = self.download_asset(src, assets_dir)
            if local:
                tag["src"] = self.relpath(local, idx_path)

    for tag in soup.find_all("img", src=True):
        src = self.abs_url(tag["src"])
        if src and self.is_moodle_url(src):
            local = self.download_asset(src, assets_dir)
            if local:
                tag["src"] = self.relpath(local, idx_path)

    # 2. Réécrire les liens <a> en un seul passage (pas de double-réécriture)
    for tag in soup.find_all("a", href=True):
        href = self.abs_url(tag["href"])
        if href in self.url_map:
            tag["href"] = self.relpath(self.url_map[href], idx_path)
        elif self.is_moodle_url(href) or tag["href"].startswith("/"):
            tag["href"] = "#"

    for tag in soup.find_all("base"):
        tag.decompose()

    self._save_html(soup, idx_path)
    self.pages_saved += 1
    log.info(f"✓ Index créé : {idx_path}")

# ── Scraping des sections d'onglets (?section=N) ─────────────────────────────
def patched_scrape_course(self, course, assets_dir):
    """
    Extension de scrape_course : après avoir scrapé la page principale du cours,
    détecte les onglets de sections (nav-link avec ?section=N) et les scrape aussi.
    """
    log = logging.getLogger(__name__)
    safe_name  = self.sanitize(course["name"])
    course_dir = self.output_dir / "cours" / safe_name
    files_dir  = course_dir / "fichiers"
    pages_dir  = course_dir / "pages"
    course_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"\n{'='*55}")
    log.info(f"[Cours] {course['name']}  (id={course['id']})")

    r = self.get(course["url"])
    if not r:
        log.error("  ✗ Impossible d'accéder au cours")
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    html_path  = course_dir / "index.html"
    activities = self._parse_activities(soup)
    log.info(f"  → {len(activities)} activités trouvées")

    for act in activities:
        if not act["href"]:
            continue
        if act["type"] == "resource":
            local = self.download_resource(act["href"], files_dir)
            if local:
                self.url_map[act["href"]] = local
        elif act["type"] == "folder":
            self._scrape_folder(act["href"], files_dir, assets_dir)
        elif act["type"] == "page":
            local = self._scrape_moodle_page(act["href"], pages_dir, assets_dir, course_dir)
            if local:
                self.url_map[act["href"]] = local

    # ── Scraper les onglets de sections (?section=N) ──────────────────────
    for a in soup.find_all("a", class_="nav-link"):
        href = a.get("href", "")
        if not href or href == "#":
            continue
        # Résoudre avec l'URL du cours (pas juste base_url) pour ?section=N
        abs_href = urljoin(course["url"], href)
        if not re.search(r"[?&]section=\d+", abs_href):
            continue
        if abs_href in self.url_map:
            continue
        m = re.search(r"section=(\d+)", abs_href)
        sec_num = m.group(1) if m else "x"
        sec_path = course_dir / f"section_{sec_num}.html"

        r2 = self.get(abs_href)
        if not r2:
            continue
        soup2 = BeautifulSoup(r2.text, "html.parser")
        # Télécharger les ressources de cette section aussi
        for act in self._parse_activities(soup2):
            if not act["href"]:
                continue
            if act["type"] == "resource":
                local = self.download_resource(act["href"], files_dir)
                if local:
                    self.url_map[act["href"]] = local
            elif act["type"] == "folder":
                self._scrape_folder(act["href"], files_dir, assets_dir)
            elif act["type"] == "page":
                local = self._scrape_moodle_page(act["href"], pages_dir, assets_dir, course_dir)
                if local:
                    self.url_map[act["href"]] = local
        # Enregistrer AVANT _rewrite_page pour que les liens inter-sections fonctionnent
        self.url_map[abs_href] = sec_path
        soup2 = self._rewrite_page(soup2, sec_path, assets_dir)
        self._save_html(soup2, sec_path)
        self.pages_saved += 1
        log.info(f"  ↓ Section {sec_num} sauvegardée : {sec_path.name}")

    soup = self._rewrite_page(soup, html_path, assets_dir)
    self._save_html(soup, html_path)
    self.pages_saved += 1
    self.url_map[course["url"]] = html_path
    log.info("  ✓ Page cours sauvegardée")
    return course_dir

# ── Post-traitement : renommer les CSS sans extension ────────────────────────
def fix_css_extensions(output_dir: Path):
    """
    Certains fichiers CSS Moodle n'ont pas d'extension (ex: theme/styles.php/.../all).
    Les renomme avec .css et met à jour les références dans tous les HTML.
    """
    log = logging.getLogger(__name__)
    assets_dir = output_dir / "assets"
    renamed = {}  # old_path → new_path (relatif à output_dir)

    for f in assets_dir.rglob("*"):
        if f.is_file() and f.suffix == "":
            try:
                head = f.read_bytes()[:200].decode("utf-8", errors="ignore").strip()
                if head.startswith(".") or head.startswith("/*") or re.match(r"^[a-zA-Z#@][\w\-]*[\s{]", head):
                    new_f = f.with_suffix(".css")
                    if not new_f.exists():
                        f.rename(new_f)
                        renamed[str(f.relative_to(output_dir))] = str(new_f.relative_to(output_dir))
                        log.info(f"  CSS renommé : {f.name} → {new_f.name}")
            except Exception:
                pass

    if not renamed:
        return

    # Mettre à jour toutes les références dans les HTML
    for html_file in output_dir.rglob("*.html"):
        try:
            text = html_file.read_text(encoding="utf-8", errors="ignore")
            changed = False
            for old_rel, new_rel in renamed.items():
                # Calculer le chemin relatif depuis ce fichier HTML
                old_abs = output_dir / old_rel
                new_abs = output_dir / new_rel
                import os
                old_local = os.path.relpath(str(old_abs), str(html_file.parent)).replace("\\", "/")
                new_local = os.path.relpath(str(new_abs), str(html_file.parent)).replace("\\", "/")
                if old_local in text:
                    text = text.replace(old_local, new_local)
                    changed = True
            if changed:
                html_file.write_text(text, encoding="utf-8")
        except Exception:
            pass

    log.info(f"  {len(renamed)} fichier(s) CSS renommé(s), références mises à jour")

# ── Main ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--test",    action="store_true")
parser.add_argument("--courses", type=int)
args = parser.parse_args()

setup_logging(LOG_FILE)
log = logging.getLogger(__name__)

scraper = MoodleScraper(
    moodle_url=MOODLE_URL,
    output_dir=OUTPUT_DIR,
    test_mode=args.test,
    max_courses=args.courses,
)

# Injecter le cookie et bypasser le login
scraper.session.cookies.set("MoodleSession", COOKIE_VALUE, domain="moodle-2024.domensai.ecole")
time.sleep(0.3)
r = scraper.session.get(f"{MOODLE_URL}/my/", timeout=30)
if "login" in r.url or r.status_code != 200:
    log.error(f"Cookie invalide — URL finale : {r.url}")
    sys.exit(1)
log.info(f"✓ Cookie valide — session active")
scraper.login = lambda: True

# Appliquer les monkey-patches
import types
scraper.build_index    = types.MethodType(fixed_build_index,     scraper)
scraper.scrape_course  = types.MethodType(patched_scrape_course, scraper)

# Lancer le scraper
scraper.run()

# Post-traitement : corriger les extensions CSS
log.info("\nPost-traitement CSS...")
fix_css_extensions(OUTPUT_DIR)

log.info(f"\n✅ Terminé. Ouvrir : {OUTPUT_DIR / 'index.html'}")
