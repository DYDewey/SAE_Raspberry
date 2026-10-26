"""Explique pourquoi les derniers bips sont (ou ne sont pas) rattachés à une séance.

    cd "D:\Cours\Semestre 5\SAE RASP\SAE_Backend"
    venv\Scripts\python diagnostic_sae.py
"""
from datetime import timedelta

import models
from config import AVANCE_POINTAGE_MIN
from database import SessionLocal
from services.groupes import etudiant_concerne
from services.presences import est_sae, trouver_seance

db = SessionLocal()
groupes = {g.id: g.nom_groupe for g in db.query(models.GroupeDB).all()}
cours = {e.id: e.libelle for e in db.query(models.EnseignementDB).all()}

for p in db.query(models.PointageDB).order_by(models.PointageDB.recu_le.desc()).limit(5).all():
    print("=" * 70)
    print(f"Bip {p.nfc_uid}  boîtier {p.device_id}  heure {p.timestamp:%d/%m %H:%M:%S}  séance n°{p.id_seance}")
    boitier = db.get(models.BoitierDB, p.device_id)
    print(f"  Boîtier : mode SAE = {getattr(boitier, 'mode_sae', '?')}, prof = {boitier.id_prof if boitier else '?'}, "
          f"salle = {boitier.id_salle if boitier else '?'}")
    carte = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == p.nfc_uid).first()
    noms = [g.nom_groupe for g in carte.etudiant.groupes] if carte else []
    print(f"  Étudiant : {carte.etudiant.prenom + ' ' + carte.etudiant.nom if carte else 'AUCUN (carte non associée)'}"
          f"  groupes : {noms}")
    seances = db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut <= p.timestamp + timedelta(minutes=AVANCE_POINTAGE_MIN),
        models.SeanceDB.date_fin >= p.timestamp).all()
    print(f"  Séances à cette heure ({len(seances)}) :")
    for s in seances:
        g = groupes.get(s.id_groupe, "?")
        print(f"    n°{s.id:<5} {cours.get(s.id_enseignement, '?')[:35]:35} groupe {g:15} "
              f"SAE={'oui' if est_sae(cours.get(s.id_enseignement)) else 'non'}  "
              f"étudiant concerné={'oui' if etudiant_concerne(noms, g) else 'non'}")
    nouvelle = trouver_seance(db, boitier, p.nfc_uid, p.timestamp)
    print(f"  -> séance trouvée maintenant : {nouvelle.id if nouvelle else 'AUCUNE'}")
