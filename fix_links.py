#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Répare les liens dans les HTML offline en utilisant mapping.json"""
import json, os
from pathlib import Path
from bs4 import BeautifulSoup

offline  = Path(__file__).parent / "moodle_offline"
base_url = "https://foad-moodle.ensai.fr"

mapping = json.loads((offline / "mapping.json").read_text(encoding="utf-8"))

def fix_html(html_path):
    content = html_path.read_text(encoding="utf-8", errors="ignore")
    soup    = BeautifulSoup(content, "html.parser")
    changed = False
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        # Ignorer les liens déjà locaux ou les ancres
        if href.startswith("#") or (not href.startswith("http") and not href.startswith("/")):
            continue
        abs_href = href if href.startswith("http") else base_url + href
        if abs_href in mapping:
            local = Path(mapping[abs_href])
            rel   = os.path.relpath(str(local), str(html_path.parent))
            rel   = rel.replace("\\", "/")
            tag["href"] = rel
            for attr in ("title", "style"):
                if attr in tag.attrs:
                    del tag[attr]
            changed = True
    if changed:
        html_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
    return changed

files = list(offline.rglob("*.html"))
print(f"Reparation de {len(files)} fichiers...")
fixed = sum(1 for f in files if fix_html(f))
print(f"{fixed} fichiers repares")

idx_soup = BeautifulSoup((offline / "index.html").read_text(encoding="utf-8"), "html.parser")
course_links = [l["href"] for l in idx_soup.find_all("a", href=True) if "cours/" in l.get("href","")]
print(f"Liens cours dans index.html : {len(course_links)}")
print("Exemples :", course_links[:4])
