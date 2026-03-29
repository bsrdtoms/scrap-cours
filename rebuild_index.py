#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recrée index.html et répare les liens internes à partir du mapping.json.
À utiliser si les liens sont cassés sans avoir à re-scraper.
"""
import json, os
from pathlib import Path
from bs4 import BeautifulSoup

offline  = Path(__file__).parent / "moodle_offline"
base_url = "https://foad-moodle.ensai.fr"

# --- Charger le mapping ---
mapping   = json.loads((offline / "mapping.json").read_text(encoding="utf-8"))
# url_moodle → chemin local absolu
url_to_local = {k: Path(v) for k, v in mapping.items()}

# --- Réparer les liens dans les pages de COURS ---
# (index.html de chaque cours + pages/)
course_html = [f for f in offline.rglob("*.html") if f.name != "index.html" or f.parent != offline]
print(f"Réparation des liens dans {len(course_html)} pages de cours...")

for html_path in course_html:
    content = html_path.read_text(encoding="utf-8", errors="ignore")
    soup    = BeautifulSoup(content, "html.parser")
    changed = False
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        # Lien vers un fichier local (PDF, DOCX…) → déjà correct
        if not href.startswith("http") and not href.startswith("/") and href != "#":
            continue
        # Chercher dans le mapping
        abs_href = href if href.startswith("http") else base_url + href
        if abs_href in url_to_local:
            local = url_to_local[abs_href]
            rel   = os.path.relpath(str(local), str(html_path.parent)).replace("\\", "/")
            tag["href"] = rel
            for attr in ("title", "style"):
                tag.attrs.pop(attr, None)
            changed = True
    if changed:
        html_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")

print("Liens de cours réparés.")

# --- Reconstruire index.html proprement ---
print("Reconstruction de index.html...")

# Récupérer la liste des cours depuis les dossiers
cours_dir = offline / "cours"
courses = []
for d in sorted(cours_dir.iterdir()):
    if d.is_dir() and (d / "index.html").exists():
        # Retrouver le vrai nom depuis le mapping
        local_idx = d / "index.html"
        nom = d.name.replace("_", " ")
        # Essayer de lire le titre depuis le HTML sauvegardé
        try:
            s = BeautifulSoup((local_idx).read_text(encoding="utf-8", errors="ignore"), "html.parser")
            t = s.find("title")
            if t:
                nom = t.get_text().split("|")[0].split(":")[1].strip() if ":" in t.get_text() else t.get_text().split("|")[0].strip()
        except Exception:
            pass
        courses.append({"name": nom, "local": f"cours/{d.name}/index.html"})

# CSS minimal + liste des cours
css_links = ""
for f in (offline / "assets" / "theme").glob("styles.php*"):
    rel = f"assets/theme/{f.name}"
    css_links += f'<link rel="stylesheet" href="{rel}">\n'

items_html = ""
for c in courses:
    items_html += f'<li><a href="{c["local"]}">{c["name"]}</a></li>\n'

html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mes cours — ENSAI Moodle (offline)</title>
{css_links}
<style>
  body {{ font-family: Arial, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; background: #f8f9fa; }}
  h1 {{ color: #003d7a; border-bottom: 3px solid #003d7a; padding-bottom: 10px; }}
  .subtitle {{ color: #666; margin-bottom: 30px; font-size: 0.9em; }}
  ul {{ list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap: 12px; }}
  li a {{
    display: block; padding: 14px 16px; background: white; border-radius: 8px;
    border: 1px solid #dee2e6; color: #003d7a; text-decoration: none;
    font-weight: 500; transition: box-shadow .15s;
  }}
  li a:hover {{ box-shadow: 0 4px 12px rgba(0,61,122,.15); border-color: #003d7a; }}
</style>
</head>
<body>
<h1>Mes cours — ENSAI Moodle</h1>
<p class="subtitle">Copie locale du {base_url.replace('https://','')} — {len(courses)} cours disponibles hors ligne</p>
<ul>
{items_html}
</ul>
</body>
</html>"""

(offline / "index.html").write_text(html, encoding="utf-8")
print(f"index.html recréé avec {len(courses)} cours.")
print(f"Ouvrir : {offline / 'index.html'}")
