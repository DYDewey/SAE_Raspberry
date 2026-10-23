"""Boîtier : stockage local, hors connexion, redémarrage, synchronisation.

Le vrai serveur (TestClient) remplace le réseau : requests.post est redirigé vers lui,
ou lève une erreur pour simuler un Wi-Fi coupé."""
import time

import pytest
import requests

import models
from conftest import stockage, synchro


class FauxReseau:
    """Remplace requests.post du boîtier. coupe=True : serveur injoignable.
    perdre_reponse=True : le serveur reçoit le lot mais la réponse se perd."""

    def __init__(self, client):
        self.client = client
        self.coupe = False
        self.perdre_reponse = False
        self.appels = 0

    def post(self, url, json, headers, timeout):
        self.appels += 1
        if self.coupe:
            raise requests.ConnectionError("Wi-Fi coupé")
        r = self.client.post("/api/v1/sync", json=json, headers=headers)
        if self.perdre_reponse:
            raise requests.Timeout("réponse perdue")
        return r


@pytest.fixture
def boitier(tmp_path, client, iut, monkeypatch):
    monkeypatch.setattr(synchro.config, "DEVICE_ID", "RPI-001")
    monkeypatch.setattr(synchro.config, "API_TOKEN", "jeton-1")
    monkeypatch.setattr(synchro.config, "TAILLE_LOT", 100)
    reseau = FauxReseau(client)
    monkeypatch.setattr(synchro.requests, "post", reseau.post)
    local = stockage.Stockage(str(tmp_path / "boitier.db"))
    return local, synchro.Synchro(local), reseau, tmp_path / "boitier.db"


def test_bip_enregistre_en_local_avant_envoi(boitier):
    local, _, _, _ = boitier
    local.ajouter("AA000001")
    assert local.nb_en_attente() == 1


def test_hors_connexion_rien_perdu(boitier, db):
    local, sync, reseau, _ = boitier
    reseau.coupe = True
    for uid in ("AA000001", "AA000002", "AA000003"):
        local.ajouter(uid)
    sync._cycle()
    assert sync.en_ligne is False
    assert local.nb_en_attente() == 3
    assert db.query(models.PointageDB).count() == 0


def test_retour_reseau_synchronisation_automatique(boitier, db):
    local, sync, reseau, _ = boitier
    reseau.coupe = True
    local.ajouter("AA000001")
    local.ajouter("AA000002")
    sync._cycle()
    reseau.coupe = False
    sync._cycle()
    assert sync.en_ligne is True
    assert local.nb_en_attente() == 0
    assert db.query(models.PointageDB).count() == 2


def test_redemarrage_sans_perte(boitier, db):
    """Coupure de courant : un nouveau Stockage sur le même fichier retrouve les bips."""
    local, _, reseau, chemin = boitier
    reseau.coupe = True
    local.ajouter("AA000001")
    local.conn.close()

    relance = stockage.Stockage(str(chemin))
    assert relance.nb_en_attente() == 1
    reseau.coupe = False
    synchro.Synchro(relance)._cycle()
    assert relance.nb_en_attente() == 0
    assert db.query(models.PointageDB).count() == 1


def test_coupure_pendant_synchro_sans_doublon(boitier, db):
    local, sync, reseau, _ = boitier
    local.ajouter("AA000001")
    reseau.perdre_reponse = True
    sync._cycle()
    assert local.nb_en_attente() == 1                     # pas de confirmation : on garde
    reseau.perdre_reponse = False
    sync._cycle()
    assert local.nb_en_attente() == 0
    assert db.query(models.PointageDB).count() == 1       # reçu deux fois, enregistré une fois


def test_token_refuse_pointages_gardes(boitier, monkeypatch):
    local, sync, _, _ = boitier
    monkeypatch.setattr(synchro.config, "API_TOKEN", "mauvais")
    local.ajouter("AA000001")
    sync._cycle()
    assert sync.en_ligne is False
    assert local.nb_en_attente() == 1


def test_cartes_connues_recues_du_serveur(boitier):
    local, sync, _, _ = boitier
    assert local.carte_connue("AA000001") is None          # jamais reçu la liste : on ne bloque pas
    sync._cycle()
    assert local.carte_connue("AA000001") is True
    assert local.carte_connue("FFFFFFFF") is False


def test_nettoyage_garde_les_non_envoyes(boitier):
    local, _, reseau, _ = boitier
    reseau.coupe = True
    local.ajouter("AA000001")
    local.conn.execute("UPDATE pointages SET timestamp = '2020-01-01T00:00:00Z'")
    local.nettoyer(30)
    assert local.nb_en_attente() == 1


def test_mille_bips_hors_ligne_puis_synchro(boitier, db):
    """Grosse file d'attente (journée sans réseau) : tout part, par lots de 100."""
    local, sync, reseau, _ = boitier
    reseau.coupe = True
    debut = time.perf_counter()
    for i in range(1000):
        local.ajouter(f"AA{i:06d}")
    duree_bips = time.perf_counter() - debut
    reseau.coupe = False
    debut = time.perf_counter()
    sync._cycle()
    duree_synchro = time.perf_counter() - debut
    print(f"\n1000 bips enregistrés en {duree_bips:.2f} s, synchronisés en {duree_synchro:.2f} s "
          f"({reseau.appels} envois)")
    assert local.nb_en_attente() == 0
    assert db.query(models.PointageDB).count() == 1000
    assert reseau.appels == 10                             # 10 lots de 100
