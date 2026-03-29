# Téléchargeur Cahier de Prépa

Script Python automatisé pour télécharger l'intégralité d'un site Cahier de Prépa et créer un miroir hors ligne entièrement fonctionnel.

## Fonctionnalités

- Connexion automatique au site avec vos identifiants
- Téléchargement récursif de toutes les pages HTML
- Téléchargement de tous les fichiers (PDF, documents, etc.)
- Téléchargement des assets (CSS, JavaScript, fonts)
- Correction automatique de tous les liens pour navigation hors ligne
- Création de liens symboliques pour les fichiers
- Génération de fichiers de mapping JSON
- Logs détaillés avec progression
- Mode test pour valider avant téléchargement complet

## Prérequis

### Logiciels nécessaires

```bash
# Python 3.x
python3 --version

# Firefox (utilisé par Selenium)
firefox --version

# Geckodriver (driver Selenium pour Firefox)
# Installation sur Fedora/RHEL :
sudo dnf install geckodriver

# Installation sur Ubuntu/Debian :
sudo apt install firefox-geckodriver
```

### Dépendances Python

```bash
pip install selenium beautifulsoup4 requests
```

Ou avec un fichier requirements.txt :

```bash
pip install -r requirements.txt
```

**Contenu de requirements.txt :**
```
selenium>=4.0.0
beautifulsoup4>=4.9.0
requests>=2.25.0
```

## Configuration

### Système en français (locale fr_FR)

Le script est configuré pour un système avec locale française et utilise le dossier `~/Téléchargements`.

Si votre système utilise `~/Downloads`, modifiez la ligne 31 du script :

```python
DOWNLOAD_DIR = Path.home() / "Downloads"  # Au lieu de "Téléchargements"
```

## Utilisation

### Mode Test (Recommandé pour la première fois)

Le mode test limite le téléchargement à :
- 1 répertoire principal
- 10 sous-pages maximum
- 10 fichiers maximum

```bash
cd ~/cahier-prepa-downloader
python3 telecharger_site_complet.py --test
```

Le résultat sera dans `~/cahier_prepa_test/`

### Mode Complet

```bash
cd ~/cahier-prepa-downloader
python3 telecharger_site_complet.py
```

### Saisie de l'URL

Le script vous demandera l'URL du site à télécharger. Vous pouvez la saisir sous différents formats :

**Format 1 - URL complète :**
```
https://cahier-de-prepa.fr/ma-classe/
```

**Format 2 - Avec domaine :**
```
cahier-de-prepa.fr/ma-classe/
```

**Format 3 - Juste le nom de la classe :**
```
ma-classe
```

Toutes ces formes seront automatiquement normalisées en `https://cahier-de-prepa.fr/ma-classe/`

### Identifiants

Ensuite, le script vous demandera :
1. Votre email de connexion
2. Votre mot de passe (saisi de manière sécurisée)

Le résultat sera dans `~/cahier_prepa_offline/`

**Durée estimée** : 30 minutes à 3 heures selon la taille du site

## Structure des fichiers générés

```
~/cahier_prepa_offline/
├── index.html                    # Page d'accueil
├── docs.html                     # Page documents
├── docs_rep_XXX.html            # Pages des répertoires
├── telecharger.log              # Journal détaillé
├── mapping_pages.json           # Mapping repo_id → fichier HTML
├── mapping_fichiers.json        # Mapping file_id → fichier réel
├── assets/
│   ├── css/
│   │   ├── style.min.css
│   │   └── icones.min.css
│   ├── js/
│   │   ├── jquery.min.js
│   │   └── commun.min.js
│   └── fonts/
│       └── icomoon.woff
└── fichiers/
    ├── 719 → Capitalisme et liberté.pdf  # Liens symboliques
    ├── Capitalisme et liberté.pdf        # Fichier réel
    └── ...
```

## Fichiers de mapping

### mapping_pages.json

Associe chaque ID de répertoire à sa page HTML :

```json
{
  "213": {
    "fichier": "docs_rep_213.html",
    "nom_complet": "Fiches de lecture",
    "url_originale": "docs?rep=213",
    "texte_clique": "Fiches de lecture"
  }
}
```

### mapping_fichiers.json

Associe chaque ID de fichier à son nom réel :

```json
{
  "719": {
    "fichier_reel": "Capitalisme et liberté Milton Friedman.pdf",
    "lien_symbolique": "719",
    "titre": "Capitalisme et liberté, Milton Friedman",
    "repo": "Fiches de lecture"
  }
}
```

## Navigation hors ligne

Une fois le téléchargement terminé, ouvrez le site dans votre navigateur :

```bash
firefox ~/cahier_prepa_offline/index.html
```

Tous les liens fonctionnent comme sur le site original :
- Navigation entre les dossiers
- Téléchargement des fichiers
- CSS et icônes chargés correctement

## Logs et débogage

Le fichier `telecharger.log` contient un journal détaillé :

```
[2026-02-12 16:53:28] Connexion réussie ✓
[2026-02-12 16:53:32]   → Page sauvegardée: index.html
[2026-02-12 16:53:37]   → Texte cliqué: "Fiches de lecture"
[2026-02-12 16:53:37]   → Page sauvegardée: docs_rep_213.html
[2026-02-12 16:53:37]   → Fichier trouvé: 719 - "Capitalisme et liberté"
[2026-02-12 16:53:41]   → Téléchargement: Capitalisme et liberté.pdf (450 Ko) [OK]
```

## Résumé final

À la fin de l'exécution, le script affiche :

```
============================================================
  RÉSUMÉ
============================================================
Pages HTML téléchargées: 45
Fichiers téléchargés: 123
Fichiers échoués: 2
Durée totale: 45m 12s

Fichiers échoués:
  • 719: Capitalisme et liberté, Milton Friedman
  • 1195: Article économie

============================================================
✅ SITE PRÊT : /home/bsrd_t/cahier_prepa_offline
🌐 Ouvrir : firefox /home/bsrd_t/cahier_prepa_offline/index.html
============================================================
```

## Limitations et risques

### Session expirée
Si le téléchargement prend plus d'une heure, la session peut expirer. Le script ne gère pas la reconnexion automatique.

### Pas de reprise
Si le script est interrompu (Ctrl+C, panne réseau, etc.), il faut recommencer depuis le début.

### Dossier Téléchargements
Assurez-vous que `~/Téléchargements` est vide ou ne contient pas de fichiers en cours de téléchargement pendant l'exécution.

### Espace disque
Vérifiez l'espace disponible avant de lancer :
```bash
df -h ~
```

## Dépannage

### Erreur "geckodriver not found"
```bash
# Fedora/RHEL
sudo dnf install geckodriver

# Ubuntu/Debian
sudo apt install firefox-geckodriver

# Ou téléchargement manuel
# https://github.com/mozilla/geckodriver/releases
```

### Erreur "Navigation timed out"
C'est normal pour les téléchargements de fichiers - l'exception est capturée automatiquement.

### Pages non connectées détectées
Vérifiez vos identifiants ou relancez le script.

### Aucun fichier téléchargé trouvé
- Vérifiez que le dossier `~/Téléchargements` existe
- Vérifiez que Firefox a les permissions d'écriture
- Videz `~/Téléchargements` avant de relancer

## Licence

Script créé pour un usage éducatif personnel. Respectez les conditions d'utilisation du site Cahier de Prépa et les droits d'auteur des contenus téléchargés.

## Auteur

Script développé avec l'assistance de Claude Code (Anthropic).

## Changelog

### Version 1.0 (2026-02-12)
- Version initiale fonctionnelle
- Mode test intégré
- Téléchargement automatique complet
- Correction des liens pour navigation hors ligne
- Génération de mappings JSON
- Logs détaillés
