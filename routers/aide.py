"""Tutoriels d'utilisation (menu « Aide »).

Une seule source : templates/aide/<tuto>.html. Les PDF (static/aide/tuto_<tuto>.pdf) sont
l'impression de ces mêmes pages par outils/tutos.py : le site et les PDF disent la même chose.
"""
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

import config
from web import PasAutorise, connexion_requise, est_prof, render

router = APIRouter(prefix="/admin", dependencies=[Depends(connexion_requise)], tags=["Aide"])

DOSSIER_CAPTURES = Path("static") / "aide"

# clé -> (titre, public, icône, accessible aux profs, résumé)
TUTOS = {
    "enseignant": ("Tutoriel enseignant", "les professeurs", "person-video3", True,
                   "Se connecter, suivre l'appel de son cours en direct, corriger un statut, comprendre le boîtier."),
    "secretariat": ("Tutoriel secrétariat", "le secrétariat pédagogique", "folder2-open", False,
                    "Importer les étudiants, associer les cartes, suivre et justifier les absences, exporter vers ScoDoc."),
    "administrateur": ("Tutoriel administrateur", "le responsable technique", "tools", False,
                       "Comptes des professeurs, boîtiers, salles et groupes, fin d'année et RGPD, installation et pannes."),
}


def tutos_visibles(request: Request) -> dict:
    """Un prof ne voit que le tutoriel enseignant ; l'administrateur voit tout."""
    prof = est_prof(request)
    return {cle: t for cle, t in TUTOS.items() if t[3] or not prof}


def _fichiers_aide() -> set:
    """Noms (sans extension) des fichiers présents dans static/aide/."""
    if not DOSSIER_CAPTURES.is_dir():
        return set()
    return {f.stem for f in DOSSIER_CAPTURES.iterdir()}


@router.get("/aide")
def sommaire(request: Request):
    return render(request, "aide/index.html", actif="aide", tutos=tutos_visibles(request),
                  fichiers=_fichiers_aide())


@router.get("/aide/{tuto}")
def tutoriel(tuto: str, request: Request):
    if tuto not in TUTOS:
        raise HTTPException(status_code=404, detail="Tutoriel inconnu")
    if tuto not in tutos_visibles(request):
        raise PasAutorise()
    titre, public, icone, _, _ = TUTOS[tuto]
    return render(request, f"aide/{tuto}.html", actif="aide", tuto=tuto, titre=titre, public=public,
                  icone=icone, captures=_fichiers_aide(), date_du_jour=date.today().strftime("%d/%m/%Y"),
                  AVANCE_POINTAGE_MIN=config.AVANCE_POINTAGE_MIN)
