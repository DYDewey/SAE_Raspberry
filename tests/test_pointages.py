"""Page Pointages : filtres combinables sur les bips reçus."""
from datetime import datetime

import models
from routers.pointages import filtrer_pointages

JOUR = (datetime(2026, 10, 12), datetime(2026, 10, 13))   # fin exclue


def ajouter_bips(db, iut):
    c1, c2 = iut["cours1"].id, iut["cours2"].id
    db.add_all([
        models.PointageDB(uuid="b1", nfc_uid="AA000001", device_id="RPI-001", timestamp=datetime(2026, 10, 12, 8, 2), id_seance=c1),
        models.PointageDB(uuid="b2", nfc_uid="AA000002", device_id="RPI-001", timestamp=datetime(2026, 10, 12, 9, 30), id_seance=c1),
        models.PointageDB(uuid="b3", nfc_uid="BB000009", device_id="RPI-002", timestamp=datetime(2026, 10, 12, 8, 10), id_seance=c2),
        models.PointageDB(uuid="b4", nfc_uid="FFFFFFFF", device_id="RPI-002", timestamp=datetime(2026, 10, 12, 18, 0)),
        models.PointageDB(uuid="b6", nfc_uid="AA000003", device_id="RPI-001", timestamp=datetime(2026, 10, 12, 23, 59, 59, 400000)),
        models.PointageDB(uuid="b5", nfc_uid="AA000001", device_id="RPI-001", timestamp=datetime(2026, 10, 13, 8, 0)),
    ])
    db.commit()


def uuids(requete):
    return sorted(p.uuid for p, *_ in requete.all())


def test_sans_filtre_tous_les_bips_du_jour(db, iut):
    ajouter_bips(db, iut)
    assert uuids(filtrer_pointages(db, *JOUR)) == ["b1", "b2", "b3", "b4", "b6"]  # b6 : dernière seconde du jour


def test_filtre_etudiant_par_nom_ou_uid(db, iut):
    ajouter_bips(db, iut)
    assert uuids(filtrer_pointages(db, *JOUR, q="alpha")) == ["b1"]
    assert uuids(filtrer_pointages(db, *JOUR, q="FFFF")) == ["b4"]
    assert uuids(filtrer_pointages(db, *JOUR, q="aa:00:00:02")) == ["b2"]


def test_filtres_groupe_enseignement_salle(db, iut):
    ajouter_bips(db, iut)
    td1 = iut["etudiants"][0].groupes[0].id
    assert uuids(filtrer_pointages(db, *JOUR, groupe=td1)) == ["b1", "b2", "b6"]
    assert uuids(filtrer_pointages(db, *JOUR, enseignement=iut["cours2"].id_enseignement)) == ["b3"]
    assert uuids(filtrer_pointages(db, *JOUR, salle=iut["cours1"].id_salle)) == ["b1", "b2"]


def test_plage_horaire_et_combinaison(db, iut):
    ajouter_bips(db, iut)
    assert uuids(filtrer_pointages(db, *JOUR, de="08:00", a="09:00")) == ["b1", "b3"]
    td1 = iut["etudiants"][0].groupes[0].id
    assert uuids(filtrer_pointages(db, *JOUR, groupe=td1, de="09:00")) == ["b2", "b6"]
    assert uuids(filtrer_pointages(db, *JOUR, de="08:00:00", a="09:00:00")) == ["b1", "b3"]


def test_plage_de_dates(db, iut):
    ajouter_bips(db, iut)
    assert uuids(filtrer_pointages(db, datetime(2026, 10, 13), datetime(2026, 10, 14))) == ["b5"]
