"""Gestion des dates et des identifiants de carte.

Convention : toutes les dates stockées en base (séances ET pointages) sont en
heure locale de Paris, sans fuseau. Le boîtier envoie de l'UTC, l'iCal aussi :
la conversion est faite ici, à l'entrée des données.
"""
import re
from datetime import datetime, date, timedelta, timezone

from config import PARIS

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def maintenant_paris() -> datetime:
    """Heure actuelle à Paris, sans fuseau (même convention que la base)."""
    return datetime.now(PARIS).replace(tzinfo=None)


def vers_heure_paris(valeur, naive_est_utc=True) -> datetime:
    """Convertit une date (texte ISO 8601 ou datetime) en heure de Paris sans fuseau.
    - Date avec fuseau (ex: 2026-10-07T11:20:00Z) : convertie en heure de Paris.
    - Date sans fuseau : considérée comme UTC si naive_est_utc (cas du boîtier),
      sinon comme déjà en heure de Paris."""
    if isinstance(valeur, str):
        valeur = datetime.fromisoformat(valeur.strip().replace("Z", "+00:00"))
    if valeur.tzinfo is None:
        if not naive_est_utc:
            return valeur
        valeur = valeur.replace(tzinfo=timezone.utc)
    return valeur.astimezone(PARIS).replace(tzinfo=None)


def debut_semaine(jour) -> datetime:
    """Lundi 00h00 de la semaine contenant `jour`."""
    if isinstance(jour, datetime):
        jour = jour.date()
    lundi = jour - timedelta(days=jour.weekday())
    return datetime(lundi.year, lundi.month, lundi.day)


def debut_annee_universitaire(jour: datetime = None) -> datetime:
    """1er septembre de l'année universitaire en cours."""
    jour = jour or maintenant_paris()
    annee = jour.year if jour.month >= 9 else jour.year - 1
    return datetime(annee, 9, 1)


def lire_date(texte, defaut=None):
    """'2026-10-07' -> datetime, ou `defaut` si vide/invalide."""
    try:
        return datetime.strptime(texte, "%Y-%m-%d") if texte else defaut
    except (TypeError, ValueError):
        return defaut


def jour_fr(d, avec_annee=False) -> str:
    """datetime -> 'Mercredi 7 octobre' (ou '... 2026')."""
    texte = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return f"{texte} {d.year}" if avec_annee else texte


def normaliser_uid(uid) -> str:
    """Format unique des UID NFC : hexadécimal majuscule sans séparateur.
    '10:d6:5d:56' -> '10D65D56'. Évite qu'une carte enrôlée ne corresponde
    jamais aux pointages à cause d'un espace ou de minuscules."""
    if uid is None:
        return ""
    return re.sub(r"[^0-9A-Fa-f]", "", str(uid)).upper()
