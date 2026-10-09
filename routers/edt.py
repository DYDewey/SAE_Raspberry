"""Emploi du temps (grille semaine) et feuilles d'émargement."""
import zlib
from datetime import timedelta

import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

import models
from config import TOLERANCE_RETARD_MIN
from database import get_db
from services import ical
from services.export import XLSX, excel_avec_entete
from services.groupes import sont_lies
from services.presences import (ABSENT, PRESENT, RETARD, bloc_de_seance, construire_blocs, presences_bloc,
                                resumes_blocs, taux)
from services.temps import debut_semaine, jour_fr, lire_date, maintenant_paris
from web import PasAutorise, admin_requis, connexion_requise, flash, groupes_par_promo, prof_connecte, render, templates

# Accessible aux profs : ils ne voient que leurs cours (voir prof_connecte)
router = APIRouter(prefix="/admin", dependencies=[Depends(connexion_requise)], tags=["Emploi du temps"])

PX_PAR_MINUTE = 1.1          # hauteur d'une minute dans la grille (1h = 66 px)
COULEURS = [                 # (fond, bordure) - une couleur stable par matière
    ("#e7f0ff", "#3b6fd8"), ("#e6f6ee", "#2e9d62"), ("#fff1e0", "#e08a1e"),
    ("#f3e8ff", "#8a4fd8"), ("#ffe8ec", "#d8435f"), ("#e3f7f8", "#1f9aa5"),
    ("#fdf6d8", "#b8960f"), ("#eceff3", "#5b6675"), ("#fde9f7", "#c2409b"),
    ("#e9f5dc", "#5f9b25"),
]


def couleur_cours(code: str):
    return COULEURS[zlib.crc32(code.encode()) % len(COULEURS)]


def groupes_lies(groupe, tous_les_groupes):
    """Groupes affichés pour une classe : elle-même, ses groupes parents (CM de la
    promo) et ses sous-groupes (BUT3-TD3 montre BUT3-TD3-APP et BUT3-TD3-PB)."""
    return [g.id for g in tous_les_groupes if sont_lies(g.nom_groupe, groupe.nom_groupe)]


class CoursAffiche:
    """Un rectangle de la grille. Un CM commun à plusieurs groupes (une séance par
    groupe en base) est affiché une seule fois, avec la somme des présences."""
    def __init__(self, blocs, resumes):
        self.blocs = sorted(blocs, key=lambda b: b.nom_groupe)
        self.bloc = self.blocs[0]
        self.debut, self.fin = self.bloc.debut, self.bloc.fin
        self.groupes = ", ".join(b.nom_groupe for b in self.blocs)
        self.ids = ",".join(str(b.id) for b in self.blocs)
        rs = [resumes[b.id] for b in self.blocs]
        self.resume = {k: sum(r[k] for r in rs) for k in ("effectif", "present", "retard", "absent")}
        self.resume["etat"] = rs[0]["etat"]


def regrouper(blocs, resumes):
    par_cle = {}
    for b in blocs:
        cle = (b.code, b.nom_salle, b.nom_prof, b.debut, b.fin)
        par_cle.setdefault(cle, []).append(b)
    return [CoursAffiche(liste, resumes) for liste in par_cle.values()]


def disposer(blocs):
    """Place les cours qui se chevauchent côte à côte (colonnes) dans une journée.
    Retourne [(bloc, colonne, nb_colonnes)]."""
    resultat, groupe_chevauchement, colonnes_fin, fin_groupe = [], [], [], None

    def cloturer():
        for b, col in groupe_chevauchement:
            resultat.append((b, col, len(colonnes_fin)))

    for b in sorted(blocs, key=lambda b: (b.debut, b.fin)):
        if fin_groupe is not None and b.debut >= fin_groupe:
            cloturer()
            groupe_chevauchement, colonnes_fin, fin_groupe = [], [], None
        col = next((i for i, fin in enumerate(colonnes_fin) if fin <= b.debut), None)
        if col is None:
            colonnes_fin.append(b.fin)
            col = len(colonnes_fin) - 1
        else:
            colonnes_fin[col] = b.fin
        groupe_chevauchement.append((b, col))
        fin_groupe = b.fin if fin_groupe is None else max(fin_groupe, b.fin)
    cloturer()
    return resultat


@router.get("/edt")
def emploi_du_temps(request: Request, semaine: str = None, groupe: int = None, prof: int = None,
                    salle: int = None, db: Session = Depends(get_db)):
    maintenant = maintenant_paris()
    lundi = debut_semaine(lire_date(semaine, maintenant))
    if prof_connecte(request):
        # Un prof connecté ne voit que ses propres cours, toutes classes confondues
        prof, groupe, salle = prof_connecte(request), 0, None

    # La classe choisie est mémorisée pour les prochaines visites (0 = toutes)
    if groupe is None:
        groupe = request.session.get("edt_groupe")
    else:
        request.session["edt_groupe"] = groupe

    tous_groupes = db.query(models.GroupeDB).all()
    groupe_choisi = db.get(models.GroupeDB, groupe) if groupe else None

    requete = db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut >= lundi,
        models.SeanceDB.date_debut < lundi + timedelta(days=7),
    )
    if groupe_choisi:
        requete = requete.filter(models.SeanceDB.id_groupe.in_(groupes_lies(groupe_choisi, tous_groupes)))
    if prof:
        requete = requete.filter(models.SeanceDB.id_prof == prof)
    if salle:
        requete = requete.filter(models.SeanceDB.id_salle == salle)

    seances = requete.all()
    # Les créneaux qui se suivent pour un même cours (même intitulé, groupe, salle et prof,
    # ex : 13h-14h30 + 14h30-16h + 16h-17h30) forment un seul bloc dans la grille,
    # comme pour le calcul des présences
    blocs = construire_blocs(db, seances)
    resumes = resumes_blocs(db, blocs)

    # Plage horaire affichée : 8h-19h, élargie si un cours déborde
    h_debut = min([8] + [b.debut.hour for b in blocs])
    h_fin = max([19] + [b.fin.hour + (1 if b.fin.minute else 0) for b in blocs])

    nb_jours = 6 if any(b.debut.weekday() == 5 for b in blocs) else 5
    jours = []
    for i in range(nb_jours):
        jour = lundi + timedelta(days=i)
        cours = []
        du_jour = regrouper([b for b in blocs if b.debut.date() == jour.date()], resumes)
        for ca, col, nb_col in disposer(du_jour):
            b, r = ca.bloc, ca.resume
            fond, bordure = couleur_cours(b.code)
            debut_min = (b.debut.hour - h_debut) * 60 + b.debut.minute
            cours.append({
                "bloc": b,
                "groupes": ca.groupes,
                "ids": ca.ids,
                "resume": r,
                "taux": taux(r["present"], r["retard"], r["effectif"]),
                "top": round(debut_min * PX_PAR_MINUTE),
                "hauteur": round((b.fin - b.debut).total_seconds() / 60 * PX_PAR_MINUTE) - 2,
                "gauche": 100 * col / nb_col,
                "largeur": 100 / nb_col,
                "fond": fond,
                "bordure": bordure,
            })
        jours.append({"date": jour, "titre": jour_fr(jour), "aujourdhui": jour.date() == maintenant.date(),
                      "cours": cours})

    ligne_maintenant = None
    if lundi <= maintenant < lundi + timedelta(days=nb_jours) and h_debut <= maintenant.hour < h_fin:
        ligne_maintenant = round(((maintenant.hour - h_debut) * 60 + maintenant.minute) * PX_PAR_MINUTE)

    return render(
        request, "edt/semaine.html", actif="edt",
        jours=jours,
        heures=list(range(h_debut, h_fin)),
        hauteur_grille=round((h_fin - h_debut) * 60 * PX_PAR_MINUTE),
        px_heure=round(60 * PX_PAR_MINUTE),
        ligne_maintenant=ligne_maintenant,
        lundi=lundi,
        dimanche=lundi + timedelta(days=6),
        semaine_prec=(lundi - timedelta(days=7)).strftime("%Y-%m-%d"),
        semaine_suiv=(lundi + timedelta(days=7)).strftime("%Y-%m-%d"),
        numero_semaine=lundi.isocalendar()[1],
        groupes=groupes_par_promo(tous_groupes),
        professeurs=db.query(models.ProfesseurDB).order_by(models.ProfesseurDB.nom).all(),
        salles=db.query(models.SalleDB).order_by(models.SalleDB.nom_salle).all(),
        groupe_choisi=groupe_choisi,
        # Ex : BUT3-TD3-PB choisi -> proposer d'afficher toute la classe BUT3-TD3
        classe_entiere=next((g for g in tous_groupes if groupe_choisi and groupe_choisi.nom_groupe.count("-") >= 2
                             and g.nom_groupe == "-".join(groupe_choisi.nom_groupe.split("-")[:2])), None),
        prof_choisi=prof,
        salle_choisie=salle,
        nb_cours=sum(len(j["cours"]) for j in jours),
    )


@router.post("/edt/synchroniser", dependencies=[Depends(admin_requis)])
def synchroniser_edt(request: Request, db: Session = Depends(get_db)):
    try:
        r = ical.telecharger_et_importer(db)
        flash(request, f"Emploi du temps synchronisé : {r['crees']} cours ajouté(s), "
                       f"{r['modifies']} mis à jour, {r['supprimes']} supprimé(s).")
    except Exception as e:
        db.rollback()
        flash(request, f"Échec de la synchronisation de l'emploi du temps : {e}", "danger")
    return RedirectResponse(url="/admin/edt", status_code=303)


# ==========================================
# Émargement d'un cours
# ==========================================

def _contexte_emargement(db: Session, seance_id: int, id_prof=None):
    """id_prof : prof connecté (None pour l'admin), qui n'a accès qu'à ses propres cours."""
    seance = db.get(models.SeanceDB, seance_id)
    if not seance:
        return None
    if id_prof is not None and seance.id_prof != id_prof:
        raise PasAutorise()
    bloc = bloc_de_seance(db, seance)
    liste, hors_liste, compteur = presences_bloc(db, bloc)
    return {
        "bloc": bloc,
        "etat": bloc.etat(),
        "liste": liste,
        "hors_liste": hors_liste,
        "compteur": compteur,
        "taux": taux(compteur["Présent"], compteur["En retard"], len(liste)),
        "limite_retard": bloc.debut + timedelta(minutes=TOLERANCE_RETARD_MIN),
    }


@router.get("/seances")
def ancienne_page_seances():
    return RedirectResponse(url="/admin/edt", status_code=303)


def _contextes(db: Session, seance_id: int, avec: str, id_prof=None):
    """Émargement du cours demandé + des autres groupes du même CM (?avec=12,13)."""
    ids = [seance_id] + [int(i) for i in (avec or "").split(",") if i.strip().isdigit() and int(i) != seance_id]
    return [c for c in (_contexte_emargement(db, i, id_prof) for i in ids) if c]


@router.get("/seances/{seance_id}")
def page_emargement(seance_id: int, request: Request, avec: str = "", db: Session = Depends(get_db)):
    contextes = _contextes(db, seance_id, avec, prof_connecte(request))
    if not contextes:
        flash(request, "Ce cours n'existe plus (l'emploi du temps a peut-être changé).", "warning")
        return RedirectResponse(url="/admin/edt", status_code=303)
    return render(request, "edt/emargement.html", actif="edt", contextes=contextes, bloc=contextes[0]["bloc"])


@router.get("/seances/{seance_id}/panneau")
def panneau_emargement(seance_id: int, request: Request, avec: str = "", db: Session = Depends(get_db)):
    """Même contenu que la page, sans le menu : chargé dans le panneau latéral de l'EDT."""
    # TemplateResponse directement (et pas render) pour ne pas consommer les messages flash
    contextes = _contextes(db, seance_id, avec, prof_connecte(request))
    if not contextes:
        return templates.TemplateResponse(request=request, name="edt/_introuvable.html")
    return templates.TemplateResponse(request=request, name="edt/_emargements.html",
                                      context={"panneau": True, "contextes": contextes, "avec": avec,
                                               "est_prof": prof_connecte(request) is not None})


@router.post("/seances/{seance_id}/manuel")
def statut_manuel(seance_id: int, request: Request, etudiant: int = Form(...), statut: str = Form(""),
                  db: Session = Depends(get_db)):
    """Le prof valide un étudiant à la main (boîtier en panne, carte oubliée...).
    statut vide : on revient au statut calculé à partir des bips."""
    if statut not in (PRESENT, RETARD, ABSENT, ""):
        raise HTTPException(status_code=400, detail="Statut inconnu")
    seance = db.get(models.SeanceDB, seance_id)
    if not seance or not db.get(models.EtudiantDB, etudiant):
        raise HTTPException(status_code=404, detail="Cours ou étudiant introuvable")
    if prof_connecte(request) is not None and seance.id_prof != prof_connecte(request):
        raise PasAutorise()
    bloc = bloc_de_seance(db, seance)
    db.query(models.PresenceManuelleDB).filter(
        models.PresenceManuelleDB.id_etudiant == etudiant,
        models.PresenceManuelleDB.id_seance.in_(bloc.ids),
    ).delete(synchronize_session=False)
    if statut:
        db.add(models.PresenceManuelleDB(id_seance=bloc.id, id_etudiant=etudiant, statut=statut,
                                         modifie_le=maintenant_paris()))
    db.commit()
    return Response(status_code=204)


@router.get("/seances/{seance_id}/export")
def export_emargement(seance_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = _contexte_emargement(db, seance_id, prof_connecte(request))
    if not ctx:
        return RedirectResponse(url="/admin/edt", status_code=303)
    bloc, c = ctx["bloc"], ctx["compteur"]

    df = pd.DataFrame([{
        "N° Étudiant": p["etudiant"].numero_etudiant,
        "Nom": p["etudiant"].nom,
        "Prénom": p["etudiant"].prenom,
        "Badge NFC": p["badge"] or "Non attribué",
        "Arrivée": p["arrivee"].strftime("%H:%M") if p["arrivee"] else "",
        "Sortie": p["sortie"].strftime("%H:%M") if p["sortie"] else "",
        "Statut": p["statut"] + (" (validé à la main)" if p["manuel"] else ""),
    } for p in ctx["liste"]], columns=["N° Étudiant", "Nom", "Prénom", "Badge NFC", "Arrivée", "Sortie", "Statut"])

    entete = [
        "FEUILLE D'ÉMARGEMENT - IUT",
        f"Cours : {bloc.libelle}",
        f"Professeur : {bloc.nom_prof or 'N/A'}",
        f"Date : {jour_fr(bloc.debut, avec_annee=True)} de {bloc.debut:%H:%M} à {bloc.fin:%H:%M} | Salle : {bloc.nom_salle}",
        f"Groupe : {bloc.nom_groupe}",
        f"Présents : {c['Présent']} | En retard : {c['En retard']} | Absents : {c['Absent']} "
        f"(retard après {ctx['limite_retard']:%H:%M})",
    ]
    fichier = excel_avec_entete(df, "Emargement", entete)
    nom = f"emargement_{bloc.debut:%Y-%m-%d_%Hh%M}_{bloc.nom_groupe}.xlsx"
    return StreamingResponse(fichier, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename={nom}"})
