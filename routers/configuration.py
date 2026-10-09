"""Configuration : boîtiers, salles, groupes, purge RGPD."""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

import config
import models
from database import get_db
from services import fin_annee
from services.presences import rattacher_pointages
from services.temps import lire_date, maintenant_paris
from web import admin_requis, flash, groupes_par_promo, render

router = APIRouter(prefix="/admin/configuration", dependencies=[Depends(admin_requis)], tags=["Configuration"])

RETOUR = "/admin/configuration"


def _id_ou_none(valeur):
    try:
        return int(valeur) if valeur not in (None, "", "0") else None
    except ValueError:
        return None


@router.get("")
def page_configuration(request: Request, db: Session = Depends(get_db)):
    maintenant = maintenant_paris()
    groupes = db.query(models.GroupeDB).order_by(models.GroupeDB.nom_groupe).all()
    effectifs = dict(db.query(models.etudiant_groupe_association.c.groupe_id, func.count())
                     .group_by(models.etudiant_groupe_association.c.groupe_id).all())
    return render(
        request, "configuration.html", actif="configuration",
        boitiers=db.query(models.BoitierDB).order_by(models.BoitierDB.device_id).all(),
        en_ligne_depuis=maintenant - timedelta(minutes=config.BOITIER_EN_LIGNE_MIN),
        professeurs=db.query(models.ProfesseurDB).filter(models.ProfesseurDB.nom != "N/A")
            .order_by(models.ProfesseurDB.nom).all(),
        salles=db.query(models.SalleDB).order_by(models.SalleDB.nom_salle).all(),
        groupes=groupes_par_promo(groupes),
        effectifs=effectifs,
        nb_pointages=db.query(models.PointageDB).count(),
        promos=fin_annee.effectifs_promos(db),
        config=config,
    )


# ==========================================
# Boîtiers
# ==========================================

@router.post("/boitiers/ajouter")
def ajouter_boitier(request: Request, device_id: str = Form(...), id_prof: str = Form(""),
                    id_salle: str = Form(""), mode_sae: str = Form(""), accueil: str = Form(""),
                    db: Session = Depends(get_db)):
    device_id = device_id.strip()[:32]
    if db.get(models.BoitierDB, device_id):
        flash(request, f"Le boîtier {device_id} existe déjà.", "warning")
    elif device_id:
        db.add(models.BoitierDB(device_id=device_id, token=secrets.token_hex(16),
                                id_prof=_id_ou_none(id_prof), id_salle=_id_ou_none(id_salle),
                                mode_sae=bool(mode_sae), accueil=bool(accueil)))
        db.commit()
        flash(request, f"Boîtier {device_id} créé. Recopiez son token dans le fichier .env du Raspberry Pi.")
    return RedirectResponse(url=RETOUR + "#boitiers", status_code=303)


@router.post("/boitiers/{device_id}/modifier")
def modifier_boitier(device_id: str, request: Request, id_prof: str = Form(""), id_salle: str = Form(""),
                     mode_sae: str = Form(""), accueil: str = Form(""), db: Session = Depends(get_db)):
    boitier = db.get(models.BoitierDB, device_id)
    if boitier:
        boitier.id_prof, boitier.id_salle = _id_ou_none(id_prof), _id_ou_none(id_salle)
        boitier.mode_sae = bool(mode_sae)
        boitier.accueil = bool(accueil)
        db.commit()
        # Le boîtier a changé de prof/salle : on recalcule ses pointages récents
        fin = maintenant_paris() + timedelta(days=1)
        rattacher_pointages(db, fin - timedelta(days=8), fin)
        flash(request, f"Boîtier {device_id} mis à jour.")
    return RedirectResponse(url=RETOUR + "#boitiers", status_code=303)


@router.post("/boitiers/{device_id}/nouveau-token")
def nouveau_token(device_id: str, request: Request, db: Session = Depends(get_db)):
    boitier = db.get(models.BoitierDB, device_id)
    if boitier:
        boitier.token = secrets.token_hex(16)
        db.commit()
        flash(request, f"Nouveau token généré pour {device_id}. L'ancien ne fonctionne plus.", "warning")
    return RedirectResponse(url=RETOUR + "#boitiers", status_code=303)


@router.post("/boitiers/{device_id}/supprimer")
def supprimer_boitier(device_id: str, request: Request, db: Session = Depends(get_db)):
    boitier = db.get(models.BoitierDB, device_id)
    if boitier:
        db.delete(boitier)
        db.commit()
        flash(request, f"Boîtier {device_id} supprimé.", "info")
    return RedirectResponse(url=RETOUR + "#boitiers", status_code=303)


# ==========================================
# Salles
# ==========================================

@router.post("/salles/ajouter")
def ajouter_salle(request: Request, nom_salle: str = Form(...), db: Session = Depends(get_db)):
    nom = nom_salle.strip()[:32]
    if db.query(models.SalleDB).filter_by(nom_salle=nom).first():
        flash(request, f"La salle {nom} existe déjà.", "warning")
    elif nom:
        db.add(models.SalleDB(nom_salle=nom))
        db.commit()
        flash(request, f"Salle {nom} ajoutée.")
    return RedirectResponse(url=RETOUR + "#salles", status_code=303)


@router.post("/salles/{salle_id}/modifier")
def modifier_salle(salle_id: int, request: Request, nom_salle: str = Form(...), db: Session = Depends(get_db)):
    salle, nom = db.get(models.SalleDB, salle_id), nom_salle.strip()[:32]
    if db.query(models.SalleDB).filter(models.SalleDB.nom_salle == nom, models.SalleDB.id != salle_id).first():
        flash(request, f"La salle {nom} existe déjà.", "warning")
    elif salle and nom:
        salle.nom_salle = nom
        db.commit()
        flash(request, f"Salle renommée en {nom}.")
    return RedirectResponse(url=RETOUR + "#salles", status_code=303)


@router.post("/salles/{salle_id}/supprimer")
def supprimer_salle(salle_id: int, request: Request, db: Session = Depends(get_db)):
    salle = db.get(models.SalleDB, salle_id)
    if salle:
        # Les cours référencent la salle : sans ça PostgreSQL refuse la suppression
        db.query(models.SeanceDB).filter(models.SeanceDB.id_salle == salle_id).delete()
        db.query(models.BoitierDB).filter(models.BoitierDB.id_salle == salle_id).update({"id_salle": None})
        flash(request, f"Salle {salle.nom_salle} supprimée.", "info")
        db.delete(salle)
        db.commit()
    return RedirectResponse(url=RETOUR + "#salles", status_code=303)


# ==========================================
# Groupes
# ==========================================

@router.post("/groupes/ajouter")
def ajouter_groupe(request: Request, nom_groupe: str = Form(...), db: Session = Depends(get_db)):
    nom = nom_groupe.strip()[:16]
    if db.query(models.GroupeDB).filter_by(nom_groupe=nom).first():
        flash(request, f"Le groupe {nom} existe déjà.", "warning")
    elif nom:
        db.add(models.GroupeDB(nom_groupe=nom))
        db.commit()
        flash(request, f"Groupe {nom} ajouté.")
    return RedirectResponse(url=RETOUR + "#groupes", status_code=303)


@router.post("/groupes/{groupe_id}/modifier")
def modifier_groupe(groupe_id: int, request: Request, nom_groupe: str = Form(...), db: Session = Depends(get_db)):
    groupe, nom = db.get(models.GroupeDB, groupe_id), nom_groupe.strip()[:16]
    if db.query(models.GroupeDB).filter(models.GroupeDB.nom_groupe == nom, models.GroupeDB.id != groupe_id).first():
        flash(request, f"Le groupe {nom} existe déjà.", "warning")
    elif groupe and nom:
        groupe.nom_groupe = nom
        db.commit()
        flash(request, f"Groupe renommé en {nom}.")
    return RedirectResponse(url=RETOUR + "#groupes", status_code=303)


@router.post("/groupes/{groupe_id}/supprimer")
def supprimer_groupe(groupe_id: int, request: Request, db: Session = Depends(get_db)):
    groupe = db.get(models.GroupeDB, groupe_id)
    if groupe:
        db.query(models.SeanceDB).filter(models.SeanceDB.id_groupe == groupe_id).delete()
        flash(request, f"Groupe {groupe.nom_groupe} supprimé (les étudiants sont conservés).", "info")
        db.delete(groupe)
        db.commit()
    return RedirectResponse(url=RETOUR + "#groupes", status_code=303)


# ==========================================
# RGPD
# ==========================================

@router.post("/rgpd/purge")
def purge_rgpd(request: Request, avant: str = Form(...), db: Session = Depends(get_db)):
    """Fin d'année universitaire : supprime les pointages antérieurs à la date choisie."""
    limite = lire_date(avant)
    if limite:
        nb = db.query(models.PointageDB).filter(models.PointageDB.timestamp < limite).delete()
        anciennes = [s for (s,) in db.query(models.SeanceDB.id).filter(models.SeanceDB.date_debut < limite)]
        if anciennes:
            db.query(models.PresenceManuelleDB).filter(models.PresenceManuelleDB.id_seance.in_(anciennes)) \
                .delete(synchronize_session=False)
        db.commit()
        flash(request, f"{nb} pointage(s) antérieur(s) au {limite:%d/%m/%Y} supprimé(s).", "info")
    return RedirectResponse(url=RETOUR + "#rgpd", status_code=303)


# ==========================================
# Fin d'année : départ d'une promo, passage à l'année suivante
# ==========================================

@router.post("/promo/depart")
def depart_promo(request: Request, promo: str = Form(...), action: str = Form(...), db: Session = Depends(get_db)):
    if promo not in fin_annee.PROMOS or action not in ("anonymiser", "supprimer"):
        return RedirectResponse(url=RETOUR + "#fin-annee", status_code=303)
    etudiants = fin_annee.etudiants_de_promo(db, promo)
    if action == "anonymiser":
        nb = fin_annee.anonymiser(db, etudiants)
        flash(request, f"{nb} étudiant(s) de {promo} anonymisé(s) : noms effacés, cartes libérées, "
                       f"pointages conservés sans identité.", "info")
    else:
        nb = fin_annee.supprimer(db, etudiants)
        flash(request, f"{nb} étudiant(s) de {promo} supprimé(s) avec leurs cartes et pointages.", "info")
    return RedirectResponse(url=RETOUR + "#fin-annee", status_code=303)


@router.post("/promo/passage")
def passage_promo(request: Request, depart: str = Form(...), db: Session = Depends(get_db)):
    if depart not in ("BUT1", "BUT2"):
        return RedirectResponse(url=RETOUR + "#fin-annee", status_code=303)
    arrivee = "BUT" + str(int(depart[-1]) + 1)
    nb, erreur = fin_annee.passer_annee(db, depart, arrivee)
    if erreur:
        flash(request, erreur, "warning")
    else:
        flash(request, f"{nb} étudiant(s) passé(s) de {depart} en {arrivee} (mêmes TD/TP).")
    return RedirectResponse(url=RETOUR + "#fin-annee", status_code=303)
