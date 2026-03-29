#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_nav_onclick.py
------------------
Ajoute un attribut onclick direct sur chaque lien de navigation Moodle
([data-key] > a[href!="#"]) pour forcer la navigation malgre les
handlers JS de Moodle qui bloquent le comportement par defaut.

L'onclick inline s'execute en PREMIER et stoppe la propagation.
"""
from pathlib import Path
from bs4 import BeautifulSoup

OFFLINE = Path(__file__).parent / "moodle_offline"

ONCLICK = "event.stopImmediatePropagation();event.preventDefault();window.location.href=this.getAttribute('href');return false;"

html_files = list(OFFLINE.rglob("*.html"))
print(f"Fichiers HTML : {len(html_files)}")

patched_files = 0
patched_links = 0

for html_path in html_files:
    content = html_path.read_text(encoding="utf-8", errors="ignore")
    # Verification rapide
    if 'data-key=' not in content:
        continue

    soup    = BeautifulSoup(content, "html.parser")
    changed = False

    for li in soup.find_all(attrs={"data-key": True}):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "")
        if not href or href == "#":
            continue
        # Ajouter/remplacer l'onclick inline
        if a.get("onclick") != ONCLICK:
            a["onclick"] = ONCLICK
            changed = True
            patched_links += 1

    if changed:
        html_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
        patched_files += 1

print(f"  {patched_files} fichiers modifies")
print(f"  {patched_links} liens patches")
print("Termine.")
