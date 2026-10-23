"""Calcul des statuts : présent, en retard, absent, cours sans appel."""
from datetime import datetime, timedelta

import models
from config import TOLERANCE_RETARD_MIN
from conftest import DEBUT, FIN
from services.presences import (ABSENT, PRESENT, RETARD, bilan_etudiants, bloc_de_seance,
                                resumes_blocs, statut_depuis, taux)

PERIODE = (datetime(2026, 10, 1), datetime(2026, 10, 31))


def pointer(db, uid, seance, minutes_apres_debut, uuid):
    db.add(models.PointageDB(uuid=uuid, nfc_uid=uid, device_id="RPI-001",
                             timestamp=DEBUT + timedelta(minutes=minutes_apres_debut), id_seance=seance.id))
    db.commit()


def bilans(db, etudiants):
    return {b["etudiant"].nom: b for b in bilan_etudiants(db, etudiants, *PERIODE)}


def test_statut_depuis():
    assert statut_depuis(None, DEBUT) == ABSENT
    assert statut_depuis(DEBUT - timedelta(minutes=10), DEBUT) == PRESENT
    assert statut_depuis(DEBUT + timedelta(minutes=TOLERANCE_RETARD_MIN), DEBUT) == PRESENT   # pile la limite
    assert statut_depuis(DEBUT + timedelta(minutes=TOLERANCE_RETARD_MIN + 1), DEBUT) == RETARD


def test_taux():
    assert taux(2, 1, 4) == 75          # un retard compte comme présent
    assert taux(0, 0, 0) is None        # aucun cours : pas de taux


def test_cours_sans_appel_ne_compte_pas(db, iut):
    """Personne n'a badgé : le prof n'avait pas son boîtier, personne n'est absent."""
    resume = resumes_blocs(db, [bloc_de_seance(db, iut["cours1"])])
    assert list(resume.values())[0]["appel"] is False
    assert list(resume.values())[0]["absent"] == 0
    assert all(b["cours"] == 0 for b in bilans(db, iut["etudiants"]).values())


def test_appel_fait_present_retard_absent(db, iut):
    alpha, bravo, _ = iut["etudiants"]
    pointer(db, alpha.carte.nfc_uid, iut["cours1"], 2, "u1")                             # à l'heure
    pointer(db, bravo.carte.nfc_uid, iut["cours1"], TOLERANCE_RETARD_MIN + 10, "u2")     # en retard
    b = bilans(db, iut["etudiants"])
    assert (b["Alpha"]["present"], b["Alpha"]["taux"]) == (1, 100)
    assert (b["Bravo"]["retard"], b["Bravo"]["taux"]) == (1, 100)
    assert (b["Charlie"]["absent"], b["Charlie"]["taux"]) == (1, 0)

    resume = list(resumes_blocs(db, [bloc_de_seance(db, iut["cours1"])]).values())[0]
    assert (resume["effectif"], resume["present"], resume["retard"], resume["absent"]) == (3, 1, 1, 1)


def test_correction_manuelle_prioritaire(db, iut):
    alpha = iut["etudiants"][0]
    pointer(db, alpha.carte.nfc_uid, iut["cours1"], 2, "u1")
    db.add(models.PresenceManuelleDB(id_seance=iut["cours1"].id, id_etudiant=alpha.id, statut=ABSENT))
    db.commit()
    assert bilans(db, iut["etudiants"])["Alpha"]["absent"] == 1


def test_correction_manuelle_seule_vaut_appel(db, iut):
    """Boîtier en panne : le prof coche à la main, le cours compte."""
    alpha = iut["etudiants"][0]
    db.add(models.PresenceManuelleDB(id_seance=iut["cours1"].id, id_etudiant=alpha.id, statut=PRESENT))
    db.commit()
    b = bilans(db, iut["etudiants"])
    assert b["Alpha"]["present"] == 1
    assert b["Bravo"]["absent"] == 1


def test_etudiant_autre_groupe_non_compte(db, iut):
    pointer(db, "AA000001", iut["cours1"], 0, "u1")
    assert bilans(db, [iut["autre"]])["Delta"]["cours"] == 0


def test_bloc_de_deux_creneaux(db, iut):
    """8h-10h puis 10h-12h même cours : un seul bloc, entrée à 8h = présent."""
    c = iut["cours1"]
    suite = models.SeanceDB(id_enseignement=c.id_enseignement, id_groupe=c.id_groupe, id_salle=c.id_salle,
                            id_prof=c.id_prof, date_debut=FIN, date_fin=FIN + timedelta(hours=2))
    db.add(suite)
    db.commit()
    bloc = bloc_de_seance(db, suite)
    assert bloc.ids == [c.id, suite.id]
    pointer(db, "AA000001", c, 0, "u1")
    assert bilans(db, iut["etudiants"])["Alpha"]["cours"] == 1
