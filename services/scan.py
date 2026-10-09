"""Enrôlement d'une carte en la passant sur un boîtier (bouton "Scanner").

Fonctionnement :
1. l'admin choisit le boîtier d'enrôlement (idéalement un boîtier posé au
   secrétariat, sans professeur) et clique sur "Scanner" pour un étudiant ;
2. l'étudiant passe sa carte sur CE boîtier : le boîtier envoie le bip au serveur
   comme d'habitude (en moins d'une seconde) ;
3. la page interroge le serveur chaque seconde : dès qu'un bip de ce boîtier est
   reçu après le clic, sa carte est associée à l'étudiant. Ce bip d'enrôlement
   n'est pas un pointage de présence : il est supprimé.

Sécurités :
- seuls les bips du boîtier choisi comptent : un étudiant qui badge en cours sur
  un autre boîtier au même moment n'est jamais pris par erreur ;
- si la carte appartient déjà à un autre étudiant, rien n'est modifié sans
  confirmation de l'admin (statut "conflit").

Une seule attente à la fois (un seul poste d'enrôlement), gardée en mémoire.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

import models
from services.etudiants import associer_carte
from services.temps import maintenant_paris

DUREE_ATTENTE_S = 60

_attente = None   # {"etudiant_id": int | None, "device_id": str, "depuis": datetime}


def demarrer(device_id: str, etudiant_id=None):
    """etudiant_id=None : on veut seulement lire l'UID (formulaire d'ajout)."""
    global _attente
    _attente = {"etudiant_id": etudiant_id, "device_id": device_id, "depuis": maintenant_paris()}
    return _attente


def en_attente(device_id: str) -> bool:
    """Un scan attend-il en ce moment un bip de ce boîtier ?"""
    return bool(_attente and _attente["device_id"] == device_id
                and (maintenant_paris() - _attente["depuis"]).total_seconds() < DUREE_ATTENTE_S)


def annuler():
    global _attente
    _attente = None


def verifier(db: Session) -> dict:
    """État de l'attente : 'aucun', 'attente', 'expire', 'trouve' ou 'conflit'."""
    global _attente
    if not _attente:
        return {"statut": "aucun"}

    maintenant = maintenant_paris()
    restant = DUREE_ATTENTE_S - (maintenant - _attente["depuis"]).total_seconds()

    # Premier bip du boîtier choisi reçu après le clic. On écarte aussi les vieux
    # bips stockés hors ligne qui arriveraient à ce moment-là.
    pointage = db.query(models.PointageDB).filter(
        models.PointageDB.device_id == _attente["device_id"],
        models.PointageDB.recu_le >= _attente["depuis"],
        models.PointageDB.timestamp >= _attente["depuis"] - timedelta(minutes=2),
    ).order_by(models.PointageDB.recu_le, models.PointageDB.timestamp).first()

    if not pointage:
        if restant <= 0:
            _attente = None
            return {"statut": "expire"}
        return {"statut": "attente", "restant": int(restant), "alerte": _alerte(db)}

    uid = pointage.nfc_uid
    db.delete(pointage)          # bip d'enrôlement : pas une présence
    db.commit()
    etudiant_id = _attente["etudiant_id"]
    _attente = None

    carte = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == uid).first()
    proprietaire = carte.etudiant if carte else None

    if proprietaire and proprietaire.id != etudiant_id:
        # Carte déjà attribuée à quelqu'un d'autre : l'admin doit confirmer
        return {"statut": "conflit", "uid": uid,
                "proprietaire": f"{proprietaire.prenom} {proprietaire.nom}"}

    message = ""
    if etudiant_id:
        etudiant = db.get(models.EtudiantDB, etudiant_id)
        if etudiant:
            message = associer_carte(db, etudiant, uid) or f"Cette carte est déjà celle de {etudiant.prenom} {etudiant.nom}."
    return {"statut": "trouve", "uid": uid, "message": message}


def _alerte(db: Session) -> str:
    """Explique pourquoi une carte passée pendant l'attente n'a pas été prise en compte."""
    depuis, boitier = _attente["depuis"], _attente["device_id"]
    recus = db.query(models.PointageDB).filter(models.PointageDB.recu_le >= depuis) \
        .order_by(models.PointageDB.recu_le.desc()).limit(20).all()

    # Bip du bon boîtier, mais horodaté trop tôt : horloge du Raspberry décalée
    for p in recus:
        if p.device_id == boitier:
            ecart = round((depuis - p.timestamp).total_seconds() / 60)
            return (f"Une carte a bien été reçue de {boitier}, mais l'horloge du Raspberry est décalée "
                    f"d'environ {ecart} min. Vérifiez la date sur le Pi (commande date).")
    # Bip d'un autre boîtier : mauvais boîtier choisi dans la liste
    autres = sorted({p.device_id for p in recus})
    if autres:
        return (f"Une carte a été passée sur {', '.join(autres)}, pas sur {boitier}. "
                f"Choisissez le bon boîtier dans la liste en haut.")
    return ""
