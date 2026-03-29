#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_nav_fix.py
-----------------
Injecte dans TOUS les HTML offline un script qui force la navigation
sur les liens de la barre de navigation Moodle (Accueil, Tableau de bord,
Mes cours) dont les clics sont interceptés par le JS Moodle.
"""
from pathlib import Path

OFFLINE = Path(__file__).parent / "moodle_offline"

NAV_FIX = """\
<script>
/* OFFLINE NAV FIX — force navigation on Moodle primary nav clicks */
(function () {
  function patchNav() {
    document.querySelectorAll('[data-key] > a[href]').forEach(function (a) {
      var href = a.getAttribute('href');
      if (!href || href === '#') return;
      // Capture phase : s'exécute avant les handlers Moodle
      a.addEventListener('click', function (e) {
        e.stopImmediatePropagation();
        e.preventDefault();
        window.location.href = a.getAttribute('href');
      }, true);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', patchNav);
  } else {
    patchNav();
  }
})();
</script>"""

html_files = list(OFFLINE.rglob("*.html"))
print(f"Fichiers HTML trouves : {len(html_files)}")

injected = 0
already  = 0

for f in html_files:
    content = f.read_text(encoding="utf-8", errors="ignore")
    if "OFFLINE NAV FIX" in content:
        already += 1
        continue
    # Injecter juste avant </head>
    if "</head>" in content:
        content = content.replace("</head>", NAV_FIX + "\n</head>", 1)
    elif "</body>" in content:
        content = content.replace("</body>", NAV_FIX + "\n</body>", 1)
    else:
        content += "\n" + NAV_FIX
    f.write_text(content, encoding="utf-8")
    injected += 1

print(f"  injecte  : {injected}")
print(f"  deja ok  : {already}")
print("Termine.")
