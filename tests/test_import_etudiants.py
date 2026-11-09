"""Import Excel des étudiants : format avec numéro et format de la liste de la scolarité."""
import io

import pandas as pd

import models
from services.etudiants import groupes_depuis_colonnes, importer_etudiants


def excel(lignes):
    sortie = io.BytesIO()
    pd.DataFrame(lignes).to_excel(sortie, index=False)
    return sortie.getvalue()


def noms_groupes(e):
    return sorted(g.nom_groupe for g in e.groupes)


LISTE = [  # même format que la liste de la scolarité (sans numéro)
    {"NOM": "DUPONT", "PRENOM": "Léa", "PARCOURS": None, "ANNEE": "BUT 1", "TD": "TD1", "TP": "TPA"},
    {"NOM": "MARTIN", "PRENOM": "Hugo", "PARCOURS": "A", "ANNEE": "BUT 2 APP", "TD": "TD3", "TP": None},
    {"NOM": "PETIT", "PRENOM": "Zoé", "PARCOURS": "B", "ANNEE": "BUT 3 APP", "TD": None, "TP": None},
]


def test_groupes_depuis_colonnes():
    assert groupes_depuis_colonnes({"annee": "BUT 2 FI", "parcours": "B", "td": "TD2", "tp": "TPC"}) \
        == "BUT2 / BUT2-TD2 / BUT2-TPC"
    assert groupes_depuis_colonnes({"annee": "BUT 2 APP", "parcours": "A", "td": "TD3", "tp": ""}) \
        == "BUT2 / BUT2-TD3 / BUT2-TPA"
    assert groupes_depuis_colonnes({"annee": "BUT 3 APP", "parcours": "A", "td": "", "tp": ""}) \
        == "BUT3 / BUT3-TD2 / BUT3-TPA"
    assert groupes_depuis_colonnes({"annee": "BUT 3 APP", "parcours": "B", "td": "", "tp": ""}) \
        == "BUT3 / BUT3-TD3 / BUT3-TPB"
    assert groupes_depuis_colonnes({"annee": "BUT 1", "td": "1", "tp": "B"}) == "BUT1 / BUT1-TD1 / BUT1-TPB"
    assert groupes_depuis_colonnes({"annee": ""}) == ""


def test_liste_scolarite_sans_numero(db):
    assert importer_etudiants(db, excel(LISTE)) == {"ajoutes": 3, "mis_a_jour": 0}
    lea = db.query(models.EtudiantDB).filter_by(nom="DUPONT").one()
    assert lea.numero_etudiant == "PROV-0001"
    assert noms_groupes(lea) == ["BUT1", "BUT1-TD1", "BUT1-TPA"]


def test_reimport_sans_doublon_et_changement_de_groupe(db):
    importer_etudiants(db, excel(LISTE))
    lignes = [dict(l) for l in LISTE]
    lignes[0]["TP"] = "TPB"                                              # Léa change de TP
    lignes.append({"NOM": "NOUVEAU", "PRENOM": "Max", "PARCOURS": None, "ANNEE": "BUT 1", "TD": "TD2", "TP": "TPC"})
    assert importer_etudiants(db, excel(lignes)) == {"ajoutes": 1, "mis_a_jour": 1}
    assert db.query(models.EtudiantDB).count() == 4
    assert db.query(models.EtudiantDB).filter_by(nom="NOUVEAU").one().numero_etudiant == "PROV-0004"


def test_vrai_numero_remplace_le_provisoire(db):
    importer_etudiants(db, excel(LISTE))
    r = importer_etudiants(db, excel([{"numero": 22301234, "nom": "Dupont", "prenom": "Lea"}]))
    assert r == {"ajoutes": 0, "mis_a_jour": 1}                          # accents et majuscules ignorés
    lea = db.query(models.EtudiantDB).filter_by(nom="DUPONT").one()
    assert lea.numero_etudiant == "22301234"
    assert noms_groupes(lea) == ["BUT1", "BUT1-TD1", "BUT1-TPA"]         # pas de colonne groupe : inchangés


def test_ancien_format_avec_numero(db):
    importer_etudiants(db, excel([{"numero": "111", "nom": "A", "prenom": "B", "groupe": "BUT1, BUT1-TD1"}]))
    r = importer_etudiants(db, excel([{"numero": "111", "nom": "A", "prenom": "B", "groupe": "BUT1, BUT1-TD2"}]))
    assert r == {"ajoutes": 0, "mis_a_jour": 1}
    assert noms_groupes(db.query(models.EtudiantDB).one()) == ["BUT1", "BUT1-TD2"]


def test_homonyme_avec_vrai_numero_pas_ecrase(db):
    """Un étudiant qui a déjà un vrai numéro n'est pas confondu avec un homonyme d'un autre numéro."""
    importer_etudiants(db, excel([{"numero": "111", "nom": "Durand", "prenom": "Paul"}]))
    importer_etudiants(db, excel([{"numero": "222", "nom": "Durand", "prenom": "Paul"}]))
    assert db.query(models.EtudiantDB).count() == 2
