"""Bandeau « Pas d'appel » de la feuille d'émargement (bug : variable appel non transmise)."""
import config
import models
from conftest import DEBUT
from datetime import timedelta


def _connecter(client):
    client.post("/login", data={"identifiant": config.ADMIN_USER, "mot_de_passe": config.ADMIN_PASSWORD})


def test_pas_de_bandeau_quand_des_etudiants_ont_badge(client, db, iut):
    cours = iut["cours1"]
    db.add(models.PointageDB(uuid="u1", nfc_uid="AA000001", device_id="RPI-001",
                             timestamp=DEBUT - timedelta(minutes=5), id_seance=cours.id))
    db.commit()
    _connecter(client)
    for url in (f"/admin/seances/{cours.id}", f"/admin/seances/{cours.id}/panneau"):
        assert "Pas d'appel" not in client.get(url).text


def test_bandeau_quand_personne_n_a_badge(client, iut):
    _connecter(client)
    assert "Pas d'appel" in client.get(f"/admin/seances/{iut['cours1'].id}/panneau").text
