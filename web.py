"""Outils communs aux pages web : templates, messages de confirmation, connexion."""
import time

from fastapi import Request
from fastapi.templating import Jinja2Templates

import config
from services.groupes import groupe_affiche
from services.temps import jour_fr

templates = Jinja2Templates(directory="templates")


# --- Filtres utilisables dans les templates : {{ date | heure }} ---
def _heure(d):
    return d.strftime("%H:%M") if d else "—"


def _date_courte(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def _date_heure(d):
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


templates.env.filters["heure"] = _heure
templates.env.filters["date_courte"] = _date_courte
templates.env.filters["date_heure"] = _date_heure
templates.env.filters["jour_fr"] = jour_fr
templates.env.globals["TOLERANCE_RETARD_MIN"] = config.TOLERANCE_RETARD_MIN


# --- Listes déroulantes de classes, regroupées par promo ---
def promo_de(nom_groupe: str) -> str:
    for promo in ("BUT1", "BUT2", "BUT3"):
        if nom_groupe.startswith(promo):
            return promo.replace("BUT", "BUT ")
    return "Autres"


templates.env.filters["promo"] = promo_de     # {{ "BUT2-TD1" | promo }} -> "BUT 2"
# {{ etudiant.groupes | groupe_affiche }} -> "BUT3-TD3-PB" (voir services/groupes.py)
templates.env.filters["groupe_affiche"] = lambda groupes: groupe_affiche([g.nom_groupe for g in groupes])


def groupes_par_promo(groupes):
    """Pour la liste déroulante : {'BUT 1': [...], 'BUT 2': [...], ...}"""
    resultat = {}
    for promo in ("BUT 1", "BUT 2", "BUT 3", "Autres"):
        membres = sorted((g for g in groupes if promo_de(g.nom_groupe) == promo), key=lambda g: g.nom_groupe)
        if membres:
            resultat[promo] = membres
    return resultat


# --- Messages "flash" : affichés une fois sur la page suivante ---
def flash(request: Request, message: str, categorie: str = "success"):
    """categorie : success, danger, warning ou info (couleurs Bootstrap)."""
    if message:
        request.session.setdefault("flash", []).append({"message": message, "categorie": categorie})


def render(request: Request, nom: str, actif: str = "", **contexte):
    """Affiche un template en ajoutant ce dont toutes les pages ont besoin."""
    contexte.update(
        actif=actif,
        messages=request.session.pop("flash", []),
        admin=request.session.get("admin"),
        est_prof=est_prof(request),
        mot_de_passe_par_defaut=config.MOT_DE_PASSE_PAR_DEFAUT,
    )
    return templates.TemplateResponse(request=request, name=nom, context=contexte)


# --- Connexion obligatoire pour l'interface d'administration ---
class NonConnecte(Exception):
    """Levée quand une page admin est demandée sans être connecté."""
    def __init__(self, suivant: str):
        self.suivant = suivant


class PasAutorise(Exception):
    """Levée quand un prof demande une page réservée à l'administrateur."""


def est_prof(request: Request) -> bool:
    return request.session.get("id_prof") is not None


def prof_connecte(request: Request):
    """Id du prof connecté, ou None pour l'administrateur."""
    return request.session.get("id_prof")


def connexion_requise(request: Request):
    """Dépendance FastAPI : pages accessibles à l'administrateur ET aux profs."""
    if not request.session.get("admin"):
        raise NonConnecte(request.url.path)
    # Modifier la session la fait ré-signer : le délai d'inactivité repart de zéro
    request.session["actif"] = int(time.time())


def admin_requis(request: Request):
    """Dépendance FastAPI : pages réservées à l'administrateur."""
    connexion_requise(request)
    if est_prof(request):
        raise PasAutorise()
