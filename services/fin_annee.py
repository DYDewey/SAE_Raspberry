"""Fin d'année universitaire : départ d'une promo (RGPD) et passage à l'année suivante.

Ordre conseillé en juillet :
  1. BUT3 : anonymiser ou supprimer les étudiants qui partent ;
  2. BUT2 -> BUT3, puis BUT1 -> BUT2 (refusé tant que la promo d'arrivée a encore des étudiants,
     sinon les deux années se mélangeraient) ;
  3. importer la liste des nouveaux BUT1.
"""
from sqlalchemy.orm import Session

import models

PROMOS = ("BUT1", "BUT2", "BUT3")


def dans_promo(nom_groupe: str, promo: str) -> bool:
    return nom_groupe == promo or nom_groupe.startswith(promo + "-")


def etudiants_de_promo(db: Session, promo: str) -> list:
    return [e for e in db.query(models.EtudiantDB).all()
            if any(dans_promo(g.nom_groupe, promo) for g in e.groupes)]


def effectifs_promos(db: Session) -> dict:
    """{'BUT1': 120, 'BUT2': 0, ...} pour l'affichage."""
    etudiants = db.query(models.EtudiantDB).all()
    return {p: sum(1 for e in etudiants if any(dans_promo(g.nom_groupe, p) for g in e.groupes))
            for p in PROMOS}


def _oublier_seances(db: Session, etudiant):
    db.query(models.PresenceManuelleDB).filter_by(id_etudiant=etudiant.id).delete()


def anonymiser(db: Session, etudiants) -> int:
    """Efface l'identité, libère la carte NFC et retire des groupes.
    Les pointages restent (rattachés à un identifiant anonyme) pour les statistiques."""
    for e in etudiants:
        if e.carte:
            ancien, nouveau = e.carte.nfc_uid, f"ANON-{e.id}"
            db.query(models.PointageDB).filter_by(nfc_uid=ancien).update({"nfc_uid": nouveau})
            db.delete(e.carte)
            db.flush()
            db.add(models.CarteDB(nfc_uid=nouveau, id_etudiant=e.id))
        e.nom, e.prenom, e.numero_etudiant = "Anonyme", f"n°{e.id}", f"ANON-{e.id}"
        e.groupes = []
        _oublier_seances(db, e)
    db.commit()
    return len(etudiants)


def supprimer(db: Session, etudiants) -> int:
    """Supprime les étudiants, leur carte, leurs pointages et leurs validations manuelles."""
    for e in etudiants:
        if e.carte:
            db.query(models.PointageDB).filter_by(nfc_uid=e.carte.nfc_uid).delete()
        _oublier_seances(db, e)
        db.delete(e)
    db.commit()
    return len(etudiants)


def passer_annee(db: Session, depart: str, arrivee: str):
    """Déplace les étudiants de `depart` vers `arrivee` en gardant leur TD/TP :
    BUT2-TD1 -> BUT3-TD1 (groupe créé s'il n'existe pas). Retourne (nb, message d'erreur)."""
    restants = len(etudiants_de_promo(db, arrivee))
    if restants:
        return 0, (f"Le {arrivee} a encore {restants} étudiant(s) : "
                   f"anonymisez-les ou supprimez-les d'abord, sinon les deux années seraient mélangées.")
    groupes = {g.nom_groupe: g for g in db.query(models.GroupeDB).all()}

    def cible(nom):
        nouveau = arrivee + nom[len(depart):]
        if nouveau not in groupes:
            groupes[nouveau] = models.GroupeDB(nom_groupe=nouveau)
            db.add(groupes[nouveau])
        return groupes[nouveau]

    etudiants = etudiants_de_promo(db, depart)
    for e in etudiants:
        e.groupes = [cible(g.nom_groupe) if dans_promo(g.nom_groupe, depart) else g for g in e.groupes]
    db.commit()
    return len(etudiants), None
