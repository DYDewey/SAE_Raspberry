"""Remplit une base SQLite JETABLE avec des données fictives, pour les captures des tutoriels.

    venv/Scripts/python outils/demo_tutos.py

Aucune vraie donnée : étudiants de etudiants_fictifs.xlsx, profs et cartes inventés.
Les badges passent par la vraie API des boîtiers (/api/v1/sync) : présences et retards
sont donc calculés exactement comme en production.
"""
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
BASE_DEMO = RACINE / "demo_tutos.db"
# Toujours AVANT d'importer l'application : on ne touche jamais à la vraie base
os.environ["DATABASE_URL"] = f"sqlite:///{BASE_DEMO.as_posix()}"
os.environ["ICAL_URL"] = ""          # pas de téléchargement d'ADE qui écraserait la démo
os.chdir(RACINE)
sys.path.insert(0, str(RACINE))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import models  # noqa: E402
from database import SessionLocal, engine  # noqa: E402
from services.comptes import hacher  # noqa: E402
from services.etudiants import importer_etudiants  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
COMPTE_PROF = ("pmartin", "demo-prof")     # utilisé par outils/tutos.py pour les captures enseignant
random.seed(2026)                          # mêmes données à chaque lancement

PROFS = [("Martin", "Paul"), ("Durand", "Anne"), ("Lefèvre", "Sophie"), ("Benali", "Karim")]
SALLES = ["A101", "A102", "B201", "Amphi A"]
COURS = [("R1.01", "Initiation au développement"), ("R1.02", "Développement web"),
         ("R1.03", "Architecture des ordinateurs"), ("R1.04", "Systèmes d'exploitation"),
         ("R1.10", "Anglais"), ("R1.06", "Mathématiques discrètes")]
CRENEAUX = [(8, 0, 10, 0), (10, 15, 12, 15), (13, 30, 15, 30), (15, 45, 17, 45)]
GROUPES_COURS = ["BUT1-TD1", "BUT1-TD2"]


def lundi(d: date) -> date:
    return d - timedelta(days=d.weekday())


def creer_referentiel(db):
    profs = [models.ProfesseurDB(nom=n, prenom=p) for n, p in PROFS]
    profs[0].identifiant, profs[0].mot_de_passe = COMPTE_PROF[0], hacher(COMPTE_PROF[1])
    salles = [models.SalleDB(nom_salle=s) for s in SALLES]
    cours = [models.EnseignementDB(code_cours=c, libelle=l) for c, l in COURS]
    db.add_all(profs + salles + cours)
    db.flush()
    boitiers = [models.BoitierDB(device_id=f"RPI-00{i + 1}", token=f"demo-{i + 1}", id_prof=p.id, id_salle=salles[i].id)
                for i, p in enumerate(profs)]
    boitiers.append(models.BoitierDB(device_id="RPI-ACCUEIL", token="demo-accueil", accueil=True))
    db.add_all(boitiers)
    db.commit()
    return profs, salles, cours, boitiers


def creer_seances(db, profs, salles, cours):
    """4 semaines (3 passées + la semaine en cours), 4 créneaux par jour pour TD1 et TD2."""
    groupes = {g.nom_groupe: g for g in db.query(models.GroupeDB).all()}
    debut = lundi(date.today()) - timedelta(weeks=3)
    seances = []
    for jour in range(4 * 7):
        d = debut + timedelta(days=jour)
        if d.weekday() >= 5:
            continue
        for i_creneau, (h1, m1, h2, m2) in enumerate(CRENEAUX):
            if d.weekday() == 2 and i_creneau >= 2:          # mercredi après-midi libre
                continue
            for i_groupe, nom in enumerate(GROUPES_COURS):
                k = (jour + i_creneau + i_groupe) % len(profs)
                seances.append(models.SeanceDB(
                    id_enseignement=cours[(jour + i_creneau * 2 + i_groupe) % len(cours)].id,
                    id_groupe=groupes[nom].id, id_salle=salles[k].id, id_prof=profs[k].id,
                    date_debut=datetime(d.year, d.month, d.day, h1, m1),
                    date_fin=datetime(d.year, d.month, d.day, h2, m2)))
    db.add_all(seances)
    db.commit()
    return seances


def badges(db, seances, boitiers):
    """Badges réalistes : la plupart à l'heure, quelques retards, quelques absents réguliers."""
    maintenant = datetime.now()
    tokens = {b.id_prof: (b.device_id, b.token) for b in boitiers if b.id_prof}
    absentéistes = set()
    envois = {}
    for s in seances:
        if s.date_debut > maintenant:
            continue
        # 1 cours sur 40 : le prof a oublié son boîtier (« personne n'a badgé »)
        if s.id % 40 == 7:
            continue
        etudiants = [e for e in db.get(models.GroupeDB, s.id_groupe).etudiants if e.carte]
        if not absentéistes:
            absentéistes = {e.id for e in random.sample(etudiants, 3)}
        for e in etudiants:
            tirage = random.random()
            seuil_absent = 0.35 if e.id in absentéistes else 0.05
            if tirage < seuil_absent:
                continue
            if tirage < seuil_absent + 0.07:
                heure = s.date_debut + timedelta(minutes=random.randint(17, 45))      # retard
            else:
                heure = s.date_debut + timedelta(minutes=random.randint(-12, 9))      # à l'heure
            if heure > maintenant:
                continue
            utc = heure.replace(tzinfo=PARIS).astimezone(timezone.utc)
            envois.setdefault(tokens[s.id_prof], []).append(
                {"uuid": str(uuid.uuid4()), "nfc_uid": e.carte.nfc_uid, "timestamp": utc.strftime("%Y-%m-%dT%H:%M:%SZ")})
    client = TestClient(main.app)
    total = 0
    for (device, token), batch in envois.items():
        for i in range(0, len(batch), 200):
            r = client.post("/api/v1/sync", headers={"Authorization": f"Bearer {token}"},
                            json={"device_id": device, "batch": batch[i:i + 200]})
            r.raise_for_status()
            total += len(r.json()["synced_uuids"])
    # Un boîtier hors ligne depuis hier, pour l'exemple du tableau de bord
    hors_ligne = db.query(models.BoitierDB).filter_by(device_id="RPI-004").first()
    hors_ligne.derniere_synchro = maintenant - timedelta(days=1)
    accueil = db.query(models.BoitierDB).filter_by(device_id="RPI-ACCUEIL").first()
    accueil.derniere_synchro = maintenant                     # boîtier d'accueil en ligne
    db.commit()
    return total, absentéistes


def main_demo():
    # Le fichier est déjà ouvert par l'application importée : on vide les tables
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    models.migrer_schema(engine)
    db = SessionLocal()
    try:
        resultat = importer_etudiants(db, (RACINE / "etudiants_fictifs.xlsx").read_bytes())
        etudiants = db.query(models.EtudiantDB).order_by(models.EtudiantDB.id).all()
        for i, e in enumerate(etudiants):
            if i % 25 != 3:                      # quelques étudiants sans carte (filtre « Sans carte »)
                db.add(models.CarteDB(nfc_uid=f"{random.getrandbits(32):08X}", id_etudiant=e.id))
        db.commit()
        profs, salles, cours, boitiers = creer_referentiel(db)
        seances = creer_seances(db, profs, salles, cours)
        nb, absentéistes = badges(db, seances, boitiers)
        # Un justificatif pour un des absents réguliers
        e = db.get(models.EtudiantDB, sorted(absentéistes)[0])
        db.add(models.JustificatifDB(id_etudiant=e.id, debut=lundi(date.today()) - timedelta(weeks=2),
                                     fin=lundi(date.today()) - timedelta(weeks=2) + timedelta(days=2),
                                     motif="Certificat médical", cree_le=datetime.now()))
        db.commit()
        print(f"Base de démo : {BASE_DEMO}")
        print(f"  {resultat['ajoutes']} étudiants fictifs, {len(seances)} séances, {nb} badges")
        print(f"  compte prof : {COMPTE_PROF[0]} / {COMPTE_PROF[1]}")
    finally:
        db.close()


if __name__ == "__main__":
    main_demo()
