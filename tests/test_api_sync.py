"""API POST /api/v1/sync : réception des pointages envoyés par les boîtiers."""
import models
from conftest import utc

ENTETE_1 = {"Authorization": "Bearer jeton-1"}
ENTETE_2 = {"Authorization": "Bearer jeton-2"}


def bip(uuid, uid, heure=8, minute=0):
    return {"uuid": uuid, "nfc_uid": uid, "timestamp": utc(heure, minute)}


def envoyer(client, lot, device="RPI-001", entete=ENTETE_1):
    return client.post("/api/v1/sync", json={"device_id": device, "batch": lot}, headers=entete)


def test_token_invalide_refuse_et_rien_enregistre(client, db, iut):
    r = envoyer(client, [bip("u1", "AA000001")], entete={"Authorization": "Bearer faux"})
    assert r.status_code == 401
    assert db.query(models.PointageDB).count() == 0


def test_boitier_inconnu_refuse(client, iut):
    r = envoyer(client, [bip("u1", "AA000001")], device="RPI-999")
    assert r.status_code == 401


def test_pointages_enregistres_et_rattaches_au_cours(client, db, iut):
    r = envoyer(client, [bip("u1", "AA000001", 8, 2), bip("u2", "AA000002", 8, 5)])
    assert r.status_code == 200
    assert sorted(r.json()["synced_uuids"]) == ["u1", "u2"]
    pointages = db.query(models.PointageDB).all()
    assert len(pointages) == 2
    assert {p.id_seance for p in pointages} == {iut["cours1"].id}
    # Heure UTC du boîtier convertie en heure de Paris
    assert min(p.timestamp for p in pointages).strftime("%H:%M") == "08:02"


def test_uid_normalise(client, db, iut):
    envoyer(client, [bip("u1", "aa:00:00:01")])
    assert db.query(models.PointageDB).one().nfc_uid == "AA000001"


def test_renvoi_du_meme_lot_sans_doublon(client, db, iut):
    """Réponse perdue (coupure) : le boîtier renvoie le lot, le serveur ne double rien."""
    lot = [bip("u1", "AA000001"), bip("u2", "AA000002")]
    envoyer(client, lot)
    r = envoyer(client, lot)
    assert sorted(r.json()["synced_uuids"]) == ["u1", "u2"]
    assert db.query(models.PointageDB).count() == 2


def test_meme_uuid_deux_fois_dans_un_lot(client, db, iut):
    r = envoyer(client, [bip("u1", "AA000001"), bip("u1", "AA000001")])
    assert r.json()["synced_uuids"] == ["u1"]
    assert db.query(models.PointageDB).count() == 1


def test_date_illisible_rejetee_sans_bloquer_le_lot(client, db, iut):
    lot = [{"uuid": "u1", "nfc_uid": "AA000001", "timestamp": "pas une date"}, bip("u2", "AA000002")]
    reponse = envoyer(client, lot).json()
    assert reponse["rejected_uuids"] == ["u1"]
    # Confirmé quand même : le boîtier ne le renverra pas en boucle
    assert sorted(reponse["synced_uuids"]) == ["u1", "u2"]
    assert db.query(models.PointageDB).count() == 1


def test_carte_inconnue_enregistree(client, db, iut):
    """Le bip d'une carte non associée est gardé (on pourra l'associer plus tard)."""
    reponse = envoyer(client, [bip("u1", "FFFFFFFF")]).json()
    assert reponse["synced_uuids"] == ["u1"]
    assert db.query(models.PointageDB).one().nfc_uid == "FFFFFFFF"
    assert "FFFFFFFF" not in reponse["cartes_connues"]
    assert "AA000001" in reponse["cartes_connues"]


def test_lot_vide_signal_de_vie(client, db, iut):
    r = envoyer(client, [])
    assert r.status_code == 200
    assert db.get(models.BoitierDB, "RPI-001").derniere_synchro is not None


def test_deux_boitiers_en_parallele(client, db, iut):
    """Deux cours en même temps dans deux salles : chaque bip va au bon cours."""
    envoyer(client, [bip("u1", "AA000001")], "RPI-001", ENTETE_1)
    envoyer(client, [bip("u2", "BB000009")], "RPI-002", ENTETE_2)
    seances = {p.uuid: p.id_seance for p in db.query(models.PointageDB).all()}
    assert seances == {"u1": iut["cours1"].id, "u2": iut["cours2"].id}


def test_bip_hors_cours_garde_sans_seance(client, db, iut):
    envoyer(client, [bip("u1", "AA000001", 20)])
    p = db.query(models.PointageDB).one()
    assert p.id_seance is None
