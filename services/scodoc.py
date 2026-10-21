"""Remplissage de la feuille de saisie des absences exportée par ScoDoc.

La secrétaire télécharge depuis ScoDoc la feuille d'une semaine (« feuille_signal_abs_AAAA-Wnn.xlsx »),
le site la remplit à partir des badges, puis elle la réimporte dans ScoDoc. Format de la feuille :
  ligne 5           : un jour toutes les 2 colonnes à partir de E (« Lundi 19/10/2026 »)
  ligne 6           : titres (Nom, Prénom, Groupe, puis Matin / Après-Midi pour chaque jour)
  lignes 7 et +     : un étudiant par ligne (A = id ScoDoc, B = nom, C = prénom, D = groupe)
  cases jaunes      : ABS, RET ou PRE ; on ne touche pas au reste de la feuille.

Par demi-journée : ABS si l'étudiant a manqué au moins un cours, sinon RET s'il est arrivé en retard
à au moins un cours, sinon la case est laissée vide (ScoDoc ne crée rien). Une case déjà remplie
à la main dans la feuille n'est jamais écrasée.
"""
import io
import re
import unicodedata
from collections import Counter
from datetime import datetime

from openpyxl import load_workbook

import models
from services.presences import ABSENT, RETARD, statuts_etudiants

HEURE_MIDI = 12                       # un cours qui commence avant midi compte pour le matin
CODES = {ABSENT: "ABS", RETARD: "RET"}
LIGNE_JOURS, LIGNE_TITRES = 5, 6
COL_NOM, COL_PRENOM, COL_GROUPE, COL_PREMIER_JOUR = 2, 3, 4, 5


def cle_nom(nom, prenom) -> str:
    """NOM Prénom sans accents, tirets ni majuscules : « Clément » = « Clement »."""
    texte = unicodedata.normalize("NFKD", f"{nom} {prenom}").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z]+", " ", texte.lower()).split())


def _jours(ws) -> dict:
    """{(date, après-midi ?): n° de colonne} d'après la ligne des jours."""
    colonnes = {}
    for cellule in ws[LIGNE_JOURS]:
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(cellule.value or ""))
        if m and cellule.column >= COL_PREMIER_JOUR:
            jour = datetime(int(m[3]), int(m[2]), int(m[1])).date()
            colonnes[(jour, False)] = cellule.column
            colonnes[(jour, True)] = cellule.column + 1
    return colonnes


def remplir_feuille(db, contenu: bytes):
    """Remplit la feuille ScoDoc avec les absences et retards de la semaine.
    Renvoie (fichier rempli, résumé)."""
    wb = load_workbook(io.BytesIO(contenu))
    ws = wb.worksheets[0]
    colonnes = _jours(ws)
    if not colonnes:
        raise ValueError("Ce fichier ne ressemble pas à une feuille de saisie ScoDoc "
                         "(pas de jours « Lundi 19/10/2026 » en ligne 5).")
    jours = sorted({j for j, _ in colonnes})
    debut = datetime.combine(jours[0], datetime.min.time())
    fin = datetime.combine(jours[-1], datetime.max.time())

    # Étudiants du site, par nom (un homonyme parfait n'est pas rempli : trop risqué)
    par_nom = {}
    for e in db.query(models.EtudiantDB).all():
        cle = cle_nom(e.nom, e.prenom)
        par_nom[cle] = None if cle in par_nom else e

    lignes, introuvables = {}, []
    for r in range(LIGNE_TITRES + 1, ws.max_row + 1):
        nom, prenom = ws.cell(r, COL_NOM).value, ws.cell(r, COL_PRENOM).value
        if not nom:
            continue
        etudiant = par_nom.get(cle_nom(nom, prenom or ""))
        if etudiant:
            lignes[r] = etudiant
        elif str(ws.cell(r, COL_GROUPE).value or "").strip().upper() != "DEM":   # démissionnaires : normal
            introuvables.append(f"{nom} {prenom or ''}".strip())

    # Statut de chaque demi-journée : ABS l'emporte sur RET
    statuts = {}
    for e, bloc, statut, _, _ in statuts_etudiants(db, list(lignes.values()), debut, fin):
        if statut in CODES:
            cle = (e.id, bloc.debut.date(), bloc.debut.hour >= HEURE_MIDI)
            if statuts.get(cle) != "ABS":
                statuts[cle] = CODES[statut]

    resume = Counter()
    for r, e in lignes.items():
        for (jour, apres_midi), col in colonnes.items():
            code = statuts.get((e.id, jour, apres_midi))
            if not code:
                continue
            cellule = ws.cell(r, col)
            if str(cellule.value or "").strip():
                resume["deja_saisies"] += 1          # saisi à la main dans la feuille : on garde
            else:
                cellule.value = code
                resume[code] += 1

    sortie = io.BytesIO()
    wb.save(sortie)
    sortie.seek(0)
    return sortie, {"abs": resume["ABS"], "ret": resume["RET"], "deja_saisies": resume["deja_saisies"],
                    "trouves": len(lignes), "introuvables": introuvables,
                    "du": jours[0], "au": jours[-1]}
