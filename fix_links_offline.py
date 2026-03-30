#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_links_offline.py
====================
Post-traitement : remplace tous les liens internes Moodle qui pointent
encore vers le site original par '#' dans un dossier offline.

Usage :
  python fix_links_offline.py                              ← demande le dossier
  python fix_links_offline.py --dir moodle_offline_psl.eu
  python fix_links_offline.py --dir moodle_offline_psl.eu --url https://moodle.psl.eu
"""

import re
import sys
import argparse
from pathlib import Path
from bs4 import BeautifulSoup


def fix_html(path: Path, moodle_domain: str) -> int:
    """Corrige les liens dans un fichier HTML. Retourne le nb de liens modifiés."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(content, "html.parser")
    changed = 0

    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        # Lien absolu vers le Moodle original
        if moodle_domain in href:
            tag["href"] = "#"
            changed += 1
        # Lien absolu commençant par / (chemin absolu du serveur)
        elif href.startswith("/") and not href.startswith("//"):
            tag["href"] = "#"
            changed += 1

    if changed:
        path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")

    return changed


def main():
    parser = argparse.ArgumentParser(
        description="Remplace les liens Moodle internes par # dans un dossier offline"
    )
    parser.add_argument(
        "--dir", type=str,
        help="Dossier offline à corriger (ex: moodle_offline_moodle.psl.eu)"
    )
    parser.add_argument(
        "--url", type=str,
        help="URL du Moodle original (ex: https://moodle.psl.eu) — déduit du nom du dossier si absent"
    )
    args = parser.parse_args()

    # Déterminer le dossier
    base = Path(__file__).parent
    offline_dir = None

    if args.dir:
        offline_dir = Path(args.dir) if Path(args.dir).is_absolute() else base / args.dir
    else:
        # Proposer les dossiers moodle_offline_* présents
        candidates = sorted(base.glob("moodle_offline_*"))
        if not candidates:
            print("Aucun dossier moodle_offline_* trouvé.")
            dir_input = input("Chemin du dossier offline : ").strip()
            offline_dir = Path(dir_input)
        elif len(candidates) == 1:
            offline_dir = candidates[0]
            print(f"Dossier détecté : {offline_dir}")
        else:
            print("Dossiers disponibles :")
            for i, c in enumerate(candidates):
                print(f"  [{i}] {c.name}")
            idx = int(input("Numéro du dossier à corriger : ").strip())
            offline_dir = candidates[idx]

    if not offline_dir.exists():
        print(f"Erreur : dossier introuvable — {offline_dir}")
        sys.exit(1)

    # Déterminer le domaine Moodle
    if args.url:
        moodle_domain = args.url.replace("https://", "").replace("http://", "").rstrip("/")
    else:
        # Déduire depuis le nom du dossier (moodle_offline_moodle.psl.eu → moodle.psl.eu)
        folder_name = offline_dir.name
        if folder_name.startswith("moodle_offline_"):
            moodle_domain = folder_name[len("moodle_offline_"):]
        else:
            moodle_domain = input("Domaine Moodle à remplacer (ex: moodle.psl.eu) : ").strip()

    print(f"\nDossier  : {offline_dir}")
    print(f"Domaine  : {moodle_domain}")

    # Parcourir tous les HTML
    html_files = list(offline_dir.rglob("*.html"))
    print(f"Fichiers : {len(html_files)} HTML trouvés\n")

    total_files   = 0
    total_changed = 0

    for html_path in sorted(html_files):
        n = fix_html(html_path, moodle_domain)
        if n:
            rel = html_path.relative_to(offline_dir)
            print(f"  OK {rel}  ({n} liens corriges)")
            total_files   += 1
            total_changed += n

    print(f"\nTermine : {total_changed} liens corriges dans {total_files} fichiers")


if __name__ == "__main__":
    main()
