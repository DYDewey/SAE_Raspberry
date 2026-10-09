"""Connexion à l'interface d'administration."""
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

import config
from web import admin_requis, flash, render

router = APIRouter(tags=["Connexion"])


def _lien_sur(suivant: str) -> str:
    """N'autorise qu'une redirection interne (évite /login?suivant=https://site-pirate)."""
    return suivant if suivant.startswith("/") and not suivant.startswith("//") else "/admin"


@router.get("/login")
def page_login(request: Request, suivant: str = "/admin"):
    if request.session.get("admin"):
        return RedirectResponse(url=_lien_sur(suivant), status_code=303)
    return render(request, "login.html", suivant=suivant)


@router.post("/login")
def connexion(request: Request, identifiant: str = Form(...), mot_de_passe: str = Form(...),
              suivant: str = Form("/admin")):
    ok_user = secrets.compare_digest(identifiant.encode(), config.ADMIN_USER.encode())
    ok_mdp = secrets.compare_digest(mot_de_passe.encode(), config.ADMIN_PASSWORD.encode())
    if not (ok_user and ok_mdp):
        flash(request, "Identifiant ou mot de passe incorrect.", "danger")
        return render(request, "login.html", suivant=suivant, identifiant=identifiant)
    request.session["admin"] = identifiant
    return RedirectResponse(url=_lien_sur(suivant), status_code=303)


@router.post("/logout")
def deconnexion(request: Request):
    request.session.clear()
    flash(request, "Vous êtes déconnecté.", "info")
    return RedirectResponse(url="/login", status_code=303)


@router.get("/admin/ping", dependencies=[Depends(admin_requis)], include_in_schema=False)
def signal_de_vie():
    """Appelé régulièrement par les pages ouvertes : renouvelle le cookie de session."""
    return Response(status_code=204)
