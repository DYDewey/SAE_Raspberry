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


PREFIXE_PROVISOIRE = "PROV-"   # numéro donné par le site quand le fichier n'en a pas


def groupes_depuis_colonnes(ligne) -> str:
    """Format de la liste de la scolarité : ANNEE (« BUT 2 FI », « BUT 3 APP »), PARCOURS (A/B),
    TD (« TD1 ») et TP (« TPA ») -> « BUT2 / BUT2-TD1 / BUT2-TPA », comme les groupes d'ADE.
    Les apprentis n'ont pas de TP : leur parcours désigne leur moitié du TD (BUT2-TD3 + TPB
    = BUT2-TD3-PB, voir services/groupes.py). En BUT3, ils n'ont pas non plus de TD :
    ADE range le parcours A en BUT3-TD2-APP et le parcours B en BUT3-TD3-APP."""
    annee = _cellule(ligne.get("annee")).upper()
    chiffre = re.search(r"\d", annee)
    if not chiffre:
        return ""
    promo = f"BUT{chiffre[0]}"
    parcours = _cellule(ligne.get("parcours")).upper()[:1]
    td = _cellule(ligne.get("td")).upper().replace(" ", "")
    tp = _cellule(ligne.get("tp")).upper().replace(" ", "")
    td = f"TD{td}" if td.isdigit() else td               # « 1 » -> « TD1 »
    tp = f"TP{tp}" if len(tp) == 1 else tp               # « A » -> « TPA »
    if "APP" in annee and parcours in ("A", "B"):
        if promo == "BUT3" and not td:
            td = {"A": "TD2", "B": "TD3"}[parcours]
        tp = tp or f"TP{parcours}"
    return " / ".join([promo] + [f"{promo}-{x}" for x in (td, tp) if x])


def _prochain_numero_provisoire(db: Session):
    """Générateur PROV-0001, PROV-0002... à la suite des numéros provisoires déjà en base."""
    existants = [n for (n,) in db.query(models.EtudiantDB.numero_etudiant)
                 .filter(models.EtudiantDB.numero_etudiant.like(PREFIXE_PROVISOIRE + "%"))]
    i = max((int(n[len(PREFIXE_PROVISOIRE):]) for n in existants
             if n[len(PREFIXE_PROVISOIRE):].isdigit()), default=0)
    while True:
        i += 1
        yield f"{PREFIXE_PROVISOIRE}{i:04d}"


def importer_etudiants(db: Session, contenu: bytes) -> dict:
    """Import du fichier Excel de la scolarité. Colonnes reconnues (majuscules et accents ignorés) :
    - nom, prenom (obligatoires) ;
    - numero (facultatif) : sans numéro, l'étudiant est retrouvé par son nom et prénom,
      et un nouvel étudiant reçoit un numéro provisoire PROV-0001... ;
    - groupe (plusieurs groupes séparés par , ; ou /), OU annee, parcours, td, tp
      (format de la liste de la scolarité, voir groupes_depuis_colonnes).
    Un étudiant déjà présent prend les groupes du fichier. Un étudiant au numéro provisoire
    reçoit son vrai numéro dès qu'un fichier en contient un pour le même nom et prénom."""
    from services.scodoc import cle_nom

    df = pd.read_excel(io.BytesIO(contenu), dtype=object)
    df.columns = [ALIAS_COLONNES.get(_sans_accent(c), _sans_accent(c)) for c in df.columns]
    manquantes = {"nom", "prenom"} - set(df.columns)
    if manquantes:
        raise ValueError(f"Colonne(s) manquante(s) dans le fichier : {', '.join(sorted(manquantes))}")

    ajoutes, modifies = 0, set()
    groupes = {g.nom_groupe: g for g in db.query(models.GroupeDB).all()}
    # Recherche par nom : seulement si le nom n'est porté que par un étudiant (homonymes ignorés)
    par_nom = {}
    for e in db.query(models.EtudiantDB).all():
        par_nom.setdefault(cle_nom(e.nom, e.prenom), []).append(e)
    numeros_provisoires = _prochain_numero_provisoire(db)

    for _, ligne in df.iterrows():
        num, nom, prenom = _cellule(ligne.get("numero")), _cellule(ligne.get("nom")), _cellule(ligne.get("prenom"))
        if not nom:
            continue
        texte_groupes = _cellule(ligne.get("groupe")) or groupes_depuis_colonnes(ligne)

        ses_groupes = []
        for nom_groupe in re.split(r"[,;/]", texte_groupes):
            nom_groupe = nom_groupe.strip()[:16]
            if not nom_groupe:
                continue
            if nom_groupe not in groupes:
                groupes[nom_groupe] = models.GroupeDB(nom_groupe=nom_groupe)
                db.add(groupes[nom_groupe])
                db.flush()
            ses_groupes.append(groupes[nom_groupe])

        etudiant = None
        if num:
            etudiant = db.query(models.EtudiantDB).filter(models.EtudiantDB.numero_etudiant == num).first()
        if not etudiant:
            homonymes = par_nom.get(cle_nom(nom, prenom), [])
            if len(homonymes) == 1 and (not num or homonymes[0].numero_etudiant.startswith(PREFIXE_PROVISOIRE)):
                etudiant = homonymes[0]
                if num:                                  # vrai numéro reçu : il remplace le provisoire
                    etudiant.numero_etudiant = num
                    modifies.add(etudiant.id)
        ses_groupes = list(dict.fromkeys(ses_groupes))
        if not etudiant:
            etudiant = models.EtudiantDB(numero_etudiant=num or next(numeros_provisoires),
                                         nom=nom[:64], prenom=prenom[:64], groupes=ses_groupes)
            db.add(etudiant)
            db.flush()   # pour repérer un numéro présent deux fois dans le fichier
            par_nom.setdefault(cle_nom(nom, prenom), []).append(etudiant)
            ajoutes += 1
        elif ses_groupes and set(ses_groupes) != set(etudiant.groupes):
            # Le fichier de la scolarité fait foi : ses groupes remplacent les anciens
            # (changement de TD/TP en cours d'année). Sans colonne groupe, on ne touche à rien.
            etudiant.groupes = ses_groupes
            modifies.add(etudiant.id)

    db.commit()
    return {"ajoutes": ajoutes, "mis_a_jour": len(modifies)}
