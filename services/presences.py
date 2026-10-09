"""Rattachement des pointages aux séances et calcul des présences.

Vocabulaire :
- séance : un créneau de l'emploi du temps (une ligne de la table seances) ;
- bloc   : plusieurs séances qui se suivent pour le même cours, groupe, salle et
           prof (ex : 8h-9h30 + 9h30-11h). L'EDT et l'émargement raisonnent en
           blocs : badger à 8h (entrée) et à 11h (sortie) compte pour le bloc entier.
"""
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from config import AVANCE_POINTAGE_MIN, MOTIF_SAE, TOLERANCE_RETARD_MIN
from services.groupes import etudiant_concerne, sont_lies
from services.temps import maintenant_paris

PRESENT, RETARD, ABSENT = "Présent", "En retard", "Absent"


# ==========================================
# Rattachement pointage -> séance
# ==========================================

def est_sae(libelle: str) -> bool:
    return bool(re.search(MOTIF_SAE, libelle or "", re.IGNORECASE))


def trouver_seance(db: Session, boitier, nfc_uid: str, t: datetime):
    """Retrouve la séance d'un pointage : boîtier -> prof (ou salle en repli)
    + heure du bip -> séance de l'EDT qui couvre cette heure.
    Boîtier en mode SAE : séance de SAE du groupe de l'étudiant à cette heure."""
    if boitier is None:
        return None

    fenetre = db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut <= t + timedelta(minutes=AVANCE_POINTAGE_MIN),
        models.SeanceDB.date_fin >= t,
    )

    # Groupes de l'étudiant, pour départager un CM partagé entre plusieurs groupes
    noms_etudiant = []
    carte = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == nfc_uid).first()
    if carte:
        noms_etudiant = [g.nom_groupe for g in carte.etudiant.groupes]

    def nom_groupe(seances):
        return {g.id: g.nom_groupe for g in db.query(models.GroupeDB).filter(
            models.GroupeDB.id.in_({s.id_groupe for s in seances})).all()}

    candidates = []
    if boitier.mode_sae and noms_etudiant:
        # Toutes les SAE de l'IUT à cette heure, puis seulement celles de sa classe
        libelles = {e.id: e.libelle for e in db.query(models.EnseignementDB).all()}
        sae = [s for s in fenetre.all() if est_sae(libelles.get(s.id_enseignement))]
        groupes_sae = nom_groupe(sae)
        candidates = [s for s in sae if etudiant_concerne(noms_etudiant, groupes_sae.get(s.id_groupe, ""))]
    if not candidates and boitier.id_prof:
        candidates = fenetre.filter(models.SeanceDB.id_prof == boitier.id_prof).all()
    if not candidates and boitier.id_salle:
        candidates = fenetre.filter(models.SeanceDB.id_salle == boitier.id_salle).all()
    if not candidates:
        return None
    noms_groupes = nom_groupe(candidates)

    def priorite(s):
        return (
            not etudiant_concerne(noms_etudiant, noms_groupes.get(s.id_groupe, "")),  # 1. cours de sa classe
            not (s.date_debut <= t < s.date_fin),      # 2. séance en cours plutôt que la suivante
            abs((s.date_debut - t).total_seconds()),   # 3. la plus proche
        )

    return min(candidates, key=priorite)


def rattacher_pointages(db: Session, debut: datetime, fin: datetime) -> int:
    """Recalcule la séance de tous les pointages d'une période (après une
    synchro EDT ou un changement de prof/salle sur un boîtier)."""
    boitiers = {b.device_id: b for b in db.query(models.BoitierDB).all()}
    pointages = db.query(models.PointageDB).filter(
        models.PointageDB.timestamp >= debut,
        models.PointageDB.timestamp < fin,
    ).all()
    for p in pointages:
        seance = trouver_seance(db, boitiers.get(p.device_id), p.nfc_uid, p.timestamp)
        p.id_seance = seance.id if seance else None
    db.commit()
    return len(pointages)


# ==========================================
# Blocs (séances contiguës)
# ==========================================

@dataclass
class Bloc:
    seances: list
    enseignement: object = None
    groupe: object = None
    salle: object = None
    prof: object = None

    @property
    def id(self):            # id utilisé dans les liens : celui du 1er créneau
        return self.seances[0].id

    @property
    def ids(self):
        return [s.id for s in self.seances]

    @property
    def debut(self):
        return self.seances[0].date_debut

    @property
    def fin(self):
        return self.seances[-1].date_fin

    @property
    def code(self):
        return self.enseignement.code_cours if self.enseignement else ""

    @property
    def libelle(self):
        return self.enseignement.libelle if self.enseignement else "Cours inconnu"

    @property
    def nom_groupe(self):
        return self.groupe.nom_groupe if self.groupe else "Inconnu"

    @property
    def nom_salle(self):
        return self.salle.nom_salle if self.salle else "Inconnue"

    @property
    def nom_prof(self):
        if not self.prof or self.prof.nom == "N/A":
            return ""
        return f"{self.prof.nom} {self.prof.prenom}".strip()

    def etat(self, maintenant=None):
        maintenant = maintenant or maintenant_paris()
        if maintenant < self.debut:
            return "a_venir"
        return "en_cours" if maintenant < self.fin else "termine"


def _par_id(db, modele, ids):
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return {o.id: o for o in db.query(modele).filter(modele.id.in_(ids)).all()}


def construire_blocs(db: Session, seances, fusionner: bool = True) -> list:
    """Regroupe les séances contiguës d'un même cours en blocs
    (fusionner=False : un bloc par créneau, pour l'affichage de la grille)."""
    par_signature = defaultdict(list)
    for s in seances:
        cle = (s.id_enseignement, s.id_groupe, s.id_salle, s.id_prof, s.date_debut.date())
        par_signature[cle].append(s)

    blocs = []
    for liste in par_signature.values():
        liste.sort(key=lambda s: s.date_debut)
        courant = [liste[0]]
        for s in liste[1:]:
            if fusionner and s.date_debut == courant[-1].date_fin:
                courant.append(s)
            else:
                blocs.append(Bloc(courant))
                courant = [s]
        blocs.append(Bloc(courant))

    # Chargement des objets liés en une requête par table
    enseignements = _par_id(db, models.EnseignementDB, [b.seances[0].id_enseignement for b in blocs])
    groupes = _par_id(db, models.GroupeDB, [b.seances[0].id_groupe for b in blocs])
    salles = _par_id(db, models.SalleDB, [b.seances[0].id_salle for b in blocs])
    profs = _par_id(db, models.ProfesseurDB, [b.seances[0].id_prof for b in blocs])
    for b in blocs:
        s = b.seances[0]
        b.enseignement = enseignements.get(s.id_enseignement)
        b.groupe = groupes.get(s.id_groupe)
        b.salle = salles.get(s.id_salle)
        b.prof = profs.get(s.id_prof)

    return sorted(blocs, key=lambda b: (b.debut, b.nom_groupe))


def bloc_de_seance(db: Session, seance) -> Bloc:
    """Le bloc qui contient une séance donnée."""
    debut_jour = seance.date_debut.replace(hour=0, minute=0, second=0, microsecond=0)
    memes = db.query(models.SeanceDB).filter(
        models.SeanceDB.id_enseignement == seance.id_enseignement,
        models.SeanceDB.id_groupe == seance.id_groupe,
        models.SeanceDB.id_salle == seance.id_salle,
        models.SeanceDB.id_prof == seance.id_prof,
        models.SeanceDB.date_debut >= debut_jour,
        models.SeanceDB.date_debut < debut_jour + timedelta(days=1),
    ).all()
    return next(b for b in construire_blocs(db, memes) if seance.id in b.ids)


# ==========================================
# Statuts
# ==========================================

def statut_depuis(premier_bip, debut: datetime) -> str:
    if premier_bip is None:
        return ABSENT
    if premier_bip <= debut + timedelta(minutes=TOLERANCE_RETARD_MIN):
        return PRESENT
    return RETARD


def heure_sortie(bips):
    """Dernier bip, s'il est distinct de l'entrée (plus de 5 min après)."""
    if len(bips) > 1 and bips[-1] - bips[0] > timedelta(minutes=5):
        return bips[-1]
    return None


def ids_groupes_lies(db: Session, noms) -> set:
    """Id des groupes liés (même groupe, parent ou sous-groupe) à l'un des noms donnés."""
    noms = list(noms)
    return {g.id for g in db.query(models.GroupeDB).all() if any(sont_lies(g.nom_groupe, n) for n in noms)}


def etudiants_par_groupe(db: Session, ids_groupes) -> dict:
    """{id_groupe: étudiants attendus aux cours de ce groupe} (voir services/groupes.py).
    Tous les groupes en une fois : quelques requêtes au lieu de plusieurs par groupe."""
    noms = {g.id: g.nom_groupe for g in db.query(models.GroupeDB).all()}
    cibles = {i: noms[i] for i in set(ids_groupes) if i in noms}
    if not cibles:
        return {}
    ids_lies = {i for i, n in noms.items() if any(sont_lies(n, c) for c in cibles.values())}
    candidats = db.query(models.EtudiantDB).filter(
        models.EtudiantDB.groupes.any(models.GroupeDB.id.in_(ids_lies))
    ).order_by(models.EtudiantDB.nom, models.EtudiantDB.prenom).all()
    resultat = {i: [] for i in cibles}
    for e in candidats:
        mes_groupes = [g.nom_groupe for g in e.groupes]
        for i, nom in cibles.items():
            if etudiant_concerne(mes_groupes, nom):
                resultat[i].append(e)
    return resultat


def etudiants_du_groupe(db: Session, id_groupe):
    """Étudiants attendus aux cours de ce groupe (voir services/groupes.py)."""
    return etudiants_par_groupe(db, [id_groupe]).get(id_groupe, [])


def presences_bloc(db: Session, bloc: Bloc):
    """Feuille d'émargement détaillée d'un bloc.
    Retourne (liste des étudiants, badges hors liste, compteur par statut)."""
    bips = defaultdict(list)
    for p in db.query(models.PointageDB).filter(
        models.PointageDB.id_seance.in_(bloc.ids)
    ).order_by(models.PointageDB.timestamp).all():
        bips[p.nfc_uid].append(p.timestamp)

    liste, uids_connus = [], set()
    compteur = {PRESENT: 0, RETARD: 0, ABSENT: 0}
    for etudiant in etudiants_du_groupe(db, bloc.groupe.id) if bloc.groupe else []:
        uid = etudiant.carte.nfc_uid if etudiant.carte else None
        heures = bips.get(uid, []) if uid else []
        if uid:
            uids_connus.add(uid)
        statut = statut_depuis(heures[0] if heures else None, bloc.debut)
        compteur[statut] += 1
        liste.append({
            "etudiant": etudiant,
            "badge": uid,
            "statut": statut,
            "arrivee": heures[0] if heures else None,
            "sortie": heure_sortie(heures),
        })

    # Badges qui ont bipé mais ne sont pas dans la liste du groupe
    hors_liste = []
    for uid, heures in bips.items():
        if uid in uids_connus:
            continue
        carte = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == uid).first()
        hors_liste.append({"badge": uid, "etudiant": carte.etudiant if carte else None, "heure": heures[0]})

    return liste, hors_liste, compteur


def resumes_blocs(db: Session, blocs) -> dict:
    """Compteurs de présence de plusieurs blocs en peu de requêtes
    (utilisé par la grille EDT et le tableau de bord).
    Retourne {bloc.id: {"effectif", "present", "retard", "absent", "etat"}}."""
    if not blocs:
        return {}
    maintenant = maintenant_paris()

    # Étudiants attendus et leurs cartes, pour chaque groupe concerné
    effectifs = defaultdict(int)
    cartes_groupe = defaultdict(set)
    for id_groupe, etudiants in etudiants_par_groupe(db, {b.groupe.id for b in blocs if b.groupe}).items():
        for e in etudiants:
            effectifs[id_groupe] += 1
            if e.carte:
                cartes_groupe[id_groupe].add(e.carte.nfc_uid)

    # Premier bip de chaque carte dans chaque séance
    tous_ids = [i for b in blocs for i in b.ids]
    premiers = defaultdict(dict)
    for id_seance, uid, premier in db.query(
        models.PointageDB.id_seance, models.PointageDB.nfc_uid, func.min(models.PointageDB.timestamp)
    ).filter(models.PointageDB.id_seance.in_(tous_ids)).group_by(
        models.PointageDB.id_seance, models.PointageDB.nfc_uid
    ).all():
        premiers[id_seance][uid] = premier

    resultat = {}
    for b in blocs:
        id_groupe = b.groupe.id if b.groupe else None
        premier_par_uid = {}
        for id_seance in b.ids:
            for uid, t in premiers[id_seance].items():
                if uid not in premier_par_uid or t < premier_par_uid[uid]:
                    premier_par_uid[uid] = t
        present = retard = 0
        for uid in cartes_groupe[id_groupe]:
            statut = statut_depuis(premier_par_uid.get(uid), b.debut)
            present += statut == PRESENT
            retard += statut == RETARD
        effectif = effectifs[id_groupe]
        resultat[b.id] = {
            "effectif": effectif,
            "present": present,
            "retard": retard,
            "absent": effectif - present - retard,
            "etat": b.etat(maintenant),
        }
    return resultat


def taux(present, retard, total):
    """Taux de présence en % (un retard compte comme présent)."""
    return round(100 * (present + retard) / total) if total else None


# ==========================================
# Suivi des absences
# ==========================================

def _blocs_commences(db: Session, ids_groupes, debut: datetime, fin: datetime):
    """Blocs des groupes donnés sur une période, terminés ou en cours (on peut badger
    jusqu'à AVANCE_POINTAGE_MIN minutes avant le début). Voir pas_encore_compte()."""
    if not ids_groupes:
        return []
    limite = maintenant_paris() + timedelta(minutes=AVANCE_POINTAGE_MIN)
    seances = db.query(models.SeanceDB).filter(
        models.SeanceDB.id_groupe.in_(ids_groupes),
        models.SeanceDB.date_debut >= debut,
        models.SeanceDB.date_debut <= min(fin, limite),
    ).all()
    return construire_blocs(db, seances)


def pas_encore_compte(bloc, heures, maintenant) -> bool:
    """Cours pas encore terminé et étudiant pas encore badgé : il peut encore arriver,
    on ne le compte pas absent (ni dans le nombre de cours) avant la fin du cours.
    S'il a badgé, il est compté tout de suite (présent ou en retard)."""
    return not heures and bloc.fin > maintenant


def _bips_par_seance(db: Session, uids, ids_seances):
    """{(uid, id_seance): [timestamps triés]}"""
    bips = defaultdict(list)
    if not uids or not ids_seances:
        return bips
    for p in db.query(models.PointageDB).filter(
        models.PointageDB.nfc_uid.in_(uids),
        models.PointageDB.id_seance.in_(ids_seances),
    ).order_by(models.PointageDB.timestamp).all():
        bips[(p.nfc_uid, p.id_seance)].append(p.timestamp)
    return bips


def historique_etudiant(db: Session, etudiant, debut: datetime, fin: datetime):
    """Cours d'un étudiant sur une période, avec son statut (cours terminés,
    plus le cours en cours s'il a déjà badgé)."""
    noms = [g.nom_groupe for g in etudiant.groupes]
    blocs = [b for b in _blocs_commences(db, ids_groupes_lies(db, noms), debut, fin)
             if b.groupe and etudiant_concerne(noms, b.groupe.nom_groupe)]
    uid = etudiant.carte.nfc_uid if etudiant.carte else None
    bips = _bips_par_seance(db, [uid] if uid else [], [i for b in blocs for i in b.ids])

    maintenant = maintenant_paris()
    lignes = []
    for b in sorted(blocs, key=lambda b: b.debut, reverse=True):
        heures = sorted(t for i in b.ids for t in bips.get((uid, i), []))
        if pas_encore_compte(b, heures, maintenant):
            continue
        lignes.append({
            "bloc": b,
            "statut": statut_depuis(heures[0] if heures else None, b.debut),
            "arrivee": heures[0] if heures else None,
            "sortie": heure_sortie(heures),
        })
    return lignes


def bilan_etudiants(db: Session, etudiants, debut: datetime, fin: datetime):
    """Nombre de présences / retards / absences de chaque étudiant sur une période."""
    ids_groupes = ids_groupes_lies(db, {g.nom_groupe for e in etudiants for g in e.groupes})
    blocs = _blocs_commences(db, ids_groupes, debut, fin)
    uids = [e.carte.nfc_uid for e in etudiants if e.carte]
    bips = _bips_par_seance(db, uids, [i for b in blocs for i in b.ids])

    maintenant = maintenant_paris()
    bilan = []
    for e in etudiants:
        mes_groupes = [g.nom_groupe for g in e.groupes]
        uid = e.carte.nfc_uid if e.carte else None
        compte = {PRESENT: 0, RETARD: 0, ABSENT: 0}
        for b in blocs:
            if not b.groupe or not etudiant_concerne(mes_groupes, b.groupe.nom_groupe):
                continue
            heures = [t for i in b.ids for t in bips.get((uid, i), [])]
            if pas_encore_compte(b, heures, maintenant):
                continue
            compte[statut_depuis(min(heures) if heures else None, b.debut)] += 1
        total = sum(compte.values())
        bilan.append({
            "etudiant": e,
            "cours": total,
            "present": compte[PRESENT],
            "retard": compte[RETARD],
            "absent": compte[ABSENT],
            "taux": taux(compte[PRESENT], compte[RETARD], total),
        })
    return bilan
