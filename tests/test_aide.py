"""Menu Aide : qui voit quel tutoriel."""
import config
import models
from services.comptes import hacher


def connecter_admin(client):
    client.post("/login", data={"identifiant": config.ADMIN_USER, "mot_de_passe": config.ADMIN_PASSWORD})


def connecter_prof(client, db):
    db.add(models.ProfesseurDB(nom="Martin", prenom="Paul", identifiant="pmartin", mot_de_passe=hacher("secret123")))
    db.commit()
    client.post("/login", data={"identifiant": "pmartin", "mot_de_passe": "secret123"})


def test_non_connecte_renvoye_vers_login(client):
    r = client.get("/admin/aide", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert "/login" in r.headers["location"]


def test_admin_voit_les_trois_tutos(client):
    connecter_admin(client)
    sommaire = client.get("/admin/aide")
    assert sommaire.status_code == 200
    for tuto in ("enseignant", "secretariat", "administrateur"):
        assert f"/admin/aide/{tuto}" in sommaire.text
        page = client.get(f"/admin/aide/{tuto}")
        assert page.status_code == 200
        assert "Sommaire" in page.text


def test_prof_ne_voit_que_le_tuto_enseignant(client, db):
    connecter_prof(client, db)
    sommaire = client.get("/admin/aide")
    assert "/admin/aide/enseignant" in sommaire.text
    assert "/admin/aide/secretariat" not in sommaire.text
    assert client.get("/admin/aide/enseignant").status_code == 200
    assert client.get("/admin/aide/secretariat").status_code == 403
    assert client.get("/admin/aide/administrateur").status_code == 403


def test_tuto_inconnu(client):
    connecter_admin(client)
    assert client.get("/admin/aide/nimporte").status_code == 404


def test_lien_aide_dans_le_menu(client):
    connecter_admin(client)
    assert 'href="/admin/aide"' in client.get("/admin/aide/enseignant").text
