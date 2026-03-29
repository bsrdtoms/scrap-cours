#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_nav_keys.py — Répare les liens de navigation par data-key Moodle.

- data-key="home"       → Accueil  → pointe vers index.html (liste des cours)
- data-key="mycourses"  → Mes cours → pointe vers index.html (liste des cours)
- data-key="myhome"     → Tableau de bord → déjà ok (dashboard/index.html)

Aussi :
- Injecte un script JS dans dashboard/index.html pour résoudre
  l'état de chargement infini de la Chronologie (AJAX non disponible hors ligne)
"""

import os
from pathlib import Path
from bs4 import BeautifulSoup

OFFLINE   = Path(__file__).parent / "moodle_offline"
INDEX     = OFFLINE / "index.html"
DASHBOARD = OFFLINE / "dashboard" / "index.html"

fixed_files   = 0
skipped_files = 0

# ── Étape 1 : réparer data-key="home" et data-key="mycourses" ──────────────

html_files = list(OFFLINE.rglob("*.html"))
print(f"Fichiers HTML à traiter : {len(html_files)}")

for html_path in html_files:
    content = html_path.read_text(encoding="utf-8", errors="ignore")

    # Pré-vérification rapide pour ne pas parser inutilement
    if 'data-key="home"' not in content and 'data-key="mycourses"' not in content:
        skipped_files += 1
        continue

    soup    = BeautifulSoup(content, "html.parser")
    changed = False

    for key, target_file in [("home", INDEX), ("mycourses", INDEX)]:
        li = soup.find("li", attrs={"data-key": key})
        if not li:
            continue
        a = li.find("a", href=True)
        if not a:
            continue

        # Calculer le chemin relatif depuis ce fichier vers la cible
        try:
            rel = os.path.relpath(str(target_file), str(html_path.parent))
            rel = rel.replace("\\", "/")
        except ValueError:
            rel = str(target_file).replace("\\", "/")

        # Ne modifier que si c'est encore un lien cassé "#"
        if a.get("href") == "#" or a.get("title") == "Non disponible hors ligne":
            a["href"] = rel
            a.attrs.pop("title", None)
            a.attrs.pop("style", None)
            changed = True

    if changed:
        html_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
        fixed_files += 1

print(f"  → {fixed_files} fichiers corrigés (data-key home/mycourses)")


# ── Étape 2 : injecter le correctif AJAX dans le Tableau de bord ────────────

print("\nInjection du correctif AJAX dans dashboard/index.html...")

AJAX_FIX = """
<script>
/* ── Offline AJAX shim ── empêche le chargement infini de la Chronologie */
(function () {
  'use strict';

  /* 1) Intercepter fetch() pour les appels AJAX Moodle */
  var _fetch = window.fetch;
  window.fetch = function (url, opts) {
    if (typeof url === 'string' &&
        (url.indexOf('/lib/ajax/') !== -1 || url.indexOf('service.php') !== -1)) {
      /* Répondre avec un tableau vide valide pour Moodle */
      return Promise.resolve(new Response('[]', {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      }));
    }
    return _fetch.apply(this, arguments);
  };

  /* 2) Intercepter XMLHttpRequest pour les mêmes endpoints */
  var _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    if (typeof url === 'string' &&
        (url.indexOf('/lib/ajax/') !== -1 || url.indexOf('service.php') !== -1)) {
      this._offlineBlocked = true;
    }
    return _open.apply(this, arguments);
  };
  var _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) {
    if (this._offlineBlocked) {
      /* Simuler une réponse vide immédiate */
      Object.defineProperty(this, 'readyState', { get: function () { return 4; } });
      Object.defineProperty(this, 'status',    { get: function () { return 200; } });
      Object.defineProperty(this, 'responseText', { get: function () { return '[]'; } });
      setTimeout(function () {
        if (typeof this.onreadystatechange === 'function') this.onreadystatechange();
        if (typeof this.onload === 'function') this.onload();
      }.bind(this), 50);
      return;
    }
    return _send.apply(this, arguments);
  };

  /* 3) Après 3 secondes, remplacer les blocs encore en chargement */
  window.addEventListener('DOMContentLoaded', function () {
    setTimeout(function () {
      /* Skeleton loaders / spinners encore visibles */
      document.querySelectorAll('[data-region="loading-icon-container"]').forEach(function (el) {
        el.innerHTML = '<p class="text-muted p-3">⚠️ Contenu dynamique non disponible hors ligne.</p>';
      });
      /* Blocs de la chronologie encore en cours de chargement */
      document.querySelectorAll('[data-region="timeline-view"]').forEach(function (el) {
        var placeholder = el.querySelector('.loading-icon, .spinner-border, [aria-label="Chargement"]');
        if (placeholder) {
          el.innerHTML = '<p class="text-muted p-3">⚠️ Chronologie non disponible hors ligne.</p>';
        }
      });
      /* Cours récemment consultés */
      document.querySelectorAll('[data-region="course-view-content"]').forEach(function (el) {
        var placeholder = el.querySelector('.loading-icon, .spinner-border');
        if (placeholder) {
          el.innerHTML = '<p class="text-muted p-3">⚠️ Contenu dynamique non disponible hors ligne.</p>';
        }
      });
    }, 3000);
  });
})();
</script>
"""

if DASHBOARD.exists():
    dash_content = DASHBOARD.read_text(encoding="utf-8", errors="ignore")
    if "Offline AJAX shim" not in dash_content:
        # Insérer juste avant </body>
        dash_content = dash_content.replace("</body>", AJAX_FIX + "\n</body>")
        DASHBOARD.write_text(dash_content, encoding="utf-8")
        print("  → Correctif AJAX injecté dans dashboard/index.html")
    else:
        print("  → Correctif AJAX déjà présent")
else:
    print("  → dashboard/index.html introuvable, ignoré")


# ── Résumé ──────────────────────────────────────────────────────────────────
print(f"\nTerminé. {fixed_files} fichiers corrigés.")
print(f"Ouvrir : http://localhost:8765/index.html")
