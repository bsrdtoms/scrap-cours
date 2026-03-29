#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_icons.py
Renomme les fichiers SVG/PNG/GIF sans extension dans assets/theme/image.php
et met à jour toutes les références dans les HTML.
"""
import os, re
from pathlib import Path

OFFLINE = Path(__file__).parent / "moodle_offline"
base = OFFLINE / "assets" / "theme" / "image.php"

# 1. Identifier et renommer
renames = {}
no_ext = [p for p in base.rglob("*") if p.is_file() and not p.suffix]

for p in no_ext:
    data = p.read_bytes()[:10]
    if data[:4] == b"<svg" or b"<?xml" in data[:10]:
        ext = ".svg"
    elif data[:4] == b"\x89PNG":
        ext = ".png"
    elif data[:2] == b"\xff\xd8":
        ext = ".jpg"
    elif data[:4] == b"GIF8":
        ext = ".gif"
    else:
        print(f"  Type inconnu: {p.name} — {data[:4]}")
        continue

    new_p = p.with_suffix(ext)
    old_rel = p.relative_to(OFFLINE).as_posix()
    new_rel = new_p.relative_to(OFFLINE).as_posix()
    renames[old_rel] = new_rel
    p.rename(new_p)
    print(f"  Renommé: {p.name} → {new_p.name}")

print(f"\n{len(renames)} fichiers renommés")

# 2. Mettre à jour les références dans tous les HTML
html_files = list(OFFLINE.rglob("*.html"))
updated = 0

for html_path in html_files:
    content = html_path.read_text(encoding="utf-8", errors="ignore")
    changed = False

    for old_rel, new_rel in renames.items():
        try:
            old_from_here = os.path.relpath(
                str(OFFLINE / old_rel), str(html_path.parent)
            ).replace("\\", "/")
            new_from_here = os.path.relpath(
                str(OFFLINE / new_rel), str(html_path.parent)
            ).replace("\\", "/")
        except ValueError:
            continue

        if old_from_here in content:
            content = content.replace(old_from_here, new_from_here)
            changed = True

    if changed:
        html_path.write_text(content, encoding="utf-8")
        updated += 1

print(f"{updated} fichiers HTML mis à jour")
print("Terminé.")
