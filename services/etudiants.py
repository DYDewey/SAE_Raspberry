"""Import Excel des étudiants et association des cartes NFC."""
import io
import re
import unicodedata

import pandas as pd
from sqlalchemy.orm import Session

import models
from services.temps import normaliser_uid


def associer_carte(db: Session, etudiant, nfc_uid: str) -> str:
    """Associe (ou retire si vide) une carte NFC à un étudiant.
    Si la carte appartenait à un autre étudiant, elle lui est retirée.
    Retourne un message décrivant ce qui a été fait."""
    uid = normaliser_uid(nfc_uid)
    if not uid:
        if etudiant.carte:
            db.delete(etudiant.carte)
            db.commit()
            return "Carte retirée."
        return ""

    if etudiant.carte and etudiant.carte.nfc_uid == uid:
        return ""

    message = f"Carte {uid} associée à {etudiant.prenom} {etudiant.nom}."
    ancienne = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == uid).first()
    if ancienne:
        message += f" Elle a été retirée à {ancienne.etudiant.prenom} {ancienne.etudiant.nom}."
        db.delete(ancienne)
    if etudiant.carte:
        db.delete(etudiant.carte)
    db.commit()
    db.add(models.CarteDB(nfc_uid=uid, id_etudiant=etudiant.id))
    db.commit()
    return message


def _sans_accent(texte) -> str:
    texte = unicodedata.normalize("NFKD", str(texte))
    return "".join(c for c in texte if not unicodedata.combining(c)).strip().lower()


def _cellule(valeur) -> str:
    """Nettoie une cellule Excel : 22301234.0 -> '22301234', vide -> ''."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur).strip()


ALIAS_COLONNES = {
    "num": "numero", "numero etudiant": "numero", "numero_etudiant": "numero",
    "n° etudiant": "numero", "groupes": "groupe", "classe": "groupe",
}


def importer_etudiants(db: Session, contenu: bytes) -> dict:
    """Import du fichier Excel de la scolarité.
    Colonnes reconnues (majuscules et accents ignorés) : numero, nom, prenom
    et, en option, groupe (plusieurs groupes séparés par , ; ou /)."""
    df = pd.read_excel(io.BytesIO(contenu), dtype=object)
    df.columns = [ALIAS_COLONNES.get(_sans_accent(c), _sans_accent(c)) for c in df.columns]
    manquantes = {"numero", "nom", "prenom"} - set(df.columns)
    if manquantes:
        raise ValueError(f"Colonne(s) manquante(s) dans le fichier : {', '.join(sorted(manquantes))}")

    ajoutes = mis_a_jour = 0
    groupes = {g.nom_groupe: g for g in db.query(models.GroupeDB).all()}

    for _, ligne in df.iterrows():
        num, nom, prenom = _cellule(ligne.get("numero")), _cellule(ligne.get("nom")), _cellule(ligne.get("prenom"))
        if not num or not nom:
            continue

        ses_groupes = []
        for nom_groupe in re.split(r"[,;/]", _cellule(ligne.get("groupe"))):
            nom_groupe = nom_groupe.strip()[:16]
            if not nom_groupe:
                continue
            if nom_groupe not in groupes:
                groupes[nom_groupe] = models.GroupeDB(nom_groupe=nom_groupe)
                db.add(groupes[nom_groupe])
                db.flush()
            ses_groupes.append(groupes[nom_groupe])

        etudiant = db.query(models.EtudiantDB).filter(models.EtudiantDB.numero_etudiant == num).first()
        if not etudiant:
            db.add(models.EtudiantDB(numero_etudiant=num, nom=nom[:64], prenom=prenom[:64],
                                     groupes=list(dict.fromkeys(ses_groupes))))
            db.flush()   # pour repérer un numéro présent deux fois dans le fichier
            ajoutes += 1
        else:
            nouveaux = [g for g in dict.fromkeys(ses_groupes) if g not in etudiant.groupes]
            if nouveaux:
                etudiant.groupes.extend(nouveaux)
                mis_a_jour += 1

    db.commit()
    return {"ajoutes": ajoutes, "mis_a_jour": mis_a_jour}
