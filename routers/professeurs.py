"""Professeurs."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

import config
import models
from database import get_db
from services.comptes import hacher
from web import admin_requis, flash, render

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_requis)], tags=["Professeurs"])


@router.get("/professeurs")
def liste_professeurs(request: Request, db: Session = Depends(get_db)):
    professeurs = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.nom != "N/A") \
        .order_by(models.ProfesseurDB.nom, models.ProfesseurDB.prenom).all()
    nb_cours = dict(db.query(models.SeanceDB.id_prof, func.count(models.SeanceDB.id))
                    .group_by(models.SeanceDB.id_prof).all())
    boitiers = {}
    for b in db.query(models.BoitierDB).filter(models.BoitierDB.id_prof.isnot(None)).all():
        boitiers.setdefault(b.id_prof, []).append(b.device_id)
    return render(request, "professeurs.html", actif="professeurs", professeurs=professeurs,
                  nb_cours=nb_cours, boitiers=boitiers)


@router.post("/professeurs/ajouter")
def ajouter_professeur(request: Request, nom: str = Form(...), prenom: str = Form(...),
                       db: Session = Depends(get_db)):
    nom, prenom = nom.strip()[:64], prenom.strip()[:64]
    if db.query(models.ProfesseurDB).filter_by(nom=nom, prenom=prenom).first():
        flash(request, f"{prenom} {nom} existe déjà.", "warning")
    else:
        db.add(models.ProfesseurDB(nom=nom, prenom=prenom))
        db.commit()
        flash(request, f"{prenom} {nom} a été ajouté(e).")
    return RedirectResponse(url="/admin/professeurs", status_code=303)


@router.post("/professeurs/{prof_id}/compte")
def definir_compte(prof_id: int, request: Request, identifiant: str = Form(...), mot_de_passe: str = Form(""),
                   db: Session = Depends(get_db)):
    """Crée ou modifie le compte de connexion d'un prof (mot de passe vide : inchangé)."""
    prof = db.get(models.ProfesseurDB, prof_id)
    identifiant = identifiant.strip()[:64]
    if not prof:
        return RedirectResponse(url="/admin/professeurs", status_code=303)
    autre = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.identifiant == identifiant,
                                                 models.ProfesseurDB.id != prof_id).first()
    if not identifiant or identifiant == config.ADMIN_USER or autre:
        flash(request, f"L'identifiant « {identifiant} » est vide ou déjà utilisé.", "danger")
    elif not prof.mot_de_passe and len(mot_de_passe) < 6:
        flash(request, "Choisissez un mot de passe d'au moins 6 caractères.", "danger")
    elif mot_de_passe and len(mot_de_passe) < 6:
        flash(request, "Le mot de passe doit faire au moins 6 caractères.", "danger")
    else:
        prof.identifiant = identifiant
        if mot_de_passe:
            prof.mot_de_passe = hacher(mot_de_passe)
        db.commit()
        flash(request, f"Compte de {prof.prenom} {prof.nom} enregistré : identifiant « {identifiant} ».")
    return RedirectResponse(url="/admin/professeurs", status_code=303)


@router.post("/professeurs/{prof_id}/compte/supprimer")
def supprimer_compte(prof_id: int, request: Request, db: Session = Depends(get_db)):
    prof = db.get(models.ProfesseurDB, prof_id)
    if prof:
        prof.identifiant = prof.mot_de_passe = None
        db.commit()
        flash(request, f"{prof.prenom} {prof.nom} ne peut plus se connecter.", "info")
    return RedirectResponse(url="/admin/professeurs", status_code=303)


@router.post("/professeurs/{prof_id}/supprimer")
def supprimer_professeur(prof_id: int, request: Request, db: Session = Depends(get_db)):
    prof = db.get(models.ProfesseurDB, prof_id)
    if prof:
        db.query(models.SeanceDB).filter(models.SeanceDB.id_prof == prof_id).delete()
        db.query(models.BoitierDB).filter(models.BoitierDB.id_prof == prof_id).update({"id_prof": None})
        flash(request, f"{prof.prenom} {prof.nom} et ses cours ont été supprimés.", "info")
        db.delete(prof)
        db.commit()
    return RedirectResponse(url="/admin/professeurs", status_code=303)
