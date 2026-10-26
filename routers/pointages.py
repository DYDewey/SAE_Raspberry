"""Pointages : liste des bips reçus, avec filtres combinables."""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, extract, or_
from sqlalchemy.orm import Session

import models
from database import get_db
from services.presences import etudiants_du_groupe
from services.temps import lire_date, maintenant_paris, normaliser_uid
from web import admin_requis, groupes_par_promo, render

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_requis)], tags=["Pointages"])

LIMITE = 500   # au-delà, la page devient lourde : on demande d'affiner les filtres


def _minutes(texte: str):
    """'08:30' (ou '08:30:00') -> 510 minutes depuis minuit, ou None si vide/invalide."""
    try:
        h, m = texte.split(":")[:2]
        return int(h) * 60 + int(m) if 0 <= int(h) < 24 and 0 <= int(m) < 60 else None
    except (AttributeError, ValueError):
        return None


def filtrer_pointages(db: Session, debut, fin, q="", groupe=0, enseignement=0, salle=0, de="", a=""):
    """Requête des bips (avec étudiant, séance et boîtier) qui passent tous les filtres.
    Période : debut inclus, fin exclue."""
    P, S, B = models.PointageDB, models.SeanceDB, models.BoitierDB
    requete = db.query(P, models.EtudiantDB, S, B) \
        .outerjoin(models.CarteDB, models.CarteDB.nfc_uid == P.nfc_uid) \
        .outerjoin(models.EtudiantDB, models.EtudiantDB.id == models.CarteDB.id_etudiant) \
        .outerjoin(S, S.id == P.id_seance) \
        .outerjoin(B, B.device_id == P.device_id) \
        .filter(P.timestamp >= debut, P.timestamp < fin)

    if q.strip():
        motif = f"%{q.strip()}%"
        conditions = [models.EtudiantDB.nom.ilike(motif), models.EtudiantDB.prenom.ilike(motif),
                      models.EtudiantDB.numero_etudiant.ilike(motif)]
        # Ça ressemble à un UID ('aa:00:00:01') : on le cherche au format stocké ('AA000001')
        if re.fullmatch(r"[0-9A-Fa-f:\s-]+", q.strip()):
            conditions.append(P.nfc_uid.like(f"%{normaliser_uid(q)}%"))
        requete = requete.filter(or_(*conditions))
    if groupe:
        # Mêmes étudiants que sur l'émargement d'un cours de ce groupe (TD3 inclut TD3-PA et TD3-PB)
        ids = [e.id for e in etudiants_du_groupe(db, groupe)]
        requete = requete.filter(models.EtudiantDB.id.in_(ids))
    if enseignement:
        requete = requete.filter(S.id_enseignement == enseignement)
    if salle:
        # Salle du cours ; pour un bip hors cours, salle du boîtier
        requete = requete.filter(or_(S.id_salle == salle, and_(S.id.is_(None), B.id_salle == salle)))
    minute_du_bip = extract("hour", P.timestamp) * 60 + extract("minute", P.timestamp)
    if _minutes(de) is not None:
        requete = requete.filter(minute_du_bip >= _minutes(de))
    if _minutes(a) is not None:
        requete = requete.filter(minute_du_bip <= _minutes(a))
    return requete


@router.get("/pointages")
def liste_pointages(request: Request, q: str = "", groupe: int = 0, enseignement: int = 0, salle: int = 0,
                    du: str = "", au: str = "", de: str = "", a: str = "", db: Session = Depends(get_db)):
    aujourd_hui = maintenant_paris().replace(hour=0, minute=0, second=0, microsecond=0)
    debut = lire_date(du, aujourd_hui - timedelta(days=6))
    dernier_jour = lire_date(au, aujourd_hui)
    if debut > dernier_jour:   # dates saisies à l'envers
        debut, dernier_jour = dernier_jour, debut
    requete = filtrer_pointages(db, debut, dernier_jour + timedelta(days=1), q, groupe, enseignement, salle, de, a)

    total = requete.count()
    lignes = requete.order_by(models.PointageDB.timestamp.desc()).limit(LIMITE).all()

    enseignements = db.query(models.EnseignementDB).order_by(models.EnseignementDB.code_cours).all()
    salles = db.query(models.SalleDB).order_by(models.SalleDB.nom_salle).all()
    groupes = db.query(models.GroupeDB).order_by(models.GroupeDB.nom_groupe).all()
    return render(request, "pointages.html", actif="pointages", lignes=lignes, total=total, limite=LIMITE,
                  q=q, groupe_choisi=groupe, enseignement=enseignement, salle=salle,
                  du=debut.strftime("%Y-%m-%d"), au=dernier_jour.strftime("%Y-%m-%d"), de=de, a=a,
                  groupes=groupes_par_promo(groupes), enseignements=enseignements, salles=salles,
                  noms_ens={e.id: e for e in enseignements}, noms_salles={s.id: s.nom_salle for s in salles},
                  noms_groupes={g.id: g.nom_groupe for g in groupes})
