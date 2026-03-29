#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moodle Offline Scraper
======================
Crée un miroir local entièrement navigable d'un site Moodle.
Inspiré de enregistrer-un-site-cahier-de-prepa (bsrdtoms).

Structure générée :
  moodle_offline/
  ├── index.html               ← page d'accueil (liste des cours)
  ├── assets/                  ← CSS, JS, fonts, images du thème
  ├── cours/
  │   ├── nom_du_cours/
  │   │   ├── index.html       ← page principale du cours
  │   │   ├── fichiers/        ← PDFs, DOCX, etc.
  │   │   └── pages/           ← pages Moodle inline
  │   └── ...
  └── moodle_scraper.log
"""

import os
import re
import sys
import json
import time
import getpass
import logging
import argparse
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURATION — modifiez ici si nécessaire
# ============================================================
MOODLE_URL   = "https://foad-moodle.ensai.fr"
OUTPUT_DIR   = Path(__file__).parent / "moodle_offline"
LOG_FILE     = Path(__file__).parent / "moodle_scraper.log"
DELAY        = 0.3   # secondes entre les requêtes (respecter le serveur)

# ============================================================
# LOGGING
# ============================================================
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        _stream_handler,
    ],
)
log = logging.getLogger(__name__)


# ============================================================
# SCRAPER
# ============================================================
class MoodleScraper:
    def __init__(self, username, password, output_dir=OUTPUT_DIR,
                 test_mode=False, max_courses=None):
        self.base_url    = MOODLE_URL.rstrip("/")
        self.username    = username
        self.password    = password
        self.output_dir  = Path(output_dir)
        self.test_mode   = test_mode
        self.max_courses = max_courses

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

        # Stats
        self.pages_saved       = 0
        self.files_downloaded  = 0
        self.files_failed      = []
        self.start_time        = time.time()

        # Mapping URL Moodle → chemin local (pour réécriture des liens)
        self.url_map           = {}   # url → Path absolu local
        self.assets_done       = set()

    # ----------------------------------------------------------
    # UTILITAIRES
    # ----------------------------------------------------------
    def sanitize(self, name, max_len=80):
        """Nettoie un nom pour en faire un nom de fichier/dossier valide."""
        name = unquote(name)
        name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
        name = re.sub(r"\s+", "_", name).strip("._")
        return name[:max_len] or "sans_nom"

    def abs_url(self, href):
        """Retourne l'URL absolue depuis une href."""
        if not href:
            return ""
        if href.startswith("http"):
            return href
        return urljoin(self.base_url, href)

    def is_moodle_url(self, url):
        """Vérifie si l'URL appartient à ce Moodle."""
        return url.startswith(self.base_url)

    def relpath(self, target, base_file):
        """Chemin relatif de target par rapport au dossier de base_file."""
        try:
            return os.path.relpath(str(target), str(Path(base_file).parent))
        except ValueError:
            # Sur Windows si les lecteurs diffèrent
            return str(target)

    def get(self, url, **kwargs):
        """GET avec gestion des erreurs et délai."""
        time.sleep(DELAY)
        try:
            r = self.session.get(url, timeout=60, **kwargs)
            return r
        except Exception as e:
            log.warning(f"  GET échoué: {url} — {e}")
            return None

    # ----------------------------------------------------------
    # CONNEXION
    # ----------------------------------------------------------
    def login(self):
        """
        Connexion à Moodle.
        Détecte automatiquement CAS (ssocas.ensai.fr) ou formulaire standard.
        """
        login_url = f"{self.base_url}/login/index.php"
        log.info("Connexion à Moodle...")

        r = self.get(login_url)
        if not r:
            raise Exception("Impossible d'accéder à la page de login")

        # --- Détecter si on est redirigé vers CAS ---
        if "ssocas" in r.url or "cas" in r.url:
            return self._login_cas(r)
        else:
            return self._login_standard(r)

    def _login_cas(self, r):
        """Login via CAS (Central Authentication Service) de l'ENSAI."""
        cas_url = r.url
        log.info(f"  CAS detecte : {cas_url.split('?')[0]}")

        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise Exception("Formulaire CAS introuvable")

        # Recuperer TOUS les champs caches (execution, _eventId, geolocation...)
        data = {}
        for inp in form.find_all("input"):
            name  = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                data[name] = value

        # Injecter les identifiants (essai 1 : username complet)
        data["username"]   = self.username
        data["password"]   = self.password
        data["_eventId"]   = "submit"
        data["geolocation"] = ""

        # POST vers l'action du formulaire CAS
        action = form.get("action", "")
        if not action.startswith("http"):
            action = urljoin(cas_url, action)

        log.info(f"  POST CAS : {action.split('?')[0]}")
        log.info(f"  Champs : {list(data.keys())}")

        time.sleep(DELAY)
        r2 = self.session.post(action, data=data, timeout=30, allow_redirects=True)
        log.info(f"  Reponse : {r2.status_code} {r2.url[:80]}")

        # Si encore sur CAS → essayer avec username court (sans @ensai.fr)
        if "ssocas" in r2.url:
            soup2 = BeautifulSoup(r2.text, "html.parser")
            form2 = soup2.find("form")
            if form2:
                data2 = {inp.get("name",""): inp.get("value","")
                         for inp in form2.find_all("input") if inp.get("name")}
                short = self.username.split("@")[0] if "@" in self.username else self.username
                data2["username"]    = short
                data2["password"]    = self.password
                data2["_eventId"]    = "submit"
                data2["geolocation"] = ""
                action2 = form2.get("action", "")
                if not action2.startswith("http"):
                    action2 = urljoin(r2.url, action2)
                log.info(f"  2e tentative avec username : {short}")
                time.sleep(DELAY)
                r2 = self.session.post(action2, data=data2, timeout=30, allow_redirects=True)
                log.info(f"  Reponse 2 : {r2.status_code} {r2.url[:80]}")

        # Echec definitif si encore sur CAS
        if "ssocas" in r2.url:
            soup_err = BeautifulSoup(r2.text, "html.parser")
            err = (soup_err.find(class_="errors") or
                   soup_err.find(id="msg") or
                   soup_err.find(class_="alert"))
            msg = err.get_text(strip=True) if err else "identifiants incorrects"
            raise Exception(f"Connexion CAS echouee : {msg}")

        # Verifier la session Moodle
        time.sleep(DELAY)
        r3 = self.session.get(f"{self.base_url}/my/", timeout=30)
        if "login" in r3.url or "ssocas" in r3.url:
            raise Exception("Session Moodle non etablie apres CAS")

        log.info("Connexion CAS reussie")
        return True

    def _login_standard(self, r):
        """Login via formulaire Moodle standard."""
        soup = BeautifulSoup(r.text, "html.parser")
        token_input = soup.find("input", {"name": "logintoken"})
        logintoken  = token_input["value"] if token_input else ""

        data = {
            "username":   self.username,
            "password":   self.password,
            "logintoken": logintoken,
            "anchor":     "",
        }
        login_url = f"{self.base_url}/login/index.php"
        time.sleep(DELAY)
        r2 = self.session.post(login_url, data=data, timeout=30)

        if "login" in r2.url:
            soup2 = BeautifulSoup(r2.text, "html.parser")
            err = soup2.find(class_="loginerrors") or soup2.find(id="loginerrormessage")
            msg = err.get_text(strip=True) if err else "vérifiez vos identifiants"
            raise Exception(f"Connexion échouée : {msg}")

        log.info("✓ Connexion réussie")
        return True

    # ----------------------------------------------------------
    # LISTE DES COURS
    # ----------------------------------------------------------
    def get_all_courses(self):
        """Récupère la liste des cours depuis la page 'Mes cours'."""
        log.info("Recuperation de la liste des cours...")
        # /my/courses.php charge via JS — on utilise /my/ qui a les liens statiques
        r = self.get(f"{self.base_url}/my/")
        if not r:
            r = self.get(f"{self.base_url}/my/courses.php")
        if not r:
            raise Exception("Impossible d'accéder aux cours")

        soup = BeautifulSoup(r.text, "html.parser")
        courses = []
        seen_ids = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/course/view.php?id=" in href:
                m = re.search(r"id=(\d+)", href)
                if m:
                    cid = m.group(1)
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    name = a.get_text(strip=True) or f"cours_{cid}"
                    # Nettoyage du nom (enlever doublons genre "Nom\nNom")
                    lines = [l.strip() for l in name.splitlines() if l.strip()]
                    name  = lines[0] if lines else name
                    courses.append({
                        "id":   cid,
                        "name": name,
                        "url":  f"{self.base_url}/course/view.php?id={cid}",
                    })

        log.info(f"→ {len(courses)} cours trouvés")
        for c in courses:
            log.info(f"   • [{c['id']}] {c['name']}")
        return courses

    # ----------------------------------------------------------
    # ASSETS (CSS / JS / FONTS / IMAGES)
    # ----------------------------------------------------------
    def download_asset(self, url, assets_dir):
        """Télécharge un asset et retourne son chemin local."""
        if not url or not self.is_moodle_url(url):
            return None
        if url in self.assets_done:
            return self.url_map.get(url)

        parsed   = urlparse(url)
        rel_path = parsed.path.lstrip("/")
        # Enlever les query strings dans le nom de fichier
        local    = assets_dir / rel_path
        local.parent.mkdir(parents=True, exist_ok=True)

        if not local.exists():
            r = self.get(url, stream=True)
            if r and r.status_code == 200:
                with open(local, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                # Si c'est un CSS, télécharger ses ressources internes
                if local.suffix.lower() == ".css":
                    self._process_css(local, url, assets_dir)
            else:
                return None

        self.assets_done.add(url)
        self.url_map[url] = local
        return local

    def _process_css(self, css_path, css_url, assets_dir):
        """Parse un CSS et télécharge ses assets référencés (fonts, images)."""
        try:
            text = css_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        urls = re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', text)
        for u in urls:
            if u.startswith("data:"):
                continue
            abs_u = urljoin(css_url, u)
            self.download_asset(abs_u, assets_dir)

    # ----------------------------------------------------------
    # TÉLÉCHARGEMENT DE FICHIERS DE COURS
    # ----------------------------------------------------------
    def download_resource(self, url, dest_dir):
        """
        Télécharge un fichier de ressource Moodle.
        Suit la redirection pluginfile.php.
        Retourne le chemin local ou None.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        r = self.get(url, allow_redirects=True, stream=True)
        if not r or r.status_code != 200:
            log.warning(f"  ✗ Erreur {r.status_code if r else 'timeout'}: {url}")
            self.files_failed.append({"url": url, "error": str(r.status_code if r else "timeout")})
            return None

        # Nom du fichier
        filename = self._guess_filename(r)
        local    = dest_dir / self.sanitize(filename)

        # Éviter les doublons
        if local.exists():
            base, ext = local.stem, local.suffix
            i = 1
            while local.exists():
                local = dest_dir / f"{self.sanitize(base)}_{i}{ext}"
                i += 1

        with open(local, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

        self.files_downloaded += 1
        size_kb = local.stat().st_size // 1024
        log.info(f"  ↓ {local.name} ({size_kb} Ko)")
        return local

    def _guess_filename(self, response):
        """Deduit le nom de fichier depuis les headers ou l'URL."""
        cd = response.headers.get("Content-Disposition", "")
        name = None
        if "filename*=" in cd:
            m = re.search(r"filename\*=(?:UTF-8'')?([^\s;]+)", cd)
            if m:
                name = unquote(m.group(1).strip('"\''), encoding="utf-8")
        if not name and "filename=" in cd:
            m = re.findall(r'filename=["\']?([^"\';\n]+)', cd)
            if m:
                raw = m[0].strip('"\'')
                # Réparer le double encodage latin-1/utf-8 (Ã© → é)
                try:
                    name = raw.encode("latin-1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    name = unquote(raw)
        if not name:
            path = urlparse(response.url).path
            raw  = unquote(path.split("/")[-1])
            try:
                name = raw.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                name = raw
        return name if name else "fichier"

    # ----------------------------------------------------------
    # SCRAPING D'UNE PAGE DE COURS
    # ----------------------------------------------------------
    def scrape_course(self, course, assets_dir):
        """Scrape une page de cours : HTML + tous les fichiers."""
        safe_name  = self.sanitize(course["name"])
        course_dir = self.output_dir / "cours" / safe_name
        files_dir  = course_dir / "fichiers"
        pages_dir  = course_dir / "pages"
        course_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"\n{'='*55}")
        log.info(f"[Cours] {course['name']}  (id={course['id']})")

        r = self.get(course["url"])
        if not r:
            log.error(f"  ✗ Impossible d'accéder au cours")
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        html_path = course_dir / "index.html"

        # --- Télécharger les fichiers et collecter le mapping URL→local ---
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

            elif act["type"] == "url":
                # Lien externe : on garde l'URL d'origine
                pass

            # forums, quiz, assign… : on garde les liens tels quels

        # --- Réécrire la page HTML ---
        soup = self._rewrite_page(soup, html_path, assets_dir)
        self._save_html(soup, html_path)
        self.pages_saved += 1
        self.url_map[course["url"]] = html_path
        log.info(f"  ✓ Page cours sauvegardée")
        return course_dir

    def _parse_activities(self, soup):
        """Retourne la liste des activités d'une page de cours."""
        acts = []
        for li in soup.find_all("li", class_="activity"):
            classes  = li.get("class", [])
            mod_type = next((c.replace("modtype_", "") for c in classes
                             if c.startswith("modtype_")), "unknown")
            a = li.find("a", href=True)
            if not a:
                continue
            href = self.abs_url(a["href"])
            name_tag = (li.find(class_="instancename") or
                        li.find(class_="activityname") or a)
            name = name_tag.get_text(strip=True) if name_tag else ""
            acts.append({"type": mod_type, "name": name, "href": href})
        return acts

    def _scrape_moodle_page(self, url, pages_dir, assets_dir, course_dir):
        """Scrape une activité 'Page' Moodle (contenu HTML inline)."""
        r = self.get(url)
        if not r or r.status_code != 200:
            return None
        soup      = BeautifulSoup(r.text, "html.parser")
        # Extraire un nom propre depuis le titre
        title     = soup.find("title")
        name      = title.get_text(strip=True).split("|")[0].strip() if title else "page"
        filename  = self.sanitize(name) + ".html"
        pages_dir.mkdir(parents=True, exist_ok=True)
        html_path = pages_dir / filename

        soup = self._rewrite_page(soup, html_path, assets_dir)
        self._save_html(soup, html_path)
        self.pages_saved += 1
        log.info(f"  ↓ Page: {filename}")
        return html_path

    def _scrape_folder(self, url, files_dir, assets_dir):
        """Scrape un dossier Moodle et télécharge tous ses fichiers."""
        r = self.get(url)
        if not r:
            return
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/pluginfile.php/" in href:
                abs_href = self.abs_url(href)
                local = self.download_resource(abs_href, files_dir)
                if local:
                    self.url_map[abs_href] = local

    # ----------------------------------------------------------
    # RÉÉCRITURE DES LIENS POUR NAVIGATION HORS LIGNE
    # ----------------------------------------------------------
    def _rewrite_page(self, soup, html_path, assets_dir):
        """Réécrit tous les liens d'une page pour usage hors ligne."""

        # CSS
        for tag in soup.find_all("link", rel=True):
            if "stylesheet" in tag.get("rel", []):
                href = self.abs_url(tag.get("href", ""))
                if href and self.is_moodle_url(href):
                    local = self.download_asset(href, assets_dir)
                    if local:
                        tag["href"] = self.relpath(local, html_path)

        # JS
        for tag in soup.find_all("script", src=True):
            src = self.abs_url(tag["src"])
            if src and self.is_moodle_url(src):
                local = self.download_asset(src, assets_dir)
                if local:
                    tag["src"] = self.relpath(local, html_path)

        # Images
        for tag in soup.find_all("img", src=True):
            src = self.abs_url(tag["src"])
            if src and self.is_moodle_url(src):
                local = self.download_asset(src, assets_dir)
                if local:
                    tag["src"] = self.relpath(local, html_path)

        # Liens de cours et ressources → fichiers locaux
        for tag in soup.find_all("a", href=True):
            href = self.abs_url(tag["href"])
            if href in self.url_map:
                local = self.url_map[href]
                tag["href"] = self.relpath(local, html_path)

        # Supprimer les balises <base> qui cassent la navigation hors ligne
        for tag in soup.find_all("base"):
            tag.decompose()

        return soup

    def _save_html(self, soup, path):
        """Sauvegarde le HTML proprement."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n")
            f.write(str(soup))

    # ----------------------------------------------------------
    # PAGE D'INDEX (LISTE DES COURS)
    # ----------------------------------------------------------
    def build_index(self, courses, assets_dir):
        """Crée index.html à partir de la page 'Mes cours'."""
        log.info("\nCréation de la page d'accueil...")

        r = self.get(f"{self.base_url}/my/courses.php") or self.get(f"{self.base_url}/my/")
        if not r:
            log.warning("  Impossible de récupérer la page d'accueil, création manuelle")
            self._build_simple_index(courses)
            return

        soup     = BeautifulSoup(r.text, "html.parser")
        idx_path = self.output_dir / "index.html"

        # Réécrire les liens de cours
        for a in soup.find_all("a", href=True):
            href = self.abs_url(a["href"])
            if href in self.url_map:
                a["href"] = self.relpath(self.url_map[href], idx_path)

        soup = self._rewrite_page(soup, idx_path, assets_dir)
        self._save_html(soup, idx_path)
        self.pages_saved += 1
        log.info(f"✓ Index créé : {idx_path}")

    def _build_simple_index(self, courses):
        """Page d'index de secours si la récupération du dashboard échoue."""
        idx_path = self.output_dir / "index.html"
        items = ""
        for c in courses:
            safe  = self.sanitize(c["name"])
            items += f'<li><a href="cours/{safe}/index.html">{c["name"]}</a></li>\n'
        html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>Moodle Offline – {self.base_url}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ color: #c00; }} ul {{ line-height: 2; }} a {{ color: #003d7a; }}
</style></head><body>
<h1>Mes cours — Moodle Offline</h1>
<p>Site : <code>{self.base_url}</code></p>
<ul>{items}</ul>
</body></html>"""
        idx_path.write_text(html, encoding="utf-8")
        self.pages_saved += 1
        log.info(f"✓ Index de secours créé : {idx_path}")

    # ----------------------------------------------------------
    # LANCEMENT PRINCIPAL
    # ----------------------------------------------------------
    def run(self):
        """Point d'entrée : scraping complet."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # 1. Connexion
        self.login()

        # 2. Liste des cours
        courses = self.get_all_courses()

        if self.test_mode:
            courses = courses[:2]
            log.info(f"\n[MODE TEST] Limité à {len(courses)} cours")
        elif self.max_courses:
            courses = courses[: self.max_courses]

        # 3. Scraper chaque cours
        for i, course in enumerate(courses, 1):
            log.info(f"\n[{i}/{len(courses)}]")
            try:
                self.scrape_course(course, assets_dir)
            except KeyboardInterrupt:
                log.warning("Interruption clavier — arrêt propre.")
                break
            except Exception as e:
                log.error(f"  ✗ Erreur cours '{course['name']}': {e}")

        # 4. Index
        self.build_index(courses, assets_dir)

        # 5. Mapping JSON
        mapping = {k: str(v) for k, v in self.url_map.items()}
        (self.output_dir / "mapping.json").write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 6. Résumé
        duration = int(time.time() - self.start_time)
        log.info(f"""
{'='*60}
RÉSUMÉ
{'='*60}
Pages HTML sauvegardées  : {self.pages_saved}
Fichiers téléchargés     : {self.files_downloaded}
Assets téléchargés       : {len(self.assets_done)}
Fichiers échoués         : {len(self.files_failed)}
Durée totale             : {duration // 60}m {duration % 60}s
{'='*60}
✅ SITE PRÊT : {self.output_dir}
🌐 Ouvrir   : {self.output_dir / 'index.html'}
{'='*60}""")

        if self.files_failed:
            log.info("Fichiers échoués :")
            for f in self.files_failed:
                log.info(f"  • {f['url']} : {f['error']}")


# ============================================================
# POINT D'ENTRÉE
# ============================================================



def main():
    parser = argparse.ArgumentParser(
        description="Moodle Offline Scraper — crée un miroir local navigable"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Mode test : scrape seulement 2 cours (validation rapide)"
    )
    parser.add_argument(
        "--courses", type=int, metavar="N",
        help="Limiter à N cours"
    )
    parser.add_argument(
        "--output", type=str,
        help=f"Dossier de sortie (défaut : {OUTPUT_DIR})"
    )
    args = parser.parse_args()


    print("=" * 60)
    print("   MOODLE OFFLINE SCRAPER")
    print(f"   Site : {MOODLE_URL}")
    if args.test:
        print("   [MODE TEST — 2 cours maximum]")
    print("=" * 60)

    # Les identifiants peuvent aussi être passés via variables d'environnement :
    #   MOODLE_USERNAME et MOODLE_PASSWORD
    username = os.environ.get("MOODLE_USERNAME") or input("Email / username : ").strip()
    password = os.environ.get("MOODLE_PASSWORD") or getpass.getpass("Mot de passe    : ")

    output = Path(args.output) if args.output else OUTPUT_DIR

    scraper = MoodleScraper(
        username=username,
        password=password,
        output_dir=output,
        test_mode=args.test,
        max_courses=args.courses,
    )
    scraper.run()


if __name__ == "__main__":
    main()
