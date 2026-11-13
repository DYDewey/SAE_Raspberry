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


def test_tous_presents_garde_les_badges_et_corrections(client, db, iut):
    """« Tous présents » : les non-badgés passent Présent (à la main), le reste ne change pas."""
    from services.presences import bloc_de_seance, presences_bloc, ABSENT, RETARD, PRESENT
    cours = iut["cours1"]
    alpha, bravo = iut["etudiants"][0], iut["etudiants"][1]
    db.add(models.PointageDB(uuid="u1", nfc_uid=alpha.carte.nfc_uid, device_id="RPI-001",
                             timestamp=DEBUT + timedelta(minutes=30), id_seance=cours.id))
    db.add(models.PresenceManuelleDB(id_seance=cours.id, id_etudiant=bravo.id, statut=ABSENT))
    db.commit()
    _connecter(client)
    assert client.post(f"/admin/seances/{cours.id}/tous-presents").status_code == 204
    liste, _, _ = presences_bloc(db, bloc_de_seance(db, cours))
    statuts = {p["etudiant"].id: (p["statut"], p["manuel"]) for p in liste}
    assert statuts[alpha.id] == (RETARD, False)      # a badgé en retard : inchangé
    assert statuts[bravo.id] == (ABSENT, True)       # corrigé à la main : inchangé
    autres = [s for i, s in statuts.items() if i not in (alpha.id, bravo.id)]
    assert autres and all(s == (PRESENT, True) for s in autres)
