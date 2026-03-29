#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_participants_click.py
Corrige le clic sur l'onglet Participants dans les pages de cours.
Moodle remplace le href par '#' et supprime onmousedown au chargement,
donc on injecte un fix via setTimeout (après l'init Moodle).
"""
from pathlib import Path
from bs4 import BeautifulSoup
import re

OFFLINE = Path(__file__).parent / "moodle_offline"
COURS_DIR = OFFLINE / "cours"

# Script injecté en fin de <body>, après que Moodle a fini son init
PARTICIPANTS_FIX = """<script>
/* PARTICIPANTS TAB FIX — setTimeout après init Moodle */
(function(){
  function fixParticipants(){
    var li = document.querySelector('[data-key="participants"]');
    if(!li) return;
    var a = li.querySelector('a');
    if(!a) return;
    // Remettre le bon href (Moodle l'a mis à '#')
    a.setAttribute('href','participants/index.html');
    // Ajouter listener direct sur l'élément (capture phase)
    // => se déclenche avant les handlers de délégation de Moodle
    a.addEventListener('click', function(e){
      e.stopImmediatePropagation();
      e.preventDefault();
      window.location.href = 'participants/index.html';
    }, true);
    console.log('[offline] participants tab fix applied, href=', a.getAttribute('href'));
  }
  // Lancer après l'init Moodle (200ms et 600ms au cas où)
  setTimeout(fixParticipants, 200);
  setTimeout(fixParticipants, 600);
})();
</script>"""

OLD_EARLY_SCRIPT_PATTERN = re.compile(
    r'<script>\s*/\* PARTICIPANTS NAV FIX[^<]*?</script>',
    re.DOTALL
)

def fix_course(index_path: Path) -> bool:
    content = index_path.read_text(encoding="utf-8", errors="ignore")

    # 1. Supprimer l'ancien early-capture script s'il existe
    content_new = OLD_EARLY_SCRIPT_PATTERN.sub('', content)

    soup = BeautifulSoup(content_new, "html.parser")

    # 2. Supprimer le onmousedown sur le lien participants
    for li in soup.find_all(attrs={"data-key": "participants"}):
        a = li.find("a")
        if a:
            if a.get("onmousedown"):
                del a["onmousedown"]
            # Remettre le href correct (au cas où il aurait été mis à '#' dans le HTML)
            if a.get("href") == "#" or not a.get("href"):
                a["href"] = "participants/index.html"

    # 3. Supprimer tout ancien fix participants en fin de body
    for sc in soup.find_all("script"):
        txt = sc.string or ""
        if "PARTICIPANTS TAB FIX" in txt or "PARTICIPANTS NAV FIX" in txt:
            sc.decompose()

    # 4. Injecter le nouveau fix à la fin du <body>
    body = soup.find("body")
    if body:
        body.append(BeautifulSoup(PARTICIPANTS_FIX, "html.parser"))
    else:
        return False

    index_path.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
    return True


if __name__ == "__main__":
    fixed = 0
    skipped = 0
    for course_dir in sorted(COURS_DIR.iterdir()):
        if not course_dir.is_dir():
            continue
        index_path = course_dir / "index.html"
        if not index_path.exists():
            print(f"  SKIP (pas d'index.html): {course_dir.name}")
            skipped += 1
            continue
        result = fix_course(index_path)
        print(f"  {'OK' if result else 'FAIL'}: {course_dir.name}")
        if result:
            fixed += 1

    print(f"\nTerminé: {fixed} cours fixés, {skipped} ignorés")
