"""Étudiants : liste, import Excel, cartes NFC, fiche individuelle et suivi des absences."""
from datetime import timedelta

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
import models
from database import get_db
from services import scan
from services.etudiants import associer_carte, importer_etudiants
from services.export import XLSX, excel_avec_entete
from services.presences import bilan_etudiants, historique_etudiant, taux
from services.temps import debut_annee_universitaire, lire_date, maintenant_paris
from web import admin_requis, flash, groupes_par_promo, render

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_requis)], tags=["Étudiants"])


def _groupes(db):
    return db.query(models.GroupeDB).order_by(models.GroupeDB.nom_groupe).all()


def _periode(du: str, au: str):
    """Période de suivi : par défaut depuis le 1er septembre jusqu'à aujourd'hui."""
    debut = lire_date(du, debut_annee_universitaire())
    fin = lire_date(au, maintenant_paris()).replace(hour=23, minute=59, second=59)
    return debut, fin


# ==========================================
# Liste et import
# ==========================================

@router.get("/etudiants")
def liste_etudiants(request: Request, groupe: int = None, q: str = "", sans_carte: bool = False,
                    db: Session = Depends(get_db)):
    requete = db.query(models.EtudiantDB)
    if groupe:
        requete = requete.filter(models.EtudiantDB.groupes.any(models.GroupeDB.id == groupe))
    if q.strip():
        motif = f"%{q.strip()}%"
        requete = requete.filter(or_(models.EtudiantDB.nom.ilike(motif), models.EtudiantDB.prenom.ilike(motif),
                                     models.EtudiantDB.numero_etudiant.ilike(motif)))
    if sans_carte:
        requete = requete.filter(~models.EtudiantDB.carte.has())
    etudiants = requete.order_by(models.EtudiantDB.nom, models.EtudiantDB.prenom).all()

    return render(request, "etudiants/liste.html", actif="etudiants",
                  etudiants=etudiants, groupes=groupes_par_promo(_groupes(db)),
                  groupe_choisi=groupe, q=q, sans_carte=sans_carte,
                  total=db.query(models.EtudiantDB).count(),
                  total_sans_carte=db.query(models.EtudiantDB).filter(~models.EtudiantDB.carte.has()).count(),
                  **_contexte_scan(request, db))


@router.post("/etudiants/import")
def import_excel(request: Request, fichier: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        r = importer_etudiants(db, fichier.file.read())
        flash(request, f"Import terminé : {r['ajoutes']} étudiant(s) ajouté(s), {r['mis_a_jour']} mis à jour.")
    except ValueError as e:
        db.rollback()
        flash(request, str(e), "danger")
    except Exception as e:
        db.rollback()
        flash(request, f"Fichier illisible : {e}", "danger")
    return RedirectResponse(url="/admin/etudiants", status_code=303)


@router.post("/etudiants/{etudiant_id}/carte")
def modifier_carte(etudiant_id: int, request: Request, nfc_uid: str = Form(""), retour: str = Form(""),
                   db: Session = Depends(get_db)):
    etudiant = db.get(models.EtudiantDB, etudiant_id)
    if etudiant:
        flash(request, associer_carte(db, etudiant, nfc_uid))
    return RedirectResponse(url=retour if retour.startswith("/admin") else "/admin/etudiants", status_code=303)


# ==========================================
# Scan d'une carte sur un boîtier (bouton "Scanner")
# ==========================================

def _contexte_scan(request: Request, db: Session) -> dict:
    """Boîtiers proposés pour le scan. Par défaut : le dernier utilisé, sinon un
    boîtier sans professeur (boîtier du secrétariat), sinon le premier."""
    seuil = maintenant_paris() - timedelta(minutes=config.BOITIER_EN_LIGNE_MIN)
    boitiers = db.query(models.BoitierDB).order_by(models.BoitierDB.device_id).all()
    ids = [b.device_id for b in boitiers]
    en_ligne = {b.device_id for b in boitiers if b.derniere_synchro and b.derniere_synchro >= seuil}
    choisi = request.session.get("scan_boitier")
    if choisi not in ids:
        # Priorité : boîtier en ligne sans professeur (accueil), puis n'importe quel boîtier en ligne
        choisi = next((b.device_id for b in boitiers if b.device_id in en_ligne and not b.id_prof),
                      next((i for i in ids if i in en_ligne), ids[0] if ids else None))
    return {
        "boitiers_scan": [{"id": b.device_id,
                           "en_ligne": b.device_id in en_ligne,
                           "prof": f"{b.professeur.nom} {b.professeur.prenom}" if b.professeur else ""}
                          for b in boitiers],
        "boitier_scan": choisi,
    }


@router.post("/scan/demarrer")
def scan_demarrer(request: Request, device_id: str = Form(...), etudiant_id: int = Form(0),
                  db: Session = Depends(get_db)):
    if not db.get(models.BoitierDB, device_id):
        return JSONResponse({"statut": "erreur", "message": "Boîtier inconnu"}, status_code=400)
    request.session["scan_boitier"] = device_id
    scan.demarrer(device_id, etudiant_id or None)
    return JSONResponse({"statut": "attente", "restant": scan.DUREE_ATTENTE_S})


@router.get("/scan/etat")
def scan_etat(db: Session = Depends(get_db)):
    return JSONResponse(scan.verifier(db))


@router.post("/scan/annuler")
def scan_annuler():
    scan.annuler()
    return JSONResponse({"statut": "aucun"})


# ==========================================
# Ajout / modification / suppression
# ==========================================

@router.get("/etudiants/nouveau")
def page_nouvel_etudiant(request: Request, db: Session = Depends(get_db)):
    return render(request, "etudiants/formulaire.html", actif="etudiants", etudiant=None,
                  groupes=groupes_par_promo(_groupes(db)), **_contexte_scan(request, db))


@router.post("/etudiants/nouveau")
def creer_etudiant(request: Request, numero_etudiant: str = Form(...), nom: str = Form(...),
                   prenom: str = Form(...), groupes_ids: list[int] = Form([]), nfc_uid: str = Form(""),
                   db: Session = Depends(get_db)):
    if db.query(models.EtudiantDB).filter(models.EtudiantDB.numero_etudiant == numero_etudiant.strip()).first():
        flash(request, f"Le numéro {numero_etudiant} existe déjà.", "danger")
        return RedirectResponse(url="/admin/etudiants/nouveau", status_code=303)
    etudiant = models.EtudiantDB(
        numero_etudiant=numero_etudiant.strip(), nom=nom.strip(), prenom=prenom.strip(),
        groupes=db.query(models.GroupeDB).filter(models.GroupeDB.id.in_(groupes_ids)).all(),
    )
    db.add(etudiant)
    db.commit()
    associer_carte(db, etudiant, nfc_uid)
    flash(request, f"{etudiant.prenom} {etudiant.nom} a été ajouté(e).")
    return RedirectResponse(url="/admin/etudiants", status_code=303)


@router.get("/etudiants/{etudiant_id}/modifier")
def page_modifier_etudiant(etudiant_id: int, request: Request, db: Session = Depends(get_db)):
    etudiant = db.get(models.EtudiantDB, etudiant_id)
    if not etudiant:
        return RedirectResponse(url="/admin/etudiants", status_code=303)
    return render(request, "etudiants/formulaire.html", actif="etudiants", etudiant=etudiant,
                  groupes=groupes_par_promo(_groupes(db)), **_contexte_scan(request, db))


@router.post("/etudiants/{etudiant_id}/modifier")
def modifier_etudiant(etudiant_id: int, request: Request, numero_etudiant: str = Form(...),
                      nom: str = Form(...), prenom: str = Form(...), groupes_ids: list[int] = Form([]),
                      nfc_uid: str = Form(""), db: Session = Depends(get_db)):
    etudiant = db.get(models.EtudiantDB, etudiant_id)
    if not etudiant:
        return RedirectResponse(url="/admin/etudiants", status_code=303)
    etudiant.numero_etudiant = numero_etudiant.strip()
    etudiant.nom = nom.strip()
    etudiant.prenom = prenom.strip()
    etudiant.groupes = db.query(models.GroupeDB).filter(models.GroupeDB.id.in_(groupes_ids)).all()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, f"Le numéro {numero_etudiant} est déjà utilisé par un autre étudiant.", "danger")
        return RedirectResponse(url=f"/admin/etudiants/{etudiant_id}/modifier", status_code=303)
    message = associer_carte(db, etudiant, nfc_uid)
    flash(request, f"Fiche de {etudiant.prenom} {etudiant.nom} enregistrée. {message}".strip())
    return RedirectResponse(url=f"/admin/etudiants/{etudiant_id}", status_code=303)


@router.post("/etudiants/{etudiant_id}/supprimer")
def supprimer_etudiant(etudiant_id: int, request: Request, db: Session = Depends(get_db)):
    etudiant = db.get(models.EtudiantDB, etudiant_id)
    if etudiant:
        flash(request, f"{etudiant.prenom} {etudiant.nom} a été supprimé(e).", "info")
        db.delete(etudiant)   # la carte est supprimée avec (cascade)
        db.commit()
    return RedirectResponse(url="/admin/etudiants", status_code=303)


# ==========================================
# Fiche étudiant (historique)
# ==========================================

@router.get("/etudiants/{etudiant_id}")
def fiche_etudiant(etudiant_id: int, request: Request, du: str = None, au: str = None,
                   db: Session = Depends(get_db)):
    etudiant = db.get(models.EtudiantDB, etudiant_id)
    if not etudiant:
        flash(request, "Étudiant introuvable.", "warning")
        return RedirectResponse(url="/admin/etudiants", status_code=303)
    debut, fin = _periode(du, au)
    historique = historique_etudiant(db, etudiant, debut, fin)
    compte = {s: sum(1 for h in historique if h["statut"] == s) for s in ("Présent", "En retard", "Absent")}
    return render(request, "etudiants/fiche.html", actif="etudiants", etudiant=etudiant,
                  historique=historique, compte=compte,
                  taux=taux(compte["Présent"], compte["En retard"], len(historique)),
                  du=debut.strftime("%Y-%m-%d"), au=fin.strftime("%Y-%m-%d"))


@router.get("/etudiants/{etudiant_id}/export")
def export_fiche(etudiant_id: int, du: str = None, au: str = None, db: Session = Depends(get_db)):
    etudiant = db.get(models.EtudiantDB, etudiant_id)
    if not etudiant:
        return RedirectResponse(url="/admin/etudiants", status_code=303)
    debut, fin = _periode(du, au)
    historique = historique_etudiant(db, etudiant, debut, fin)
    df = pd.DataFrame([{
        "Date": h["bloc"].debut.strftime("%d/%m/%Y"),
        "Horaire": f"{h['bloc'].debut:%H:%M}-{h['bloc'].fin:%H:%M}",
        "Cours": h["bloc"].libelle,
        "Groupe": h["bloc"].nom_groupe,
        "Salle": h["bloc"].nom_salle,
        "Arrivée": h["arrivee"].strftime("%H:%M") if h["arrivee"] else "",
        "Statut": h["statut"],
    } for h in historique], columns=["Date", "Horaire", "Cours", "Groupe", "Salle", "Arrivée", "Statut"])
    nb = {s: sum(1 for h in historique if h["statut"] == s) for s in ("Présent", "En retard", "Absent")}
    entete = [
        f"SUIVI D'ASSIDUITÉ - {etudiant.nom.upper()} {etudiant.prenom}",
        f"N° étudiant : {etudiant.numero_etudiant} | Groupes : {', '.join(g.nom_groupe for g in etudiant.groupes)}",
        f"Période : du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}",
        f"Présences : {nb['Présent']} | Retards : {nb['En retard']} | Absences : {nb['Absent']}",
    ]
    nom = f"assiduite_{etudiant.numero_etudiant}_{etudiant.nom}.xlsx"
    return StreamingResponse(excel_avec_entete(df, "Assiduité", entete), media_type=XLSX,
                             headers={"Content-Disposition": f"attachment; filename={nom}"})


# ==========================================
# Suivi des absences par classe
# ==========================================

def _bilan(db, groupe, du, au):
    debut, fin = _periode(du, au)
    requete = db.query(models.EtudiantDB)
    if groupe:
        requete = requete.filter(models.EtudiantDB.groupes.any(models.GroupeDB.id == groupe))
    bilan = bilan_etudiants(db, requete.all(), debut, fin)
    bilan.sort(key=lambda b: (-b["absent"], -b["retard"], b["etudiant"].nom))
    return bilan, debut, fin


@router.get("/absences")
def suivi_absences(request: Request, groupe: int = None, du: str = None, au: str = None,
                   db: Session = Depends(get_db)):
    if groupe is None:
        groupe = request.session.get("edt_groupe")
    bilan, debut, fin = _bilan(db, groupe, du, au)
    total = {k: sum(b[k] for b in bilan) for k in ("cours", "present", "retard", "absent")}
    return render(request, "absences.html", actif="absences", bilan=bilan, total=total,
                  taux_global=taux(total["present"], total["retard"], total["cours"]),
                  groupes=groupes_par_promo(_groupes(db)), groupe_choisi=groupe,
                  du=debut.strftime("%Y-%m-%d"), au=fin.strftime("%Y-%m-%d"))


@router.get("/absences/export")
def export_absences(groupe: int = None, du: str = None, au: str = None, db: Session = Depends(get_db)):
    bilan, debut, fin = _bilan(db, groupe, du, au)
    df = pd.DataFrame([{
        "N° Étudiant": b["etudiant"].numero_etudiant,
        "Nom": b["etudiant"].nom,
        "Prénom": b["etudiant"].prenom,
        "Cours": b["cours"],
        "Présences": b["present"],
        "Retards": b["retard"],
        "Absences": b["absent"],
        "Taux de présence (%)": b["taux"] if b["taux"] is not None else "",
    } for b in bilan], columns=["N° Étudiant", "Nom", "Prénom", "Cours", "Présences", "Retards",
                                "Absences", "Taux de présence (%)"])
    nom_groupe = db.get(models.GroupeDB, groupe).nom_groupe if groupe and db.get(models.GroupeDB, groupe) else "tous"
    entete = [
        "BILAN DES ABSENCES - IUT",
        f"Classe : {nom_groupe}",
        f"Période : du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}",
    ]
    return StreamingResponse(excel_avec_entete(df, "Absences", entete), media_type=XLSX,
                             headers={"Content-Disposition": f"attachment; filename=absences_{nom_groupe}.xlsx"})
