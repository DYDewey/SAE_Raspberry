"""Pages et exports : ajout / suppression d'un justificatif, affichage, Excel."""
import io

import pandas as pd
import pytest

import config
import models
from conftest import DEBUT


@pytest.fixture
def admin(client):
    client.post("/login", data={"identifiant": config.ADMIN_USER, "mot_de_passe": config.ADMIN_PASSWORD})
    return client


def test_ajout_affichage_export_suppression(admin, db, iut):
    charlie = iut["etudiants"][2]
    db.add(models.PointageDB(uuid="u1", nfc_uid="AA000001", device_id="RPI-001", timestamp=DEBUT,
                             id_seance=iut["cours1"].id))
    db.commit()
    periode = "du=2026-10-01&au=2026-10-31"

    r = admin.post(f"/admin/etudiants/{charlie.id}/justificatifs",
                   data={"debut": "2026-10-12", "fin": "2026-10-10", "motif": "x"})
    assert db.query(models.JustificatifDB).count() == 0           # fin avant début : refusé

    admin.post(f"/admin/etudiants/{charlie.id}/justificatifs", data={"debut": "2026-10-12", "motif": "Certificat"})
    assert db.query(models.JustificatifDB).count() == 1           # fin vide = un seul jour

    page = admin.get(f"/admin/etudiants/{charlie.id}?{periode}").text
    assert "Certificat" in page and "Justifiée" in page
    assert "dont 1 justifiée" in admin.get(f"/admin/absences?{periode}").text

    detail = pd.read_excel(io.BytesIO(admin.get(f"/admin/absences/detail?{periode}").content), header=None)
    assert "Justifiée" in detail.values and "Oui" in detail.values
    bilan = pd.read_excel(io.BytesIO(admin.get(f"/admin/absences/export?{periode}").content), header=None)
    assert "Absences justifiées" in bilan.values
    fiche = pd.read_excel(io.BytesIO(admin.get(f"/admin/etudiants/{charlie.id}/export?{periode}").content), header=None)
    assert "Justifiée" in fiche.values

    j = db.query(models.JustificatifDB).one()
    admin.post(f"/admin/etudiants/{charlie.id}/justificatifs/{j.id}/supprimer")
    db.expire_all()
    assert db.query(models.JustificatifDB).count() == 0
