#!/usr/bin/env python3
"""
Script complet pour télécharger et créer un miroir hors ligne de cahier-de-prepa.fr
- Télécharge toutes les pages HTML et fichiers
- Corrige automatiquement tous les liens
- Crée les fichiers de mapping et logs détaillés
- Prêt pour navigation hors ligne
"""

import os
import sys
import time
import json
import getpass
import re
import shutil
from pathlib import Path
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests
from bs4 import BeautifulSoup

# Configuration
OUTPUT_DIR = Path.home() / "cahier_prepa_offline"
OUTPUT_DIR_TEST = Path.home() / "cahier_prepa_test"  # Dossier séparé pour les tests
DOWNLOAD_DIR = Path.home() / "Téléchargements"
WAIT_TIME = 2  # Secondes entre les téléchargements

# Limites en mode TEST
TEST_MODE = False  # Sera activé par argument --test
TEST_MAX_REPOS = 1  # 1 seul répertoire principal
TEST_MAX_SUBPAGES = 10  # Maximum 10 sous-pages
TEST_MAX_FILES = 10  # Maximum 10 fichiers

def normalize_url(user_input):
    """
    Normalise l'URL saisie par l'utilisateur
    Accepte:
    - https://cahier-de-prepa.fr/ma-classe/
    - cahier-de-prepa.fr/ma-classe/
    - ma-classe
    - ma-classe/

    Retourne toujours: https://cahier-de-prepa.fr/ma-classe/
    """
    url = user_input.strip()

    # Retirer les slashes en fin
    url = url.rstrip('/')

    # Si c'est déjà une URL complète
    if url.startswith('https://cahier-de-prepa.fr/'):
        return url + '/'

    # Si c'est http au lieu de https
    if url.startswith('http://cahier-de-prepa.fr/'):
        return url.replace('http://', 'https://') + '/'

    # Si ça commence par cahier-de-prepa.fr/
    if url.startswith('cahier-de-prepa.fr/'):
        return 'https://' + url + '/'

    # Sinon, c'est juste le nom de la classe (ex: ma-classe)
    # On ajoute le préfixe complet
    return f'https://cahier-de-prepa.fr/{url}/'

class Logger:
    """Gestionnaire de logs détaillé"""
    def __init__(self, log_file):
        self.log_file = log_file
        self.start_time = datetime.now()

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + "\n")

    def section(self, title):
        separator = "=" * 60
        self.log(f"\n{separator}")
        self.log(f"  {title}")
        self.log(separator)

class SiteDownloader:
    def __init__(self, email, password, base_url, output_dir, logger, test_mode=False):
        self.email = email
        self.password = password
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.logger = logger
        self.test_mode = test_mode

        # Structure des dossiers
        self.assets_dir = self.output_dir / "assets"
        self.fichiers_dir = self.output_dir / "fichiers"
        (self.assets_dir / "css").mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "js").mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "fonts").mkdir(parents=True, exist_ok=True)
        self.fichiers_dir.mkdir(parents=True, exist_ok=True)

        # Tracking
        self.visited_repos = set()
        self.repo_mapping = {}  # repo_id -> {fichier, nom_complet, url, texte_clique}
        self.file_mapping = {}  # file_id -> {fichier_reel, titre, repo}
        self.downloaded_files_count = 0
        self.failed_files = []
        self.repos_explored = 0
        self.subpages_count = 0

        # Setup Selenium
        self.setup_driver()

    def setup_driver(self):
        """Configure Firefox avec Selenium"""
        options = Options()

        # Configuration du téléchargement automatique
        options.set_preference("browser.download.folderList", 2)  # 2 = dossier personnalisé
        options.set_preference("browser.download.dir", str(DOWNLOAD_DIR))
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.download.manager.showWhenStarting", False)
        options.set_preference("browser.download.manager.closeWhenDone", True)
        options.set_preference("browser.download.manager.focusWhenStarting", False)
        options.set_preference("browser.download.manager.useWindow", False)
        options.set_preference("browser.download.manager.showAlertOnComplete", False)

        # Liste de tous les types MIME à télécharger sans demander
        mime_types = [
            "application/pdf",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
            "application/x-zip-compressed",
            "application/octet-stream",
            "text/plain",
            "text/csv",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "image/jpeg",
            "image/png",
            "image/gif"
        ]
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", ",".join(mime_types))

        # Désactiver la prévisualisation PDF intégrée
        options.set_preference("pdfjs.disabled", True)

        # Désactiver les popups de téléchargement
        options.set_preference("browser.helperApps.alwaysAsk.force", False)
        options.set_preference("browser.download.panel.shown", False)

        self.driver = webdriver.Firefox(options=options)
        self.wait = WebDriverWait(self.driver, 10)

    def login(self):
        """Connexion au site"""
        self.logger.log(f"Email de connexion : {self.email}")

        try:
            # Charger la page d'accueil
            self.driver.set_page_load_timeout(30)
            self.driver.get(self.base_url)
            self.driver.set_page_load_timeout(10)

            # Cliquer sur le bouton de connexion
            wait = WebDriverWait(self.driver, 15)
            connexion_button = wait.until(
                EC.element_to_be_clickable((By.CLASS_NAME, "icon-connexion"))
            )
            connexion_button.click()
            time.sleep(2)

            # Trouver les champs (avec plusieurs tentatives)
            email_field = None
            password_field = None

            # Chercher le champ identifiant
            try:
                email_field = self.driver.find_element(By.NAME, "identifiant")
            except:
                try:
                    email_field = self.driver.find_element(By.ID, "identifiant")
                except:
                    email_field = self.driver.find_element(By.CSS_SELECTOR, "input[type='text']")

            # Chercher le champ mot de passe
            try:
                password_field = self.driver.find_element(By.NAME, "motdepasse")
            except:
                try:
                    password_field = self.driver.find_element(By.ID, "motdepasse")
                except:
                    password_field = self.driver.find_element(By.CSS_SELECTOR, "input[type='password']")

            # Remplir les champs
            email_field.clear()
            time.sleep(0.5)
            email_field.send_keys(self.email)
            time.sleep(0.5)

            password_field.clear()
            time.sleep(0.5)
            password_field.send_keys(self.password)
            time.sleep(0.5)

            # Soumettre le formulaire
            password_field.submit()
            time.sleep(5)

            # Vérifier que la connexion a réussi en cherchant l'icône de déconnexion
            try:
                wait = WebDriverWait(self.driver, 10)
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "icon-deconnexion")))
                self.logger.log("Connexion réussie ✓")
                return True
            except TimeoutException:
                self.logger.log("❌ Échec de connexion : l'icône de déconnexion n'apparaît pas")
                self.logger.log("   Vérifiez vos identifiants ou lancez le script manuellement")
                return False

        except Exception as e:
            self.logger.log(f"Erreur de connexion : {e}")
            import traceback
            self.logger.log(traceback.format_exc())
            return False

    def save_page(self, repo_id=None, link_text="", url=""):
        """Sauvegarde une page HTML"""
        if repo_id and repo_id in self.visited_repos:
            return None

        if repo_id:
            self.visited_repos.add(repo_id)
            filename = f"docs_rep_{repo_id}.html"
        else:
            filename = "docs.html" if "docs" in url else "index.html"

        filepath = self.output_dir / filename

        try:
            # Attendre que la page soit complètement chargée
            # On attend soit l'icône de déconnexion (si connecté) soit le contenu principal
            wait = WebDriverWait(self.driver, 10)
            try:
                # Attendre l'un de ces éléments
                wait.until(lambda driver:
                    driver.find_elements(By.CLASS_NAME, "icon-deconnexion") or
                    driver.find_elements(By.TAG_NAME, "section")
                )
            except TimeoutException:
                pass  # Continuer même si timeout

            time.sleep(2)  # Attendre encore 2 secondes pour être sûr

            html_content = self.driver.page_source

            # Vérifier que la page ne contient pas le formulaire de connexion
            if 'icon-connexion' in html_content and 'icon-deconnexion' not in html_content:
                self.logger.log(f"  ⚠️  Page non connectée détectée pour {filename} - abandon")
                return None

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)

            if repo_id:
                self.logger.log(f"  → Texte cliqué: \"{link_text}\"")
                self.logger.log(f"  → Page sauvegardée: {filename}")

                # Enregistrer le mapping
                self.repo_mapping[repo_id] = {
                    "fichier": filename,
                    "nom_complet": link_text,
                    "url_originale": f"docs?rep={repo_id}",
                    "texte_clique": link_text
                }
            else:
                self.logger.log(f"  → Page sauvegardée: {filename}")

            return filepath

        except Exception as e:
            self.logger.log(f"  ⚠️  Erreur sauvegarde page: {e}")
            return None

    def download_file(self, file_id, title, repo_name=""):
        """Télécharge un fichier"""
        # Vérifier la limite en mode test
        if self.test_mode and self.downloaded_files_count >= TEST_MAX_FILES:
            self.logger.log(f"  ⚠️  LIMITE TEST atteinte ({TEST_MAX_FILES} fichiers) - Fichier ignoré: {file_id}")
            return False

        download_url = f"{self.base_url}download?id={file_id}"

        try:
            # Nettoyer le titre pour en faire un nom de fichier valide
            safe_title = re.sub(r'[^\w\s\-\.]', '', title)
            safe_title = re.sub(r'\s+', ' ', safe_title).strip()

            # Limiter la longueur (max 200 caractères)
            if len(safe_title) > 200:
                safe_title = safe_title[:197] + "..."

            self.logger.log(f"  → Fichier trouvé: {file_id} - \"{title}\"")

            # Noter les fichiers existants AVANT le téléchargement
            import glob
            before_files = set(glob.glob(str(DOWNLOAD_DIR / "*")))
            before_time = time.time()

            # Lancer le téléchargement avec Selenium
            # Note: le get() va timeout car c'est un téléchargement, pas une page web
            # C'est normal et attendu - on capture l'exception
            try:
                self.driver.set_page_load_timeout(5)  # Court timeout
                self.driver.get(download_url)
            except TimeoutException:
                pass  # Normal pour un téléchargement de fichier
            finally:
                self.driver.set_page_load_timeout(10)  # Restaurer le timeout normal

            time.sleep(3)  # Attendre que le téléchargement démarre

            # Chercher les NOUVEAUX fichiers téléchargés
            max_wait = 30
            latest_file = None

            for _ in range(max_wait):
                after_files = set(glob.glob(str(DOWNLOAD_DIR / "*")))
                new_files = after_files - before_files

                if new_files:
                    # Prendre le fichier le plus récent parmi les nouveaux
                    new_files_list = list(new_files)
                    new_files_list.sort(key=os.path.getmtime, reverse=True)
                    latest_file = Path(new_files_list[0])

                    # Vérifier que le fichier a été modifié après le début du téléchargement
                    if os.path.getmtime(latest_file) >= before_time:
                        break

                time.sleep(1)

            if not latest_file:
                raise Exception("Aucun nouveau fichier téléchargé trouvé")

            # Attendre que le téléchargement se termine (pas de .part)
            wait_count = 0
            while latest_file.suffix == '.part' and wait_count < 30:
                time.sleep(1)
                wait_count += 1

            if latest_file.suffix == '.part':
                raise Exception("Téléchargement incomplet")

            # Déterminer l'extension depuis le fichier téléchargé
            file_ext = latest_file.suffix
            if not file_ext:
                file_ext = ""

            # Ajouter l'extension si nécessaire
            if not safe_title.endswith(file_ext) and file_ext:
                safe_title += file_ext

            # Déplacer le fichier vers le dossier final
            file_path = self.fichiers_dir / safe_title
            shutil.move(str(latest_file), str(file_path))

            file_size = file_path.stat().st_size

            # Convertir la taille en Ko/Mo
            if file_size < 1024:
                size_str = f"{file_size} octets"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size // 1024} Ko"
            else:
                size_str = f"{file_size // (1024 * 1024)} Mo"

            self.logger.log(f"  → Téléchargement: {safe_title} ({size_str}) [OK]")

            # Créer le lien symbolique
            link_path = self.fichiers_dir / file_id
            if link_path.exists():
                link_path.unlink()
            link_path.symlink_to(safe_title)

            self.logger.log(f"  → Lien symbolique: fichiers/{file_id} -> {safe_title}")

            # Enregistrer le mapping
            self.file_mapping[file_id] = {
                "fichier_reel": safe_title,
                "lien_symbolique": file_id,
                "titre": title,
                "repository": repo_name,
                "taille": size_str
            }

            self.downloaded_files_count += 1
            time.sleep(WAIT_TIME)
            return True

        except Exception as e:
            self.logger.log(f"  ⚠️  Échec téléchargement {file_id}: {e}")
            self.failed_files.append({"id": file_id, "titre": title, "erreur": str(e)})
            return False

    def explore_repository(self, repo_id, link_text):
        """Explore un répertoire et télécharge son contenu"""
        # Vérifier la limite de sous-pages en mode test
        if self.test_mode and self.subpages_count >= TEST_MAX_SUBPAGES:
            self.logger.log(f"  ⚠️  LIMITE TEST atteinte ({TEST_MAX_SUBPAGES} sous-pages) - Repo ignoré: {repo_id}")
            return

        self.subpages_count += 1
        self.logger.log(f"Exploration du repo {repo_id} [{self.subpages_count}/{TEST_MAX_SUBPAGES if self.test_mode else '∞'}]")

        url = f"{self.base_url}docs?rep={repo_id}"
        self.driver.get(url)

        # Attendre que la page soit complètement chargée
        try:
            # Attendre qu'un élément caractéristique soit présent (signe que c'est bien chargé)
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "section"))
            )
            time.sleep(2)  # Temps supplémentaire pour le rendu complet
        except:
            self.logger.log(f"  ⚠️  Timeout chargement page {repo_id}")
            time.sleep(1)

        # Sauvegarder la page
        self.save_page(repo_id, link_text, url)

        # Trouver tous les sous-répertoires
        try:
            sub_repos = self.driver.find_elements(By.CSS_SELECTOR, "p.rep a")
            sub_repo_list = []
            for repo_link in sub_repos:
                href = repo_link.get_attribute('href')
                if 'rep=' in href:
                    sub_id = href.split('rep=')[-1].split('&')[0]
                    text = repo_link.text.strip()
                    sub_repo_list.append((sub_id, text))
        except:
            sub_repo_list = []

        # Trouver tous les fichiers
        try:
            files = self.driver.find_elements(By.CSS_SELECTOR, "p.doc a")
            for file_link in files:
                href = file_link.get_attribute('href')
                if 'download?id=' in href:
                    file_id = href.split('id=')[-1].split('&')[0]
                    title = file_link.text.strip()
                    self.download_file(file_id, title, link_text)
        except:
            pass

        # Explorer les sous-répertoires récursivement
        for sub_id, sub_text in sub_repo_list:
            if sub_id not in self.visited_repos:
                self.explore_repository(sub_id, sub_text)

    def download_all(self):
        """Télécharge tout le site"""
        self.logger.section("DÉBUT DU TÉLÉCHARGEMENT")

        if not self.login():
            return False

        # Aller sur la page docs
        self.driver.get(f"{self.base_url}docs")
        time.sleep(1)

        # Sauvegarder la page d'accueil et docs
        self.driver.get(self.base_url)
        time.sleep(1)
        self.save_page(url=self.base_url)

        self.driver.get(f"{self.base_url}docs")
        time.sleep(1)
        self.save_page(url=f"{self.base_url}docs")

        # Trouver tous les répertoires principaux
        main_repos = []
        try:
            menu = self.driver.find_element(By.ID, "menu")
            repo_links = menu.find_elements(By.CSS_SELECTOR, "a.menurep")

            for link in repo_links:
                href = link.get_attribute('href')
                if 'rep=' in href:
                    repo_id = href.split('rep=')[-1].split('&')[0]
                    text = link.text.strip()
                    main_repos.append((repo_id, text))
        except Exception as e:
            self.logger.log(f"Erreur extraction menu: {e}")

        self.logger.log(f"\n{len(main_repos)} répertoires principaux trouvés\n")

        # Explorer chaque répertoire
        for repo_id, text in main_repos:
            # Limite en mode test
            if self.test_mode and self.repos_explored >= TEST_MAX_REPOS:
                self.logger.log(f"\n⚠️  LIMITE TEST atteinte ({TEST_MAX_REPOS} répertoire principal)")
                self.logger.log(f"Repos ignorés: {len(main_repos) - self.repos_explored}")
                break

            if repo_id not in self.visited_repos:
                self.logger.log(f"\n{'='*60}")
                self.logger.log(f"RÉPERTOIRE PRINCIPAL {self.repos_explored + 1}/{TEST_MAX_REPOS if self.test_mode else len(main_repos)}: {text}")
                self.logger.log(f"{'='*60}\n")
                self.explore_repository(repo_id, text)
                self.repos_explored += 1

        self.driver.quit()
        return True

    def download_assets(self):
        """Télécharge les CSS, JS et fonts"""
        self.logger.section("TÉLÉCHARGEMENT DES ASSETS")

        assets = [
            ("css", "style.min.css", f"{self.base_url}css/style.min.css?v=1202"),
            ("css", "icones.min.css", f"{self.base_url}css/icones.min.css?v=1200"),
            ("js", "jquery.min.js", f"{self.base_url}js/jquery.min.js"),
            ("js", "commun.min.js", f"{self.base_url}js/commun.min.js?v=1200"),
            ("fonts", "icomoon.woff", f"{self.base_url}fonts/icomoon.woff?1210"),
        ]

        for asset_type, filename, url in assets:
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()

                filepath = self.assets_dir / asset_type / filename
                with open(filepath, 'wb') as f:
                    f.write(response.content)

                size = len(response.content)
                size_str = f"{size // 1024} Ko" if size >= 1024 else f"{size} octets"
                self.logger.log(f"  → {asset_type.upper()}: {filename} ({size_str}) [OK]")

            except Exception as e:
                self.logger.log(f"  ⚠️  Erreur {filename}: {e}")

    def fix_html_links(self):
        """Corrige tous les liens dans tous les fichiers HTML"""
        self.logger.section("CORRECTION DES LIENS HTML")

        html_files = list(self.output_dir.glob("*.html"))
        total_links = 0
        total_assets = 0

        for html_file in html_files:
            try:
                with open(html_file, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'html.parser')

                links_fixed = 0
                assets_fixed = 0
                details = []

                # Corriger les liens CSS
                for link in soup.find_all('link', rel='stylesheet'):
                    if link.get('href'):
                        old_href = link['href']
                        # Transformer css/style.min.css → assets/css/style.min.css
                        if old_href.startswith('css/'):
                            link['href'] = 'assets/' + old_href
                            assets_fixed += 1

                # Corriger les scripts JS
                for script in soup.find_all('script', src=True):
                    old_src = script['src']
                    # Transformer js/jquery.min.js → assets/js/jquery.min.js
                    if old_src.startswith('js/'):
                        script['src'] = 'assets/' + old_src
                        assets_fixed += 1

                # Corriger les liens <a>
                for a in soup.find_all('a', href=True):
                    old_href = a['href']
                    new_href = self.fix_link(old_href, a.get_text(strip=True))

                    if new_href != old_href:
                        a['href'] = new_href
                        links_fixed += 1

                        # Garder quelques exemples pour les logs
                        if links_fixed <= 3:
                            link_text = a.get_text(strip=True)[:50]
                            details.append(f"    • {old_href} → {new_href} (\"{link_text}\")")

                if links_fixed > 0 or assets_fixed > 0:
                    with open(html_file, 'w', encoding='utf-8') as f:
                        f.write(str(soup))

                    if assets_fixed > 0:
                        self.logger.log(f"  → {html_file.name}: {assets_fixed} assets + {links_fixed} liens corrigés")
                    else:
                        self.logger.log(f"  → {html_file.name}: {links_fixed} liens corrigés")

                    for detail in details:
                        self.logger.log(detail)
                    if links_fixed > 3:
                        self.logger.log(f"    ... et {links_fixed - 3} autres")

                    total_links += links_fixed
                    total_assets += assets_fixed

            except Exception as e:
                self.logger.log(f"  ⚠️  Erreur {html_file.name}: {e}")

        self.logger.log(f"\nTotal: {total_assets} assets + {total_links} liens corrigés dans {len(html_files)} fichiers")

    def fix_link(self, href, link_text=""):
        """Corrige un lien href"""
        if not href or href.startswith('#') or href.startswith('javascript:'):
            return href

        # Fichiers déjà corrigés
        if href.startswith('assets/') or href.startswith('fichiers/'):
            return href

        # Liens de téléchargement
        if 'download?id=' in href:
            file_id = href.split('id=')[-1].split('&')[0]
            return f"fichiers/{file_id}"

        # Liens vers repos avec docs?rep=
        if 'docs?rep=' in href:
            repo_id = href.split('rep=')[-1].split('&')[0]
            return f"docs_rep_{repo_id}.html"

        # Liens vers repos avec ?rep= (relatif)
        if href.startswith('?rep='):
            repo_id = href.split('rep=')[-1].split('&')[0]
            return f"docs_rep_{repo_id}.html"

        # Liens vers pages spéciales
        if href in ['.', './', 'index', 'index.html']:
            return 'index.html'
        if href in ['docs', 'docs.html']:
            return 'docs.html'

        # Autres liens (agenda, mail, etc.) - pas disponibles hors ligne
        if href in ['recent', 'agenda', 'mail', 'notescolles', 'prefs', 'blogcdp']:
            return '#'
        if href.startswith('notescolles?') or href.startswith('.?'):
            return '#'

        return href

    def save_mappings(self):
        """Sauvegarde les fichiers de mapping"""
        self.logger.section("SAUVEGARDE DES MAPPINGS")

        # Mapping des pages
        mapping_pages_file = self.output_dir / "mapping_pages.json"
        with open(mapping_pages_file, 'w', encoding='utf-8') as f:
            json.dump(self.repo_mapping, f, indent=2, ensure_ascii=False)
        self.logger.log(f"  → mapping_pages.json: {len(self.repo_mapping)} entrées")

        # Mapping des fichiers
        mapping_fichiers_file = self.output_dir / "mapping_fichiers.json"
        with open(mapping_fichiers_file, 'w', encoding='utf-8') as f:
            json.dump(self.file_mapping, f, indent=2, ensure_ascii=False)
        self.logger.log(f"  → mapping_fichiers.json: {len(self.file_mapping)} entrées")

    def print_summary(self):
        """Affiche le résumé final"""
        self.logger.section("RÉSUMÉ")

        duration = datetime.now() - self.logger.start_time
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)

        html_count = len(list(self.output_dir.glob("*.html")))

        self.logger.log(f"Pages HTML téléchargées: {html_count}")
        self.logger.log(f"Fichiers téléchargés: {self.downloaded_files_count}")
        self.logger.log(f"Fichiers échoués: {len(self.failed_files)}")
        self.logger.log(f"Durée totale: {minutes}m {seconds:02d}s")

        if self.failed_files:
            self.logger.log("\nFichiers échoués:")
            for failed in self.failed_files[:10]:
                self.logger.log(f"  • {failed['id']}: {failed['titre']}")
            if len(self.failed_files) > 10:
                self.logger.log(f"  ... et {len(self.failed_files) - 10} autres")

        self.logger.log("\n" + "=" * 60)
        self.logger.log(f"✅ SITE PRÊT : {self.output_dir}")
        self.logger.log(f"🌐 Ouvrir : firefox {self.output_dir}/index.html")
        self.logger.log("=" * 60)

def main():
    # Vérifier le mode test
    global TEST_MODE
    test_mode = '--test' in sys.argv

    if test_mode:
        TEST_MODE = True
        print("=" * 70)
        print("  🧪 MODE TEST - TÉLÉCHARGEMENT LIMITÉ")
        print("=" * 70)
        print(f"  • Maximum {TEST_MAX_REPOS} répertoire principal")
        print(f"  • Maximum {TEST_MAX_SUBPAGES} sous-pages")
        print(f"  • Maximum {TEST_MAX_FILES} fichiers")
        print("=" * 70)
    else:
        print("=" * 70)
        print("  📚 TÉLÉCHARGEMENT COMPLET DU SITE CAHIER-DE-PREPA.FR")
        print("=" * 70)
        print()
        print("⚠️  MODE COMPLET - Cela peut prendre 30-60 minutes")
        print("💡 Pour tester d'abord, lancez avec: --test")

    print()

    # Demander l'URL du site
    print("🌐 URL du site à télécharger")
    print("   Vous pouvez saisir :")
    print("   - L'URL complète : https://cahier-de-prepa.fr/ma-classe/")
    print("   - Avec domaine : cahier-de-prepa.fr/ma-classe/")
    print("   - Juste le nom : ma-classe")
    print()
    site_input = input("🔗 URL ou nom du site : ").strip()
    base_url = normalize_url(site_input)
    print(f"   ✓ URL normalisée : {base_url}")
    print()

    # Demander les identifiants
    email = input("📧 Email de connexion : ").strip()
    password = getpass.getpass("🔑 Mot de passe : ")

    print()

    # Choisir le dossier de destination
    output_dir = OUTPUT_DIR_TEST if test_mode else OUTPUT_DIR

    # Initialiser le logger
    log_file = output_dir / "telecharger.log"
    output_dir.mkdir(exist_ok=True)

    # Effacer le log précédent
    if log_file.exists():
        log_file.unlink()

    logger = Logger(log_file)

    if test_mode:
        logger.log("🧪 MODE TEST ACTIVÉ")
        logger.log(f"Dossier de sortie: {output_dir}")
        logger.log(f"Limites: {TEST_MAX_REPOS} repo | {TEST_MAX_SUBPAGES} pages | {TEST_MAX_FILES} fichiers")

    # Créer le downloader
    downloader = SiteDownloader(email, password, base_url, output_dir, logger, test_mode=test_mode)

    try:
        # 1. Télécharger tout le contenu
        if not downloader.download_all():
            logger.log("❌ Échec du téléchargement")
            return

        # 2. Télécharger les assets
        downloader.download_assets()

        # 3. Corriger les liens
        downloader.fix_html_links()

        # 4. Sauvegarder les mappings
        downloader.save_mappings()

        # 5. Résumé
        downloader.print_summary()

    except KeyboardInterrupt:
        logger.log("\n\n⚠️  Interruption par l'utilisateur (Ctrl+C)")
        logger.log("Le téléchargement partiel est disponible dans:")
        logger.log(f"  {OUTPUT_DIR}")
    except Exception as e:
        logger.log(f"\n\n❌ Erreur fatale: {e}")
        import traceback
        logger.log(traceback.format_exc())

if __name__ == "__main__":
    main()
