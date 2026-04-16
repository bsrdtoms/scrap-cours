# scrap-cours — Moodle Offline Scraper

Crée un miroir local entièrement navigable d'un Moodle (HTML + CSS + JS + fichiers).
Fonctionne avec n'importe quelle instance Moodle : CAS, formulaire standard, ou SSO.

---

## Fichiers principaux

| Fichier | Description |
|---|---|
| `moodle_scraper.py` | Scraper universel — classe `MoodleScraper` |
| `run_moodle_scraper.py` | Lanceur pour Moodle DOMENSAI (cookie + patches) |
| `scrape_my_courses.py` | Scrape `/my/courses` et met à jour les liens de navigation |
| `fix_links_offline.py` | Post-traitement : corrige les liens cassés dans le miroir |
| `inject_nav_fix.py` | Injecte un fix JS de navigation dans tous les HTML |
| `rebuild_index.py` | Regénère `index.html` depuis `mapping.json` |

---

## Installation

```bash
git clone https://github.com/bsrdtoms/scrap-cours.git
cd scrap-cours
pip install -r requirements.txt
```

---

## Usage général (`moodle_scraper.py`)

```bash
# Interactif — demande l'URL et les identifiants
python3 moodle_scraper.py

# URL en argument
python3 moodle_scraper.py --url https://moodle.monecole.fr

# Mode test (2 cours, rapide)
python3 moodle_scraper.py --test
```

Le miroir est généré dans `moodle_offline_<domaine>/`.
Ouvrir `index.html` dans un navigateur (ou servir avec `python3 -m http.server`).

### Authentification supportée

| Type | Comportement |
|---|---|
| CAS (ex. ENSAI, ENSAI) | Login automatique username/password |
| Formulaire Moodle standard | Login automatique username/password |
| SSO / OAuth / Shibboleth | Fenêtre Chrome ouverte pour login manuel |

---

## Usage DOMENSAI (`run_moodle_scraper.py`)

Lanceur spécifique pour `http://moodle-2024.domensai.ecole` avec injection directe du cookie de session (bypass login).

```bash
python3 run_moodle_scraper.py

# Limiter le nombre de cours (test)
python3 run_moodle_scraper.py --courses 3

# Mode test complet
python3 run_moodle_scraper.py --test
```

Avant de lancer, mettre à jour le cookie dans le fichier :
```python
COOKIE_VALUE = "votre_cookie_MoodleSession"
```

Le cookie s'obtient depuis les DevTools du navigateur (F12 → Application → Cookies) une fois connecté sur Moodle.

### Corrections incluses dans `run_moodle_scraper.py`

- **Bug `build_index`** : double-réécriture des liens corrigée (les liens de cours ne tombaient plus sur `#`)
- **Sections d'onglets** : les cours multi-sections (`?section=N`) sont maintenant scrapés comme des pages séparées (`section_1.html`, `section_2.html`...)
- **Extensions CSS** : les fichiers CSS servis par Moodle sans extension (ex. `styles.php/.../all`) sont renommés en `.css` pour que le navigateur les applique correctement

### Structure générée

```
moodle-domensai-offline/
├── index.html
├── mapping.json
├── assets/
└── cours/
    └── Nom_du_cours/
        ├── index.html
        ├── section_1.html
        ├── section_2.html
        ├── fichiers/
        │   └── TD1.pdf
        └── pages/
```

---

## Navigation hors ligne

Les liens cliquables utilisent un fix JS injecté dans chaque page pour contourner l'interception des clics par Moodle (Bootstrap drawer).
Servir le miroir avec un serveur HTTP local :

```bash
cd moodle-domensai-offline
python3 -m http.server 8766
# Ouvrir http://localhost:8766
```

---

## Dépendances

```
requests >= 2.28
beautifulsoup4 >= 4.11
lxml >= 4.9
```
