#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_dashboard.py
----------------
Corrige le dashboard offline :

1. Supprime / remplace les blocs AJAX (Chronologie, Cours récents)
   qui causent une popup "Error: missing response" et un chargement infini.
2. Injecte un shim JS robuste EN TÊTE de page pour intercepter
   tous les appels réseau vers le vrai Moodle avant que le JS s'exécute.
3. Remplace les images qui pointent encore vers le serveur live.
"""

import re
from pathlib import Path
from bs4 import BeautifulSoup

OFFLINE   = Path(__file__).parent / "moodle_offline"
DASHBOARD = OFFLINE / "dashboard" / "index.html"
INDEX     = OFFLINE / "index.html"

# ── Shim JS injecté tout en haut du <head> ─────────────────────────────────
# Doit s'exécuter AVANT tout le JS Moodle pour intercepter fetch / XHR.
SHIM_JS = """\
<script>
/* =========================================================
   OFFLINE SHIM – intercept all network calls to Moodle
   Injected by fix_dashboard.py
   ========================================================= */
(function () {
  var MOODLE = 'https://foad-moodle.ensai.fr';

  /* --- helper : build N Moodle-format responses from a request body --- */
  function buildResponses(bodyStr) {
    var reqs = [];
    try { reqs = JSON.parse(bodyStr || '[]'); } catch (e) {}
    if (!Array.isArray(reqs)) reqs = [reqs];
    return JSON.stringify(reqs.map(function () {
      return { error: false, data: null };
    }));
  }

  /* --- 1. fetch() -------------------------------------------------------- */
  var _fetch = window.fetch;
  window.fetch = function (resource, init) {
    var url = (typeof resource === 'string') ? resource : (resource && resource.url) || '';
    if (url.indexOf(MOODLE) !== -1) {
      var body = (init && init.body) ? String(init.body) : '[]';
      return Promise.resolve(
        new Response(buildResponses(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      );
    }
    return _fetch ? _fetch.apply(this, arguments)
                  : Promise.reject(new TypeError('Network request failed'));
  };

  /* --- 2. XMLHttpRequest ------------------------------------------------- */
  var NativeXHR = window.XMLHttpRequest;
  function PatchedXHR() {
    var real  = new NativeXHR();
    var self  = this;
    var muted = false;   // true when the URL targets Moodle
    var reqBody = '[]';

    /* ---- open ---- */
    self.open = function (method, url) {
      muted = (typeof url === 'string' && url.indexOf(MOODLE) !== -1);
      if (!muted) real.open.apply(real, arguments);
    };

    /* ---- setRequestHeader ---- */
    self.setRequestHeader = function () {
      if (!muted) real.setRequestHeader.apply(real, arguments);
    };

    /* ---- send ---- */
    self.send = function (body) {
      if (muted) {
        reqBody = (body != null) ? String(body) : '[]';
        var resp = buildResponses(reqBody);
        // Fire callbacks asynchronously, just like a real XHR would
        setTimeout(function () {
          /* Patch own props so Moodle reads the right values */
          Object.defineProperties(self, {
            readyState:   { value: 4,    writable: true, configurable: true },
            status:       { value: 200,  writable: true, configurable: true },
            responseText: { value: resp, writable: true, configurable: true },
            response:     { value: resp, writable: true, configurable: true }
          });
          if (typeof self.onreadystatechange === 'function') {
            self.onreadystatechange();
          }
          if (typeof self.onload === 'function') {
            self.onload();
          }
        }, 20);
        return;
      }
      /* Proxy real XHR events back to self */
      real.onreadystatechange = function () {
        Object.defineProperties(self, {
          readyState:   { get: function () { return real.readyState; },   configurable: true },
          status:       { get: function () { return real.status; },       configurable: true },
          responseText: { get: function () { return real.responseText; }, configurable: true },
          response:     { get: function () { return real.response; },     configurable: true }
        });
        if (typeof self.onreadystatechange === 'function') self.onreadystatechange();
      };
      real.onload  = function () { if (typeof self.onload  === 'function') self.onload();  };
      real.onerror = function () { if (typeof self.onerror === 'function') self.onerror(); };
      real.send.apply(real, arguments);
    };

    /* Proxy misc methods */
    ['abort', 'getResponseHeader', 'getAllResponseHeaders',
     'overrideMimeType', 'addEventListener', 'removeEventListener'].forEach(function (m) {
      self[m] = function () { if (!muted) return real[m].apply(real, arguments); };
    });
    Object.defineProperty(self, 'upload', { get: function () { return real.upload; } });
  }
  /* Copy static constants */
  [0,1,2,3,4].forEach(function (n) { PatchedXHR[n] = n; });
  PatchedXHR.UNSENT           = 0;
  PatchedXHR.OPENED           = 1;
  PatchedXHR.HEADERS_RECEIVED = 2;
  PatchedXHR.LOADING          = 3;
  PatchedXHR.DONE             = 4;
  window.XMLHttpRequest = PatchedXHR;

  /* --- 3. Suppress ALL unhandled promise rejections (AJAX errors) -------- */
  window.addEventListener('unhandledrejection', function (e) {
    e.preventDefault();
    e.stopPropagation();
    return false;
  });

  /* --- 4. MutationObserver : auto-close any Moodle error dialog ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          /* Moodle error modals : data-region="modal" or class modal */
          var isModal = (
            node.matches && (
              node.matches('[data-region="modal-container"]') ||
              node.matches('.modal') ||
              node.matches('[role="dialog"]')
            )
          ) || (node.querySelector && node.querySelector('[data-region="modal-container"], .modal-dialog'));
          if (isModal) {
            /* Try clicking the close button first */
            var closeBtn = node.querySelector(
              '[data-action="hide"], [data-dismiss="modal"], ' +
              '.close, button.btn-secondary, [aria-label="Fermer"]'
            );
            if (closeBtn) {
              setTimeout(function () { closeBtn.click(); }, 50);
            } else {
              setTimeout(function () { node.remove(); }, 50);
            }
          }
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });

  /* --- 5. Silence M.core.exception after Moodle loads -------------------- */
  window.addEventListener('load', function () {
    setTimeout(function () {
      if (window.require) {
        try {
          require(['core/notification'], function (notif) {
            if (notif && notif.exception) notif.exception = function () {};
          });
        } catch (e) {}
      }
      if (window.M && window.M.util) {
        window.M.util.show_confirm_dialog = function () {};
      }
    }, 300);
  });
})();
</script>
"""

# ── Remplacement des blocs dynamiques ──────────────────────────────────────
OFFLINE_NOTICE = """
<div class="card-body p-3 text-muted" style="font-size:.9em">
  <span class="fa fa-wifi-slash" aria-hidden="true"></span>
  Contenu dynamique — non disponible hors ligne.
</div>
"""


def patch_dynamic_block(soup, block_name, title):
    """Vide le contenu d'un bloc dynamique et y met un message statique."""
    block = soup.find(attrs={"data-block": block_name})
    if not block:
        return False
    # Garder le header du bloc si présent
    header = block.find(class_=re.compile(r"card-header|block-header"))
    block.clear()
    if header:
        block.append(header)
    notice = BeautifulSoup(OFFLINE_NOTICE, "html.parser")
    block.append(notice)
    return True


def main():
    print("Lecture du dashboard...")
    content = DASHBOARD.read_text(encoding="utf-8", errors="ignore")

    # Supprimer l'ancien shim s'il existe
    content = re.sub(
        r'<script>\s*/\* ={3,}\s*OFFLINE SHIM.*?</script>',
        '',
        content,
        flags=re.DOTALL
    )
    content = re.sub(
        r'<script>\s*/\* ──+ Offline AJAX shim.*?</script>',
        '',
        content,
        flags=re.DOTALL
    )

    soup = BeautifulSoup(content, "html.parser")

    # 1. Injecter le shim en tout premier dans <head>
    head = soup.find("head")
    if head:
        shim_tag = BeautifulSoup(SHIM_JS, "html.parser")
        head.insert(0, shim_tag)
        print("  Shim JS injecte en tete du <head>")

    # 2. Remplacer les blocs dynamiques (tous ceux qui font des appels AJAX)
    for block_name in ("timeline", "recentlyaccessedcourses", "recentlyaccesseditems",
                       "calendar_upcoming"):
        if patch_dynamic_block(soup, block_name, block_name):
            print(f"  Bloc '{block_name}' remplace par message statique")

    # 3. Supprimer les src qui pointent encore vers le serveur live (images)
    for tag in soup.find_all(src=re.compile(r'https://foad-moodle')):
        tag.decompose()
        print(f"  Tag live supprime : {tag.name}")

    # 4. Sauvegarder
    DASHBOARD.write_text("<!DOCTYPE html>\n" + str(soup), encoding="utf-8")
    print(f"\nDashboard patche : {DASHBOARD}")
    print("Recharger http://localhost:8765/dashboard/index.html pour verifier")


if __name__ == "__main__":
    main()
