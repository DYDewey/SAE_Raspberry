"""Import de l'emploi du temps depuis le flux iCal de l'université (ADE)."""
import re
from datetime import datetime, timedelta

import requests
from icalendar import Calendar
from sqlalchemy.orm import Session

import models
from config import ICAL_URL, ICAL_SEMAINES
from services.groupes import parents
from services.presences import rattacher_pointages
from services.temps import debut_semaine, maintenant_paris, vers_heure_paris

REGEX_GROUPE = r'(BUT\d(?:-[A-Z0-9\-]+)?)'


def _get_or_create(db, modele, filtre: dict, valeurs: dict = None):
    obj = db.query(modele).filter_by(**filtre).first()
    if not obj:
        obj = modele(**filtre, **(valeurs or {}))
        db.add(obj)
        db.flush()
    return obj


def extraire_groupes(summary: str, description: str) -> list:
    """Groupes concernés par un cours (BUT3-TD1, BUT2-TPA...).
    ADE met un groupe par ligne dans la description ; un CM en a plusieurs."""
    groupes = []
    for ligne in description.split('\n'):
        trouve = re.fullmatch(REGEX_GROUPE, ligne.strip())
        if trouve and trouve.group(1)[:16] not in groupes:
            groupes.append(trouve.group(1)[:16])
    if not groupes:
        trouve = re.search(REGEX_GROUPE, f"{summary}\n{description}")
        groupes = [trouve.group(1)[:16]] if trouve else ["Groupe Inconnu"]
    return groupes


def extraire_prof(description: str):
    """Première ligne de la description qui ressemble à 'NOM Prénom'."""
    for ligne in description.split('\n'):
        ligne = ligne.strip()
        if not ligne or "Exporté" in ligne or ligne.startswith("("):
            continue
        if any(c.isupper() for c in ligne) and len(ligne) > 3 and "BUT" not in ligne:
            morceaux = ligne.split()
            if len(morceaux) >= 2:
                return morceaux[0][:64], " ".join(morceaux[1:])[:64]
    return "N/A", ""


def telecharger_et_importer(db: Session) -> dict:
    if not ICAL_URL:
        raise ValueError("ICAL_URL n'est pas défini dans le fichier .env")
    reponse = requests.get(ICAL_URL, timeout=30)
    reponse.raise_for_status()
    return importer_ical(db, reponse.content)


def importer_ical(db: Session, contenu: bytes, reference: datetime = None, semaines: int = ICAL_SEMAINES) -> dict:
    """Met à jour les séances de la période (semaine en cours + semaines suivantes).
    Les séances sont mises à jour via l'UID iCal au lieu d'être supprimées et
    recréées : leurs id restent stables et les pointages restent rattachés."""
    cal = Calendar.from_ical(contenu)

    debut_periode = debut_semaine(reference or maintenant_paris())
    fin_periode = debut_periode + timedelta(weeks=semaines)

    uids_vus = set()
    crees = modifies = 0
    for event in cal.walk('vevent'):
        dtstart, dtend = event.get('dtstart').dt, event.get('dtend').dt
        if not (isinstance(dtstart, datetime) and isinstance(dtend, datetime)):
            continue   # événement "journée entière", ignoré

        # Conversion vers l'heure de Paris (gère heure d'été / d'hiver)
        debut = vers_heure_paris(dtstart, naive_est_utc=False)
        fin = vers_heure_paris(dtend, naive_est_utc=False)
        if not (debut_periode <= debut < fin_periode):
            continue

        summary = str(event.get('summary', ''))
        description = str(event.get('description', ''))
        location = str(event.get('location', '')) or 'Salle Inconnue'

        uid_event = str(event.get('uid', '')).strip() or f"{summary}|{debut.isoformat()}|{location}"
        if event.get('recurrence-id'):
            # Occurrence d'un cours récurrent : toutes les occurrences ont le même UID
            uid_event += f"|{event.get('recurrence-id').dt}"

        salle = _get_or_create(db, models.SalleDB, {"nom_salle": location[:32]})
        enseignement = _get_or_create(db, models.EnseignementDB, {"code_cours": summary[:32]}, {"libelle": summary[:128]})
        nom, prenom = extraire_prof(description)
        prof = _get_or_create(db, models.ProfesseurDB, {"nom": nom}, {"prenom": prenom})

        # Un cours partagé par plusieurs groupes (CM) donne une séance par groupe,
        # pour que chaque groupe ait sa propre feuille d'émargement
        noms_groupes = extraire_groupes(summary, description)
        for nom_groupe in noms_groupes:
            for parent in parents(nom_groupe):
                _get_or_create(db, models.GroupeDB, {"nom_groupe": parent})
            groupe = _get_or_create(db, models.GroupeDB, {"nom_groupe": nom_groupe})
            uid = (uid_event if len(noms_groupes) == 1 else f"{uid_event}|{nom_groupe}")[:255]
            uids_vus.add(uid)

            champs = dict(id_enseignement=enseignement.id, id_groupe=groupe.id, id_salle=salle.id,
                          id_prof=prof.id, date_debut=debut, date_fin=fin)
            seance = db.query(models.SeanceDB).filter(models.SeanceDB.uid_ical == uid).first()
            if seance:
                for cle, valeur in champs.items():
                    setattr(seance, cle, valeur)
                modifies += 1
            else:
                db.add(models.SeanceDB(uid_ical=uid, **champs))
                crees += 1
            db.flush()

    # Séances à venir qui ont disparu de l'EDT (cours annulé ou déplacé).
    # Les cours déjà passés ne sont jamais supprimés : le flux de l'université ne
    # contient que les cours à partir d'aujourd'hui, et ils portent les présences.
    supprimes = 0
    for s in db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut >= max(debut_periode, reference or maintenant_paris()),
        models.SeanceDB.date_debut < fin_periode,
    ).all():
        if s.uid_ical not in uids_vus:
            db.delete(s)
            supprimes += 1
    db.commit()

    # Les séances ont pu bouger : on recalcule le rattachement des pointages
    rattacher_pointages(db, debut_periode, fin_periode)
    return {"crees": crees, "modifies": modifies, "supprimes": supprimes}
