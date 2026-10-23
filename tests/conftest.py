"""Outils communs aux tests.

Les tests tournent sur une base SQLite jetable (jamais sur PostgreSQL) :
DATABASE_URL est fixée AVANT d'importer l'application.
Lancer : venv/Scripts/python -m pytest
"""
import importlib.util
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASE_TEST = Path(tempfile.gettempdir()) / "sae_pointage_tests.db"
os.environ["DATABASE_URL"] = f"sqlite:///{BASE_TEST.as_posix()}"
os.environ["BOITIER_ENV"] = str(BASE_TEST.with_suffix(".env-absent"))   # pas le vrai .env du boîtier
sys.path.insert(0, str(RACINE))

import pytest
from fastapi.testclient import TestClient

import main
import models
from database import SessionLocal, engine
from routers import api


def _charger_module_boitier(nom):
    """Le boîtier a son propre config.py : on le charge sans écraser celui du serveur."""
    config_serveur = sys.modules["config"]
    try:
        spec = importlib.util.spec_from_file_location("boitier_config", RACINE / "boitier" / "config.py")
        config_boitier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_boitier)
        sys.modules["config"] = config_boitier
        spec = importlib.util.spec_from_file_location(f"boitier_{nom}", RACINE / "boitier" / f"{nom}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules["config"] = config_serveur


stockage = _charger_module_boitier("stockage")
synchro = _charger_module_boitier("synchro")

# Lundi 12 octobre 2026, cours de 8h à 10h (heure de Paris = UTC+2 en octobre)
DEBUT = datetime(2026, 10, 12, 8, 0)
FIN = datetime(2026, 10, 12, 10, 0)


def utc(heure, minute=0):
    """Heure de Paris du 12/10/2026 -> texte ISO UTC, comme l'envoie le boîtier."""
    return f"2026-10-12T{heure - 2:02d}:{minute:02d}:00Z"


@pytest.fixture(autouse=True)
def base_vide(monkeypatch):
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    # Pas de téléchargement de l'emploi du temps pendant les tests
    monkeypatch.setattr(api.ical, "synchroniser_en_fond", lambda raison: None)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def iut(db):
    """Un TD de 3 étudiants avec carte, 2 profs avec chacun son boîtier et un cours."""
    td1 = models.GroupeDB(nom_groupe="BUT1-TD1")
    td2 = models.GroupeDB(nom_groupe="BUT1-TD2")
    salle1, salle2 = models.SalleDB(nom_salle="A101"), models.SalleDB(nom_salle="A102")
    r101 = models.EnseignementDB(code_cours="R1.01", libelle="Initiation au développement")
    r102 = models.EnseignementDB(code_cours="R1.02", libelle="Développement web")
    prof1 = models.ProfesseurDB(nom="Martin", prenom="Paul")
    prof2 = models.ProfesseurDB(nom="Durand", prenom="Anne")
    db.add_all([td1, td2, salle1, salle2, r101, r102, prof1, prof2])
    db.flush()

    etudiants = []
    for i, nom in enumerate(["Alpha", "Bravo", "Charlie"], start=1):
        e = models.EtudiantDB(numero_etudiant=f"2026000{i}", nom=nom, prenom="Test", groupes=[td1])
        e.carte = models.CarteDB(nfc_uid=f"AA00000{i}")
        etudiants.append(e)
    autre = models.EtudiantDB(numero_etudiant="20260009", nom="Delta", prenom="Test", groupes=[td2])
    autre.carte = models.CarteDB(nfc_uid="BB000009")
    db.add_all(etudiants + [autre])

    db.add_all([
        models.BoitierDB(device_id="RPI-001", token="jeton-1", id_prof=prof1.id),
        models.BoitierDB(device_id="RPI-002", token="jeton-2", id_prof=prof2.id),
    ])
    cours1 = models.SeanceDB(id_enseignement=r101.id, id_groupe=td1.id, id_salle=salle1.id,
                             id_prof=prof1.id, date_debut=DEBUT, date_fin=FIN)
    cours2 = models.SeanceDB(id_enseignement=r102.id, id_groupe=td2.id, id_salle=salle2.id,
                             id_prof=prof2.id, date_debut=DEBUT, date_fin=FIN)
    db.add_all([cours1, cours2])
    db.commit()
    return {"etudiants": etudiants, "autre": autre, "cours1": cours1, "cours2": cours2}
