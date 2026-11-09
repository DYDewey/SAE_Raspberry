"""Captures d'écran et PDF des tutoriels (menu Aide), sur la base de démo FICTIVE.

    venv/Scripts/python outils/demo_tutos.py      # 1. (re)crée la base de démo
    venv/Scripts/python outils/tutos.py           # 2. captures + PDF
    venv/Scripts/python outils/tutos.py captures  #    seulement les captures
    venv/Scripts/python outils/tutos.py pdf       #    seulement les PDF

Lance un serveur temporaire (port 8790) sur demo_tutos.db, pilote Microsoft Edge déjà
installé (Playwright, channel « msedge » : aucun navigateur à télécharger), puis :
  - captures -> static/aide/<nom>.png (utilisées par templates/aide/*.html)
  - PDF      -> static/aide/tuto_<tuto>.pdf (bouton « Télécharger le PDF » du site)
"""
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

RACINE = Path(__file__).resolve().parent.parent
BASE_DEMO = RACINE / "demo_tutos.db"
CAPTURES = RACINE / "static" / "aide"
PORT = 8790
URL = f"http://127.0.0.1:{PORT}"
ADMIN = ("secretariat", "demo-admin")
PROF = ("pmartin", "demo-prof")          # créé par outils/demo_tutos.py
TUTOS = ["enseignant", "secretariat", "administrateur"]
TAILLE = {"width": 1400, "height": 860}


# ---------- serveur temporaire sur la base de démo ----------
def lancer_serveur():
    if not BASE_DEMO.exists():
        sys.exit("Base de démo absente : lancer d'abord outils/demo_tutos.py")
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{BASE_DEMO.as_posix()}", ICAL_URL="",
               ADMIN_USER=ADMIN[0], ADMIN_PASSWORD=ADMIN[1])
    serveur = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                               cwd=RACINE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{URL}/api/v1/status", timeout=1)
            return serveur
        except OSError:
            time.sleep(0.5)
    serveur.kill()
    sys.exit("Le serveur de démo n'a pas démarré")


def requete(sql, *params):
    with sqlite3.connect(BASE_DEMO) as conn:
        return conn.execute(sql, params).fetchone()


# ---------- navigateur ----------
def connecter(navigateur, compte):
    page = navigateur.new_page(viewport=TAILLE, locale="fr-FR")
    page.goto(f"{URL}/login")
    page.fill("input[name=identifiant]", compte[0])
    page.fill("input[name=mot_de_passe]", compte[1])
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    return page


def ouvrir(page, chemin):
    page.goto(URL + chemin)
    page.wait_for_load_state("networkidle")


def photo(page, nom, selecteur=None):
    """Capture de l'écran visible, ou d'un seul élément si selecteur est donné."""
    page.wait_for_timeout(400)                    # fin des animations (fenêtres, menus)
    chemin = CAPTURES / f"{nom}.png"
    if selecteur:
        page.locator(selecteur).first.screenshot(path=chemin)
    else:
        page.screenshot(path=chemin)
    print(f"  capture {chemin.name}")


def captures(navigateur):
    CAPTURES.mkdir(parents=True, exist_ok=True)
    maintenant = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seance_prof = requete("SELECT s.id FROM seances s JOIN professeurs p ON p.id = s.id_prof "
                          "WHERE p.identifiant = ? AND s.date_debut < ? ORDER BY s.date_debut DESC", PROF[0], maintenant)[0]
    td1 = requete("SELECT id FROM groupes WHERE nom_groupe = 'BUT1-TD1'")[0]
    etudiant_justifie = requete("SELECT id_etudiant FROM justificatifs")[0]

    print("Enseignant")
    page = navigateur.new_page(viewport=TAILLE, locale="fr-FR")
    ouvrir(page, "/login")
    page.fill("input[name=identifiant]", PROF[0])
    photo(page, "e-connexion")
    page.close()
    page = connecter(navigateur, PROF)
    ouvrir(page, "/admin/edt")
    photo(page, "e-mes-cours")
    page.click(f'.cours-carte[data-seance="{seance_prof}"]')
    page.wait_for_selector("#panneau-contenu table")
    photo(page, "e-emargement")
    page.locator('#panneau-contenu [title="Modifier le statut à la main"]').nth(1).click()
    photo(page, "e-valider-main")
    page.close()

    print("Secrétariat")
    page = connecter(navigateur, ADMIN)
    ouvrir(page, "/admin")
    photo(page, "s-tableau-de-bord")
    ouvrir(page, "/admin/etudiants")
    photo(page, "s-etudiants")
    page.click('[data-bs-target="#modal-import"]')
    photo(page, "s-import", "#modal-import .modal-content")
    ouvrir(page, "/admin/etudiants?sans_carte=1")
    page.locator("[data-scan]").first.click()
    photo(page, "s-scan")
    ouvrir(page, f"/admin/etudiants/{etudiant_justifie}")
    photo(page, "s-fiche")
    photo(page, "s-justificatif", '.card:has(.card-header:has-text("Justificatifs"))')
    ouvrir(page, f"/admin/edt?groupe={td1}")
    photo(page, "s-edt")
    ouvrir(page, "/admin/absences")
    photo(page, "s-absences")
    page.get_by_role("button", name="Feuille ScoDoc").click()
    photo(page, "s-scodoc")
    ouvrir(page, "/admin/pointages")
    photo(page, "s-pointages")

    print("Administrateur")
    ouvrir(page, "/admin/professeurs")
    photo(page, "a-professeurs")
    ouvrir(page, "/admin/configuration")
    photo(page, "a-config-boitiers")
    photo(page, "a-config-salles", '.row:has(.card-header:text-is("Salles"))')
    photo(page, "a-rgpd", '.row:has(#rgpd)')
    photo(page, "a-fin-annee", "#fin-annee")
    page.close()


def pdfs(navigateur):
    page = connecter(navigateur, ADMIN)
    pied = ('<div style="font-size:8px;width:100%;text-align:center;color:#888;font-family:sans-serif">'
            '<span class="title"></span> · page <span class="pageNumber"></span>/<span class="totalPages"></span></div>')
    for tuto in TUTOS:
        ouvrir(page, f"/admin/aide/{tuto}")
        page.emulate_media(media="print")
        chemin = CAPTURES / f"tuto_{tuto}.pdf"
        page.pdf(path=chemin, format="A4", print_background=True, prefer_css_page_size=True,
                 display_header_footer=True, header_template="<div></div>", footer_template=pied)
        print(f"  PDF {chemin.name} ({chemin.stat().st_size // 1024} ko)")
    page.close()


def main():
    quoi = sys.argv[1] if len(sys.argv) > 1 else "tout"
    serveur = lancer_serveur()
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch(channel="msedge", headless=True)
            if quoi in ("tout", "captures"):
                captures(navigateur)
            if quoi in ("tout", "pdf"):
                pdfs(navigateur)
            navigateur.close()
    finally:
        serveur.terminate()


if __name__ == "__main__":
    main()
