"""Absences justifiées : période du justificatif, retards, alerte « à risque », fin d'année."""
from datetime import date, datetime, timedelta

import models
from conftest import DEBUT
from services import fin_annee
from services.presences import absences_detaillees, bilan_etudiants, bilan_par_classe, historique_etudiant

PERIODE = (datetime(2026, 10, 1), datetime(2026, 10, 31))
JOUR = DEBUT.date()   # lundi 12/10/2026


def pointer(db, etudiant, seance, minutes, uuid):
    db.add(models.PointageDB(uuid=uuid, nfc_uid=etudiant.carte.nfc_uid, device_id="RPI-001",
                             timestamp=DEBUT + timedelta(minutes=minutes), id_seance=seance.id))
    db.commit()


def justifier(db, etudiant, debut, fin, motif="Certificat médical"):
    db.add(models.JustificatifDB(id_etudiant=etudiant.id, debut=debut, fin=fin, motif=motif))
    db.commit()


def bilans(db, etudiants):
    return {b["etudiant"].nom: b for b in bilan_etudiants(db, etudiants, *PERIODE)}


def appel_avec_charlie_absent(db, iut):
    """Alpha à l'heure, Bravo en retard, Charlie absent."""
    alpha, bravo, charlie = iut["etudiants"]
    pointer(db, alpha, iut["cours1"], 2, "u1")
    pointer(db, bravo, iut["cours1"], 40, "u2")
    return charlie


def test_absence_dans_la_periode_justifiee(db, iut):
    charlie = appel_avec_charlie_absent(db, iut)
    justifier(db, charlie, JOUR, JOUR)                       # un seul jour, bornes incluses
    b = bilans(db, iut["etudiants"])["Charlie"]
    assert (b["absent"], b["absent_justifie"]) == (1, 1)
    assert b["taux"] == 0                                    # option A : taux de présence inchangé
    assert b["a_risque"] is False                            # ... mais pas « à risque »


def test_absence_hors_periode_non_justifiee(db, iut):
    charlie = appel_avec_charlie_absent(db, iut)
    justifier(db, charlie, JOUR - timedelta(days=5), JOUR - timedelta(days=1))   # finit la veille
    justifier(db, charlie, JOUR + timedelta(days=1), JOUR + timedelta(days=3))   # commence le lendemain
    b = bilans(db, iut["etudiants"])["Charlie"]
    assert (b["absent_justifie"], b["a_risque"]) == (0, True)


def test_justificatif_d_un_autre_etudiant_sans_effet(db, iut):
    appel_avec_charlie_absent(db, iut)
    justifier(db, iut["etudiants"][0], JOUR, JOUR)           # justificatif d'Alpha
    assert bilans(db, iut["etudiants"])["Charlie"]["absent_justifie"] == 0


def test_retard_jamais_justifie(db, iut):
    appel_avec_charlie_absent(db, iut)
    bravo = iut["etudiants"][1]
    justifier(db, bravo, JOUR, JOUR)
    b = bilans(db, iut["etudiants"])["Bravo"]
    assert (b["retard"], b["absent_justifie"]) == (1, 0)
    lignes = absences_detaillees(db, [bravo], *PERIODE)
    assert [l["justifiee"] for l in lignes] == [False]


def test_detail_historique_et_classe(db, iut):
    charlie = appel_avec_charlie_absent(db, iut)
    justifier(db, charlie, JOUR, JOUR + timedelta(days=7))
    assert [l["justifiee"] for l in absences_detaillees(db, [charlie], *PERIODE)] == [True]
    assert [h["justifiee"] for h in historique_etudiant(db, charlie, *PERIODE)] == [True]
    classe = bilan_par_classe(bilan_etudiants(db, iut["etudiants"], *PERIODE))[0]
    assert (classe["absent"], classe["absent_justifie"], classe["a_risque"]) == (1, 1, 0)


def test_fin_annee_efface_les_justificatifs(db, iut):
    charlie = iut["etudiants"][2]
    justifier(db, charlie, JOUR, JOUR)
    fin_annee.anonymiser(db, [charlie])
    assert db.query(models.JustificatifDB).count() == 0
