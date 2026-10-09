"""Point d'entrée du serveur : uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Organisation du code :
- config.py       paramètres (.env)
- database.py     connexion à PostgreSQL
- models.py       tables
- services/       logique métier (présences, import iCal, import Excel, dates)
- routers/        pages et API, une fichier par partie de l'interface
- web.py          outils communs aux pages (templates, messages, connexion)
- templates/      pages HTML (Jinja2 + Bootstrap)
- static/         CSS et JavaScript
"""
import time
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import config
import models
from database import engine
from routers import api, auth, configuration, edt, etudiants, professeurs, tableau_de_bord
from web import NonConnecte, PasAutorise, flash

# Crée les tables manquantes, puis met à jour les tables qui existaient déjà
models.Base.metadata.create_all(bind=engine)
models.migrer_schema(engine)

app = FastAPI(title="Pointage NFC - IUT")
# Le cookie de session est renouvelé à chaque page (ou signal de vie) : il n'expire
# qu'après SESSION_INACTIVITE_MIN minutes sans aucune activité
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, max_age=config.SESSION_INACTIVITE_MIN * 60)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def signaler_pages_lentes(request, call_next):
    """Affiche dans le terminal les pages qui mettent plus d'une seconde à répondre."""
    debut = time.perf_counter()
    reponse = await call_next(request)
    duree = time.perf_counter() - debut
    if duree > 1:
        print(f"Page lente : {request.method} {request.url.path} en {duree:.1f} s")
    return reponse


@app.exception_handler(NonConnecte)
def rediriger_vers_login(request, exc: NonConnecte):
    # Appel fait par le JavaScript d'une page (ex : fenêtre "Scanner") : une redirection
    # vers la page de connexion passerait inaperçue, on répond 401 pour qu'il l'affiche
    if "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"statut": "deconnecte"}, status_code=401)
    return RedirectResponse(url=f"/login?suivant={quote(exc.suivant)}", status_code=303)


@app.exception_handler(PasAutorise)
def reserve_admin(request, exc: PasAutorise):
    """Un prof n'a accès qu'à l'emploi du temps et à l'émargement de ses cours."""
    if "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"statut": "interdit"}, status_code=403)
    if request.url.path not in ("/admin", "/admin/"):
        flash(request, "Cette page est réservée à l'administrateur.", "warning")
    return RedirectResponse(url="/admin/edt", status_code=303)


@app.get("/", include_in_schema=False)
def accueil():
    return RedirectResponse(url="/admin", status_code=303)


app.include_router(api.router)            # API des boîtiers (token)
app.include_router(auth.router)           # connexion / déconnexion
app.include_router(tableau_de_bord.router)
app.include_router(edt.router)
app.include_router(etudiants.router)
app.include_router(professeurs.router)
app.include_router(configuration.router)
