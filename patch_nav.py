#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_nav.py — Répare la navigation complète du miroir offline.

Ce script :
  1. Lit mapping.json pour connaître tous les fichiers locaux existants
  2. Se connecte à Moodle (pour accéder aux pages authentifiées)
  3. Scrape les pages de navigation (/my/, /calendar/, profil…)
  4. Re-télécharge et re-sauvegarde les HTML de TOUS les cours
     avec un url_map COMPLET (tous les liens connus d'avance)
  5. Ne re-télécharge PAS les fichiers binaires (PDFs, DOCX…) déjà présents

Résultat : tous les boutons de navigation (Tableau de bord, etc.) fonctionnent.
"""

import os, re, sys, json, time, getpass, logging
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup

# ---- Config ----
MOODLE_URL   = "https://foad-moodle.ensai.fr"
OFFLINE_DIR  = Path(__file__).parent / "moodle_offline"
MAPPING_FILE = OFFLINE_DIR / "mapping.json"
LOG_FILE     = Path(__file__).parent / "patch_nav.log"
PASSWORD_FILE = Path(__file__).parent.parent / "mot de passe moodle.txt"
DELAY        = 0.25

# ---- Logging ----
_sh = logging.StreamHandler(sys.stdout)
_sh.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), _sh],
)
log = logging.getLogger(__name__)

# Pages de navigation à sauvegarder (en plus des cours)
NAV_PAGES = [
    ("/my/",                    "dashboard/index.html"),
    ("/calendar/view.php",      "calendar/index.html"),
    ("/message/index.php",      "messages/index.html"),
    ("/mod/forum/index.php",    "forums/index.html"),
]


# ============================================================
class NavPatcher:
    def __init__(self, username, password):
        self.base_url = MOODLE_URL.rstrip("/")
        self.username = username
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        # url_map : url_moodle → chemin local Path absolu
        self.url_map: dict[str, Path] = {}
        self.assets_dir = OFFLINE_DIR / "assets"

    # ----------------------------------------------------------
    def sanitize(self, name, max_len=80):
        name = unquote(name)
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("._")
        return name[:max_len] or "sans_nom"

    def abs_url(self, href):
        if not href:
            return ""
        if href.startswith("http"):
            return href
        return urljoin(self.base_url, href)

    def is_moodle_url(self, url):
        return url.startswith(self.base_url)

    def relpath(self, target, base_file):
        try:
            p = os.path.relpath(str(target), str(Path(base_file).parent))
            return p.replace("\\", "/")
        except ValueError:
            return str(target).replace("\\", "/")

    def get(self, url, **kw):
        time.sleep(DELAY)
        try:
            return self.session.get(url, timeout=60, **kw)
        except Exception as e:
            log.warning(f"GET échoué : {url} — {e}")
            return None

    # ----------------------------------------------------------
    # LOGIN (copié du scraper principal)
    # ----------------------------------------------------------
    def login(self):
        login_url = f"{self.base_url}/login/index.php"
        log.info("Connexion à Moodle...")
        r = self.get(login_url)
        if not r:
            raise Exception("Impossible d'accéder à la page de login")
        if "ssocas" in r.url or "cas" in r.url:
            self._login_cas(r)
        else:
            self._login_standard(r)

    def _login_cas(self, r):
        cas_url = r.url
        log.info(f"  CAS détecté : {cas_url.split('?')[0]}")
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise Exception("Formulaire CAS introuvable")
        data = {i.get("name", ""): i.get("value", "")
                for i in form.find_all("input") if i.get("name")}
        data.update(username=self.username, password=self.password,
                    _eventId="submit", geolocation="")
        action = form.get("action", "")
        if not action.startswith("http"):
            action = urljoin(cas_url, action)
        time.sleep(DELAY)
        r2 = self.session.post(action, data=data, timeout=30, allow_redirects=True)
        if "ssocas" in r2.url:
            soup2 = BeautifulSoup(r2.text, "html.parser")
            form2 = soup2.find("form")
            if form2:
                data2 = {i.get("name", ""): i.get("value", "")
                         for i in form2.find_all("input") if i.get("name")}
                short = self.username.split("@")[0] if "@" in self.username else self.username
                data2.update(username=short, password=self.password,
                             _eventId="submit", geolocation="")
                action2 = form2.get("action", "")
                if not action2.startswith("http"):
                    action2 = urljoin(r2.url, action2)
                log.info(f"  2e tentative : {short}")
                time.sleep(DELAY)
                r2 = self.session.post(action2, data=data2, timeout=30, allow_redirects=True)
        if "ssocas" in r2.url:
            raise Exception("Connexion CAS échouée")
        time.sleep(DELAY)
        r3 = self.session.get(f"{self.base_url}/my/", timeout=30)
        if "login" in r3.url or "ssocas" in r3.url:
            raise Exception("Session Moodle non établie après CAS")
        log.info("  Connexion CAS réussie")

    def _login_standard(self, r):
        soup = BeautifulSoup(r.text, "html.parser")
        tok  = soup.find("input", {"name": "logintoken"})
        data = {"username": self.username, "password": self.password,
                "logintoken": tok["value"] if tok else "", "anchor": ""}
        time.sleep(DELAY)
        r2 = self.session.post(f"{self.base_url}/login/index.php", data=data, timeout=30)
        if "login" in r2.url:
            raise Exception("Connexion standard échouée")
        log.info("  Connexion réussie")

    # ----------------------------------------------------------
    # RÉÉCRITURE DES LIENS
    # ----------------------------------------------------------
    def _rewrite_page(self, soup, html_path):
        """Réécrit les liens avec url_map complet. Les liens inconnus → #."""
        # CSS
        for tag in soup.find_all("link", rel=True):
            if "stylesheet" in tag.get("rel", []):
                href = self.abs_url(tag.get("href", ""))
                if href in self.url_map:
                    tag["href"] = self.relpath(self.url_map[href], html_path)

        # JS
        for tag in soup.find_all("script", src=True):
            src = self.abs_url(tag["src"])
            if src in self.url_map:
                tag["src"] = self.relpath(self.url_map[src], html_path)

        # Images
        for tag in soup.find_all("img", src=True):
            src = self.abs_url(tag["src"])
            if src in self.url_map:
                tag["src"] = self.relpath(self.url_map[src], html_path)

        # Liens <a>
        for tag in soup.find_all("a", href=True):
            raw  = tag["href"]
            href = self.abs_url(raw)
            if href in self.url_map:
                tag["href"] = self.relpath(self.url_map[href], html_path)
                # Supprimer les marqueurs "non disponible" si présents
                tag.attrs.pop("title", None)
                tag.attrs.pop("style", None)
            elif self.is_moodle_url(href) or raw.startswith("/"):
                tag["href"] = "#"
                tag["title"] = "Non disponible hors ligne"
                tag["style"]  = "cursor:default;color:inherit;text-decoration:none;"

        # Supprimer les balises <base>
        for tag in soup.find_all("base"):
            tag.decompose()

        return soup

    def _save_html(self, soup, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")

    # ----------------------------------------------------------
    # CHARGEMENT DU MAPPING EXISTANT
    # ----------------------------------------------------------
    def load_mapping(self):
        log.info("Chargement du mapping.json...")
        raw = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
        for url, local_str in raw.items():
            self.url_map[url] = Path(local_str)
        log.info(f"  {len(self.url_map)} entrées chargées")

        # Ajouter aussi les variantes sans trailing slash pour /my/
        extras = {}
        for url, path in self.url_map.items():
            if url.endswith("/"):
                extras[url.rstrip("/")] = path
            else:
                extras[url + "/"] = path
        self.url_map.update(extras)

    # ----------------------------------------------------------
    # SCRAPE DES PAGES DE NAVIGATION
    # ----------------------------------------------------------
    def scrape_nav_pages(self):
        log.info("\nScrape des pages de navigation...")
        for path_suffix, local_rel in NAV_PAGES:
            url       = self.base_url + path_suffix
            local     = OFFLINE_DIR / local_rel
            r         = self.get(url)
            if not r or r.status_code != 200:
                log.warning(f"  Inaccessible : {url}")
                continue

            soup      = BeautifulSoup(r.text, "html.parser")

            # Pré-enregistrer dans url_map AVANT de réécrire
            self.url_map[url]             = local
            self.url_map[url.rstrip("/")] = local
            self.url_map[url + "/"]       = local

            soup = self._rewrite_page(soup, local)
            self._save_html(soup, local)
            log.info(f"  Sauvegardé : {local_rel}")

    # ----------------------------------------------------------
    # RE-SCRAPE DES COURS (HTML UNIQUEMENT)
    # ----------------------------------------------------------
    def rescrape_course_html(self):
        """Re-télécharge et re-sauvegarde le HTML de chaque cours."""
        log.info("\nRe-scrape des pages de cours...")

        # Identifier les cours depuis mapping.json
        course_entries = {
            url: path for url, path in self.url_map.items()
            if "/course/view.php?id=" in url
        }
        log.info(f"  {len(course_entries)} cours à re-scraper")

        for i, (url, html_path) in enumerate(course_entries.items(), 1):
            html_path = Path(html_path)
            if not html_path.parent.exists():
                log.warning(f"  [{i}] Dossier inexistant, ignoré : {html_path}")
                continue

            log.info(f"  [{i}/{len(course_entries)}] {html_path.parent.name}")
            r = self.get(url)
            if not r or r.status_code != 200:
                log.warning(f"    Impossible d'accéder : {url}")
                continue

            soup = BeautifulSoup(r.text, "html.parser")

            # Aussi scraper les sous-pages (pages/) de ce cours
            pages_dir = html_path.parent / "pages"
            if pages_dir.exists():
                self._rescrape_subpages(soup, pages_dir)

            soup = self._rewrite_page(soup, html_path)
            self._save_html(soup, html_path)

        log.info("  Re-scrape des cours terminé")

    def _rescrape_subpages(self, course_soup, pages_dir):
        """Re-scrape les activités 'Page' d'un cours."""
        for li in course_soup.find_all("li", class_="activity"):
            classes = li.get("class", [])
            if not any("modtype_page" in c for c in classes):
                continue
            a = li.find("a", href=True)
            if not a:
                continue
            url = self.abs_url(a["href"])
            if url not in self.url_map:
                continue
            html_path = Path(self.url_map[url])
            r = self.get(url)
            if not r or r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            soup = self._rewrite_page(soup, html_path)
            self._save_html(soup, html_path)

    # ----------------------------------------------------------
    # MISE À JOUR DU MAPPING
    # ----------------------------------------------------------
    def save_mapping(self):
        mapping = {url: str(p) for url, p in self.url_map.items()
                   if not url.endswith("/")}  # éviter les doublons /my/ et /my
        MAPPING_FILE.write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info(f"mapping.json mis à jour ({len(mapping)} entrées)")

    # ----------------------------------------------------------
    # POINT D'ENTRÉE
    # ----------------------------------------------------------
    def run(self):
        self.load_mapping()
        self.login()
        self.scrape_nav_pages()
        self.rescrape_course_html()
        self.save_mapping()
        log.info("\nPatch navigation terminé.")
        log.info(f"Ouvrir : {OFFLINE_DIR / 'index.html'}")


# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("   PATCH NAVIGATION — Moodle Offline")
    print("=" * 55)

    if PASSWORD_FILE.exists():
        username = "id2813"
        password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
        print(f"   Identifiants lus depuis {PASSWORD_FILE.name}")
    else:
        username = input("Username : ").strip()
        password = getpass.getpass("Mot de passe : ")

    patcher = NavPatcher(username, password)
    patcher.run()
