#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moodle Offline Scraper — Universel
===================================
Crée un miroir local entièrement navigable de n'importe quel Moodle.
Inspiré de enregistrer-un-site-cahier-de-prepa (bsrdtoms).

Usage :
  python moodle_scraper.py                    ← demande l'URL au lancement
  python moodle_scraper.py --url https://...  ← URL directement
  python moodle_scraper.py --test             ← mode test (2 cours)

Authentification automatique :
  - CAS (ex. ENSAI)         → login automatique username/password
  - Formulaire standard     → login automatique username/password
  - SSO/OAuth/Shibboleth    → fenêtre Chrome ouverte pour login manuel

Structure générée :
  moodle_offline_<domaine>/
  ├── index.html
  ├── assets/
  ├── cours/
  │   └── nom_cours/
  │       ├── index.html
  │       ├── fichiers/
  │       └── pages/
  └── mapping.json
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

DELAY = 0.3  # secondes entre les requêtes (respecter le serveur)

# ============================================================
# LOGGING — configuré dynamiquement dans main()
# ============================================================
log = logging.getLogger(__name__)


def setup_logging(log_file: Path):
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stream = logging.StreamHandler(sys.stdout)
    try:
        stream.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            stream,
        ],
    )


# ============================================================
# SCRAPER
# ============================================================
class MoodleScraper:
    def __init__(self, moodle_url, output_dir,
                 username=None, password=None,
                 test_mode=False, max_courses=None):
        self.base_url    = moodle_url.rstrip("/")
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

        self.pages_saved      = 0
        self.files_downloaded = 0
        self.files_failed     = []
        self.start_time       = time.time()
        self.url_map          = {}
        self.assets_done      = set()

    # ----------------------------------------------------------
    # UTILITAIRES
    # ----------------------------------------------------------
    def sanitize(self, name, max_len=80):
        name = unquote(name)
        name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
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
            return os.path.relpath(str(target), str(Path(base_file).parent))
        except ValueError:
            return str(target)

    def get(self, url, **kwargs):
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
        Détecte automatiquement le type d'auth :
          - CAS              → login automatique (requests)
          - Formulaire std   → login automatique (requests)
          - SSO/OAuth/Shib   → fenêtre Chrome (login manuel)
        """
        login_url = f"{self.base_url}/login/index.php"
        log.info(f"Connexion à {self.base_url} ...")

        r = self.get(login_url)
        if not r:
            raise Exception("Impossible d'accéder à la page de login")

        final_url = r.url
        domain    = urlparse(self.base_url).netloc

        # Déjà connecté ?
        if domain in final_url and "login" not in final_url:
            log.info("✓ Déjà connecté")
            return True

        # CAS (ssocas.ensai.fr ou tout serveur cas.*)
        if "ssocas" in final_url or re.search(r"//cas\.", final_url):
            self._ensure_credentials("CAS")
            return self._login_cas(r)

        # Formulaire Moodle standard (reste sur le domaine Moodle)
        if domain in final_url:
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.find("input", {"name": "logintoken"}) or soup.find("input", {"name": "username"}):
                self._ensure_credentials("formulaire Moodle")
                return self._login_standard(r)

        # Tout autre SSO (Shibboleth, Microsoft OAuth, Google, etc.)
        log.info(f"  SSO détecté (redirection vers {final_url.split('?')[0]})")
        return self._login_browser(login_url)

    def _ensure_credentials(self, auth_type):
        """Demande username/password si pas déjà définis."""
        if not self.username:
            self.username = input(f"  [{auth_type}] Email / username : ").strip()
        if not self.password:
            self.password = getpass.getpass(f"  [{auth_type}] Mot de passe    : ")

    def _login_cas(self, r):
        """Login via CAS (Central Authentication Service)."""
        cas_url = r.url
        log.info(f"  CAS détecté : {cas_url.split('?')[0]}")

        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise Exception("Formulaire CAS introuvable")

        data = {inp.get("name", ""): inp.get("value", "")
                for inp in form.find_all("input") if inp.get("name")}
        data["username"]    = self.username
        data["password"]    = self.password
        data["_eventId"]    = "submit"
        data["geolocation"] = ""

        action = form.get("action", "")
        if not action.startswith("http"):
            action = urljoin(cas_url, action)

        time.sleep(DELAY)
        r2 = self.session.post(action, data=data, timeout=30, allow_redirects=True)

        # 2e tentative avec username court (sans @domaine)
        if "cas" in r2.url or "ssocas" in r2.url:
            soup2 = BeautifulSoup(r2.text, "html.parser")
            form2 = soup2.find("form")
            if form2:
                data2 = {inp.get("name", ""): inp.get("value", "")
                         for inp in form2.find_all("input") if inp.get("name")}
                short = self.username.split("@")[0] if "@" in self.username else self.username
                data2.update(username=short, password=self.password,
                             _eventId="submit", geolocation="")
                action2 = form2.get("action", "")
                if not action2.startswith("http"):
                    action2 = urljoin(r2.url, action2)
                log.info(f"  2e tentative : {short}")
                time.sleep(DELAY)
                r2 = self.session.post(action2, data=data2, timeout=30, allow_redirects=True)

        if "cas" in r2.url or "ssocas" in r2.url:
            soup_err = BeautifulSoup(r2.text, "html.parser")
            err = (soup_err.find(class_="errors") or
                   soup_err.find(id="msg") or
                   soup_err.find(class_="alert"))
            raise Exception(f"Connexion CAS échouée : {err.get_text(strip=True) if err else 'identifiants incorrects'}")

        time.sleep(DELAY)
        r3 = self.session.get(f"{self.base_url}/my/", timeout=30)
        if "login" in r3.url:
            raise Exception("Session Moodle non établie après CAS")

        log.info("✓ Connexion CAS réussie")
        return True

    def _login_standard(self, r):
        """Login via formulaire Moodle standard (username/password)."""
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
            raise Exception(f"Connexion échouée : {err.get_text(strip=True) if err else 'vérifiez vos identifiants'}")

        log.info("✓ Connexion réussie")
        return True

    def _login_browser(self, login_url):
        """
        Ouvre une fenêtre Chrome visible pour login manuel (SSO/OAuth/Shibboleth).
        Transfère automatiquement les cookies vers la session requests.
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            raise Exception(
                "Selenium requis pour ce type de connexion.\n"
                "Installe-le avec : pip install selenium"
            )

        log.info("=" * 60)
        log.info("  CONNEXION MANUELLE REQUISE")
        log.info("  → Une fenêtre Chrome va s'ouvrir.")
        log.info("  → Connecte-toi normalement (SSO, Microsoft, etc.).")
        log.info("  → La fenêtre se ferme automatiquement après connexion.")
        log.info("=" * 60)

        opts = ChromeOptions()
        opts.add_argument("--start-maximized")
        driver = webdriver.Chrome(options=opts)

        try:
            driver.get(login_url)
            domain = urlparse(self.base_url).netloc

            log.info("En attente de connexion (3 min max)...")
            WebDriverWait(driver, 180).until(
                lambda d: domain in d.current_url and "login" not in d.current_url
            )
            log.info(f"✓ Connecté — URL : {driver.current_url}")

            # Transférer les cookies vers requests
            for cookie in driver.get_cookies():
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", "").lstrip("."),
                )
                if cookie["name"] == "MoodleSession":
                    log.info(f"  MoodleSession transférée : {cookie['value'][:12]}...")

        finally:
            driver.quit()

        time.sleep(1)
        r = self.session.get(f"{self.base_url}/my/", timeout=30)
        if "login" in r.url:
            raise Exception("Session Moodle non établie après connexion navigateur")

        log.info("✓ Session requests opérationnelle")
        return True

    # ----------------------------------------------------------
    # LISTE DES COURS
    # ----------------------------------------------------------
    def get_all_courses(self):
        log.info("Récupération de la liste des cours...")
        r = self.get(f"{self.base_url}/my/")
        if not r:
            r = self.get(f"{self.base_url}/my/courses.php")
        if not r:
            raise Exception("Impossible d'accéder aux cours")

        soup = BeautifulSoup(r.text, "html.parser")
        courses  = []
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
                    name  = a.get_text(strip=True) or f"cours_{cid}"
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
        if not url or not self.is_moodle_url(url):
            return None
        if url in self.assets_done:
            return self.url_map.get(url)

        parsed   = urlparse(url)
        rel_path = parsed.path.lstrip("/")
        local    = assets_dir / rel_path
        local.parent.mkdir(parents=True, exist_ok=True)

        if not local.exists():
            r = self.get(url, stream=True)
            if r and r.status_code == 200:
                with open(local, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                if local.suffix.lower() == ".css":
                    self._process_css(local, url, assets_dir)
            else:
                return None

        self.assets_done.add(url)
        self.url_map[url] = local
        return local

    def _process_css(self, css_path, css_url, assets_dir):
        try:
            text = css_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        for u in re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', text):
            if not u.startswith("data:"):
                self.download_asset(urljoin(css_url, u), assets_dir)

    # ----------------------------------------------------------
    # TÉLÉCHARGEMENT DE FICHIERS
    # ----------------------------------------------------------
    def download_resource(self, url, dest_dir):
        dest_dir.mkdir(parents=True, exist_ok=True)
        r = self.get(url, allow_redirects=True, stream=True)
        if not r or r.status_code != 200:
            log.warning(f"  ✗ Erreur {r.status_code if r else 'timeout'}: {url}")
            self.files_failed.append({"url": url, "error": str(r.status_code if r else "timeout")})
            return None

        filename = self._guess_filename(r)
        local    = dest_dir / self.sanitize(filename)

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
        log.info(f"  ↓ {local.name} ({local.stat().st_size // 1024} Ko)")
        return local

    def _guess_filename(self, response):
        cd   = response.headers.get("Content-Disposition", "")
        name = None
        if "filename*=" in cd:
            m = re.search(r"filename\*=(?:UTF-8'')?([^\s;]+)", cd)
            if m:
                name = unquote(m.group(1).strip('"\''), encoding="utf-8")
        if not name and "filename=" in cd:
            m = re.findall(r'filename=["\']?([^"\';\n]+)', cd)
            if m:
                raw = m[0].strip('"\'')
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
        return name or "fichier"

    # ----------------------------------------------------------
    # SCRAPING D'UNE PAGE DE COURS
    # ----------------------------------------------------------
    def scrape_course(self, course, assets_dir):
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

        soup = self._rewrite_page(soup, html_path, assets_dir)
        self._save_html(soup, html_path)
        self.pages_saved += 1
        self.url_map[course["url"]] = html_path
        log.info("  ✓ Page cours sauvegardée")
        return course_dir

    def _parse_activities(self, soup):
        acts = []
        for li in soup.find_all("li", class_="activity"):
            classes  = li.get("class", [])
            mod_type = next((c.replace("modtype_", "") for c in classes
                             if c.startswith("modtype_")), "unknown")
            a = li.find("a", href=True)
            if not a:
                continue
            href     = self.abs_url(a["href"])
            name_tag = (li.find(class_="instancename") or
                        li.find(class_="activityname") or a)
            acts.append({"type": mod_type,
                         "name": name_tag.get_text(strip=True) if name_tag else "",
                         "href": href})
        return acts

    def _scrape_moodle_page(self, url, pages_dir, assets_dir, course_dir):
        r = self.get(url)
        if not r or r.status_code != 200:
            return None
        soup     = BeautifulSoup(r.text, "html.parser")
        title    = soup.find("title")
        name     = title.get_text(strip=True).split("|")[0].strip() if title else "page"
        filename = self.sanitize(name) + ".html"
        pages_dir.mkdir(parents=True, exist_ok=True)
        html_path = pages_dir / filename

        soup = self._rewrite_page(soup, html_path, assets_dir)
        self._save_html(soup, html_path)
        self.pages_saved += 1
        log.info(f"  ↓ Page: {filename}")
        return html_path

    def _scrape_folder(self, url, files_dir, assets_dir):
        r = self.get(url)
        if not r:
            return
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if "/pluginfile.php/" in a["href"]:
                abs_href = self.abs_url(a["href"])
                local    = self.download_resource(abs_href, files_dir)
                if local:
                    self.url_map[abs_href] = local

    # ----------------------------------------------------------
    # RÉÉCRITURE DES LIENS
    # ----------------------------------------------------------
    def _rewrite_page(self, soup, html_path, assets_dir):
        for tag in soup.find_all("link", rel=True):
            if "stylesheet" in tag.get("rel", []):
                href = self.abs_url(tag.get("href", ""))
                if href and self.is_moodle_url(href):
                    local = self.download_asset(href, assets_dir)
                    if local:
                        tag["href"] = self.relpath(local, html_path)

        for tag in soup.find_all("script", src=True):
            src = self.abs_url(tag["src"])
            if src and self.is_moodle_url(src):
                local = self.download_asset(src, assets_dir)
                if local:
                    tag["src"] = self.relpath(local, html_path)

        for tag in soup.find_all("img", src=True):
            src = self.abs_url(tag["src"])
            if src and self.is_moodle_url(src):
                local = self.download_asset(src, assets_dir)
                if local:
                    tag["src"] = self.relpath(local, html_path)

        for tag in soup.find_all("a", href=True):
            href = self.abs_url(tag["href"])
            if href in self.url_map:
                # Lien téléchargé → chemin local relatif
                tag["href"] = self.relpath(self.url_map[href], html_path)
            elif self.is_moodle_url(href) or tag["href"].startswith("/"):
                # Lien interne Moodle non téléchargé → désactiver
                tag["href"] = "#"

        for tag in soup.find_all("base"):
            tag.decompose()

        return soup

    def _save_html(self, soup, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n")
            f.write(str(soup))

    # ----------------------------------------------------------
    # PAGE D'INDEX
    # ----------------------------------------------------------
    def build_index(self, courses, assets_dir):
        log.info("\nCréation de la page d'accueil...")
        r = self.get(f"{self.base_url}/my/courses.php") or self.get(f"{self.base_url}/my/")
        if not r:
            self._build_simple_index(courses)
            return

        soup     = BeautifulSoup(r.text, "html.parser")
        idx_path = self.output_dir / "index.html"

        for a in soup.find_all("a", href=True):
            href = self.abs_url(a["href"])
            if href in self.url_map:
                a["href"] = self.relpath(self.url_map[href], idx_path)

        soup = self._rewrite_page(soup, idx_path, assets_dir)
        self._save_html(soup, idx_path)
        self.pages_saved += 1
        log.info(f"✓ Index créé : {idx_path}")

    def _build_simple_index(self, courses):
        idx_path = self.output_dir / "index.html"
        items = "".join(
            f'<li><a href="cours/{self.sanitize(c["name"])}/index.html">{c["name"]}</a></li>\n'
            for c in courses
        )
        html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>Moodle Offline – {self.base_url}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ color: #003d7a; }} ul {{ line-height: 2; }} a {{ color: #003d7a; }}
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
        self.output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = self.output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        self.login()
        courses = self.get_all_courses()

        if self.test_mode:
            courses = courses[:2]
            log.info(f"\n[MODE TEST] Limité à {len(courses)} cours")
        elif self.max_courses:
            courses = courses[:self.max_courses]

        for i, course in enumerate(courses, 1):
            log.info(f"\n[{i}/{len(courses)}]")
            try:
                self.scrape_course(course, assets_dir)
            except KeyboardInterrupt:
                log.warning("Interruption — arrêt propre.")
                break
            except Exception as e:
                log.error(f"  ✗ Erreur cours '{course['name']}': {e}")

        self.build_index(courses, assets_dir)

        mapping = {k: str(v) for k, v in self.url_map.items()}
        (self.output_dir / "mapping.json").write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
        )

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
        description="Moodle Offline Scraper — crée un miroir local navigable de n'importe quel Moodle"
    )
    parser.add_argument(
        "--url", type=str,
        help="URL du Moodle (ex: https://moodle.psl.eu). Demandé au lancement si absent."
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Mode test : scrape seulement 2 cours"
    )
    parser.add_argument(
        "--courses", type=int, metavar="N",
        help="Limiter à N cours"
    )
    parser.add_argument(
        "--output", type=str,
        help="Dossier de sortie (défaut : moodle_offline_<domaine>)"
    )
    args = parser.parse_args()

    # Demander l'URL si pas fournie
    moodle_url = args.url
    if not moodle_url:
        moodle_url = input("URL du Moodle (ex: https://moodle.psl.eu) : ").strip()
    if not moodle_url.startswith("http"):
        moodle_url = "https://" + moodle_url
    moodle_url = moodle_url.rstrip("/")

    # Dossier de sortie basé sur le domaine
    domain = urlparse(moodle_url).netloc
    base_dir = Path(__file__).parent
    output_dir = Path(args.output) if args.output else base_dir / f"moodle_offline_{domain}"
    log_file   = base_dir / f"moodle_scraper_{domain}.log"

    setup_logging(log_file)

    print("=" * 60)
    print("   MOODLE OFFLINE SCRAPER — Universel")
    print(f"   Site   : {moodle_url}")
    print(f"   Sortie : {output_dir}")
    if args.test:
        print("   [MODE TEST — 2 cours maximum]")
    print("=" * 60)
    print()

    scraper = MoodleScraper(
        moodle_url=moodle_url,
        output_dir=output_dir,
        test_mode=args.test,
        max_courses=args.courses,
    )
    scraper.run()


if __name__ == "__main__":
    main()
