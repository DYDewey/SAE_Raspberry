from fastapi import FastAPI, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from database import engine, SessionLocal, Base
import models
import pandas as pd
import io
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
import requests
from icalendar import Calendar
from datetime import datetime, timedelta
import re
from collections import defaultdict
from zoneinfo import ZoneInfo

# Initialisation du moteur de templates
templates = Jinja2Templates(directory="templates")

# Crée les tables dans PostgreSQL si elles n'existent pas encore
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="API Pointage NFC")

# Dépendance pour récupérer une session BDD propre à chaque requête
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 1. ROUTES DE BASE & API NFC / EXCEL ETUDIANTS
# ==========================================

@app.get("/")
def check_status():
    return {"message": "Le serveur API est opérationnel et connecté à PostgreSQL !"}

@app.post("/api/v1/sync")
def sync_pointages(payload: dict, db: Session = Depends(get_db)):
    device_id = payload.get("device_id", "Inconnu")
    batch = payload.get("batch", [])
    
    uuids_confirmes = []
    for item in batch:
        pointage_uuid = item.get("uuid")
        nfc_uid = item.get("nfc_uid")
        timestamp = item.get("timestamp")

        existing = db.query(models.PointageDB).filter(models.PointageDB.uuid == pointage_uuid).first()
        if not existing:
            nouveau_pointage = models.PointageDB(
                uuid=pointage_uuid,
                nfc_uid=nfc_uid,
                device_id=device_id,
                timestamp=timestamp
            )
            db.add(nouveau_pointage)
            db.commit()
        
        uuids_confirmes.append(pointage_uuid)

    print(f"Boîtier {device_id} : {len(uuids_confirmes)} pointage(s) synchronisé(s).")
    return {"status": "success", "synced_uuids": uuids_confirmes}

@app.post("/api/v1/upload-students")
def upload_students_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = file.file.read()
    df = pd.read_excel(io.BytesIO(contents))
    
    count = 0
    for _, row in df.iterrows():
        num = str(row.get("numero"))
        nom = str(row.get("nom"))
        prenom = str(row.get("prenom"))

        existing = db.query(models.EtudiantDB).filter(models.EtudiantDB.numero_etudiant == num).first()
        if not existing:
            nouveau_etudiant = models.EtudiantDB(numero_etudiant=num, nom=nom, prenom=prenom)
            db.add(nouveau_etudiant)
            count += 1
            
    db.commit()
    return {"status": "success", "etudiants_ajoutes": count}


# ==========================================
# 2. GESTION DES ETUDIANTS (ADMIN)
# ==========================================

@app.get("/admin", response_class=HTMLResponse)
def dashboard_admin(request: Request, id_groupe: int = None, db: Session = Depends(get_db)):
    groupes = db.query(models.GroupeDB).all()
    
    query = db.query(models.EtudiantDB)
    if id_groupe and id_groupe > 0:
        query = query.filter(models.EtudiantDB.groupes.any(models.GroupeDB.id == id_groupe))
        
    etudiants = query.all()
    
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"etudiants": etudiants, "groupes": groupes, "selected_groupe": id_groupe}
    )

@app.post("/admin/upload")
def admin_upload_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    contents = file.file.read()
    df = pd.read_excel(io.BytesIO(contents))
    
    for _, row in df.iterrows():
        num = str(row.get("numero"))
        nom = str(row.get("nom"))
        prenom = str(row.get("prenom"))

        existing = db.query(models.EtudiantDB).filter(models.EtudiantDB.numero_etudiant == num).first()
        if not existing:
            nouveau_etudiant = models.EtudiantDB(numero_etudiant=num, nom=nom, prenom=prenom)
            db.add(nouveau_etudiant)
            
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/groupes")
def admin_create_groupe(nom_groupe: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(models.GroupeDB).filter(models.GroupeDB.nom_groupe == nom_groupe).first()
    if not existing:
        nouveau_groupe = models.GroupeDB(nom_groupe=nom_groupe)
        db.add(nouveau_groupe)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/etudiants/nouveau", response_class=HTMLResponse)
def page_ajouter_etudiant(request: Request, db: Session = Depends(get_db)):
    groupes = db.query(models.GroupeDB).all()
    return templates.TemplateResponse(request=request, name="ajouter_etudiant.html", context={"groupes": groupes})

@app.post("/admin/etudiants/ajouter")
def ajouter_etudiant_manuel(
    numero_etudiant: str = Form(...),
    nom: str = Form(...),
    prenom: str = Form(...),
    groupes_ids: list[int] = Form([]),
    db: Session = Depends(get_db)
):
    existing = db.query(models.EtudiantDB).filter(models.EtudiantDB.numero_etudiant == numero_etudiant).first()
    if not existing:
        groupes = db.query(models.GroupeDB).filter(models.GroupeDB.id.in_(groupes_ids)).all()
        nouveau_etudiant = models.EtudiantDB(
            numero_etudiant=numero_etudiant,
            nom=nom,
            prenom=prenom,
            groupes=groupes
        )
        db.add(nouveau_etudiant)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/etudiants/{etudiant_id}/modifier", response_class=HTMLResponse)
def page_modifier_etudiant(etudiant_id: int, request: Request, db: Session = Depends(get_db)):
    etudiant = db.query(models.EtudiantDB).filter(models.EtudiantDB.id == etudiant_id).first()
    if not etudiant:
        return RedirectResponse(url="/admin", status_code=303)
    groupes = db.query(models.GroupeDB).all()
    return templates.TemplateResponse(
        request=request, 
        name="modifier_etudiant.html", 
        context={"etudiant": etudiant, "groupes": groupes}
    )

@app.post("/admin/etudiants/{etudiant_id}/modifier")
def modifier_etudiant(
    etudiant_id: int,
    numero_etudiant: str = Form(...),
    nom: str = Form(...),
    prenom: str = Form(...),
    groupes_ids: list[int] = Form([]),
    nfc_uid: str = Form(None),
    db: Session = Depends(get_db)
):
    etudiant = db.query(models.EtudiantDB).filter(models.EtudiantDB.id == etudiant_id).first()
    if etudiant:
        etudiant.numero_etudiant = numero_etudiant
        etudiant.nom = nom
        etudiant.prenom = prenom
        
        groupes = db.query(models.GroupeDB).filter(models.GroupeDB.id.in_(groupes_ids)).all()
        etudiant.groupes = groupes
        
        nfc_clean = nfc_uid.strip() if nfc_uid else ""
        if nfc_clean:
            carte_existante = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == nfc_clean).first()
            if carte_existante and carte_existante.id_etudiant != etudiant.id:
                db.delete(carte_existante)
                db.commit()
            
            if etudiant.carte:
                if etudiant.carte.nfc_uid != nfc_clean:
                    db.delete(etudiant.carte)
                    db.commit()
                    db.add(models.CarteDB(nfc_uid=nfc_clean, id_etudiant=etudiant.id))
            else:
                db.add(models.CarteDB(nfc_uid=nfc_clean, id_etudiant=etudiant.id))
        else:
            if etudiant.carte:
                db.delete(etudiant.carte)
                
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/etudiants/{etudiant_id}/supprimer")
def supprimer_etudiant(etudiant_id: int, db: Session = Depends(get_db)):
    etudiant = db.query(models.EtudiantDB).filter(models.EtudiantDB.id == etudiant_id).first()
    if etudiant:
        db.delete(etudiant)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/etudiants/{etudiant_id}/carte")
def update_etudiant_carte(etudiant_id: int, nfc_uid: str = Form(...), db: Session = Depends(get_db)):
    etudiant = db.query(models.EtudiantDB).filter(models.EtudiantDB.id == etudiant_id).first()
    if etudiant:
        nfc_clean = nfc_uid.strip()
        if nfc_clean:
            carte_existante = db.query(models.CarteDB).filter(models.CarteDB.nfc_uid == nfc_clean).first()
            if carte_existante and carte_existante.id_etudiant != etudiant.id:
                db.delete(carte_existante)
                db.commit()
            
            if etudiant.carte:
                if etudiant.carte.nfc_uid != nfc_clean:
                    db.delete(etudiant.carte)
                    db.commit()
                    db.add(models.CarteDB(nfc_uid=nfc_clean, id_etudiant=etudiant.id))
            else:
                db.add(models.CarteDB(nfc_uid=nfc_clean, id_etudiant=etudiant.id))
        else:
            if etudiant.carte:
                db.delete(etudiant.carte)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


# ==========================================
# 3. PROFESSEURS & CONFIG (SALLES, GROUPES)
# ==========================================

@app.get("/admin/professeurs", response_class=HTMLResponse)
def admin_professeurs_page(request: Request, db: Session = Depends(get_db)):
    professeurs = db.query(models.ProfesseurDB).all()
    return templates.TemplateResponse(request=request, name="professeurs.html", context={"professeurs": professeurs})

@app.post("/admin/professeurs/ajouter")
def admin_create_professeur(nom: str = Form(...), prenom: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.nom == nom, models.ProfesseurDB.prenom == prenom).first()
    if not existing:
        db.add(models.ProfesseurDB(nom=nom, prenom=prenom))
        db.commit()
    return RedirectResponse(url="/admin/professeurs", status_code=303)

@app.post("/admin/professeurs/{prof_id}/supprimer")
def supprimer_professeur(prof_id: int, db: Session = Depends(get_db)):
    prof = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.id == prof_id).first()
    if prof:
        db.query(models.SeanceDB).filter(models.SeanceDB.id_prof == prof_id).delete()
        db.delete(prof)
        db.commit()
    return RedirectResponse(url="/admin/professeurs", status_code=303)

@app.post("/admin/groupes/{groupe_id}/supprimer")
def supprimer_groupe(groupe_id: int, db: Session = Depends(get_db)):
    groupe = db.query(models.GroupeDB).filter(models.GroupeDB.id == groupe_id).first()
    if groupe:
        db.query(models.SeanceDB).filter(models.SeanceDB.id_groupe == groupe_id).delete()
        db.delete(groupe)
        db.commit()
    return RedirectResponse(url="/admin/config", status_code=303)

@app.post("/admin/salles/{salle_id}/modifier")
def modifier_salle(salle_id: int, nom_salle: str = Form(...), db: Session = Depends(get_db)):
    salle = db.query(models.SalleDB).filter(models.SalleDB.id == salle_id).first()
    if salle:
        salle.nom_salle = nom_salle
        db.commit()
    return RedirectResponse(url="/admin/config", status_code=303)

@app.post("/admin/salles/{salle_id}/supprimer")
def supprimer_salle(salle_id: int, db: Session = Depends(get_db)):
    salle = db.query(models.SalleDB).filter(models.SalleDB.id == salle_id).first()
    if salle:
        db.delete(salle)
        db.commit()
    return RedirectResponse(url="/admin/config", status_code=303)

@app.get("/admin/config", response_class=HTMLResponse)
def admin_config_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request, 
        name="config.html", 
        context={
            "salles": db.query(models.SalleDB).all(),
            "enseignements": db.query(models.EnseignementDB).all(),
            "professeurs": db.query(models.ProfesseurDB).all(),
            "groupes": db.query(models.GroupeDB).all()
        }
    )


# ==========================================
# 4. SYNCHRONISATION iCAL & EDT / SEANCES
# ==========================================

@app.post("/admin/sync-edt")
def sync_emploi_du_temps(db: Session = Depends(get_db)):
    url = "https://edt.univ-littoral.fr/jsp/custom/modules/plannings/OnEMEVnr.shu"
    try:
        response = requests.get(url)
        response.raise_for_status()
        cal = Calendar.from_ical(response.content)
        
        aujourdhui = datetime.now()
        debut_semaine = aujourdhui - timedelta(days=aujourdhui.weekday())
        debut_semaine = debut_semaine.replace(hour=0, minute=0, second=0, microsecond=0)
        fin_semaine = debut_semaine + timedelta(days=7)
        
        db.query(models.SeanceDB).filter(
            models.SeanceDB.date_debut >= debut_semaine,
            models.SeanceDB.date_debut < fin_semaine
        ).delete()
        db.commit()
        
        for component in cal.walk('vevent'):
            summary = str(component.get('summary', ''))
            description = str(component.get('description', ''))
            location = str(component.get('location', 'Salle Inconnue'))
            dtstart = component.get('dtstart').dt
            dtend = component.get('dtend').dt
            
            if isinstance(dtstart, datetime) and isinstance(dtend, datetime):
                dtstart_naive = dtstart.replace(tzinfo=None) + timedelta(hours=2)
                dtend_naive = dtend.replace(tzinfo=None) + timedelta(hours=2)
                
                if not (debut_semaine <= dtstart_naive < fin_semaine):
                    continue
                
                full_text = f"{summary}\n{description}"
                
                salle = db.query(models.SalleDB).filter(models.SalleDB.nom_salle == location).first()
                if not salle:
                    salle = models.SalleDB(nom_salle=location[:32])
                    db.add(salle)
                    db.commit()
                    db.refresh(salle)
                
                code_cours = summary[:32]
                enseignement = db.query(models.EnseignementDB).filter(models.EnseignementDB.code_cours == code_cours).first()
                if not enseignement:
                    enseignement = models.EnseignementDB(code_cours=code_cours, libelle=summary[:128])
                    db.add(enseignement)
                    db.commit()
                    db.refresh(enseignement)
                
                nom_groupe_trouve = "Groupe Inconnu"
                for ligne in full_text.split('\n'):
                    if "TD" in ligne or "TP" in ligne or "APP" in ligne:
                        match_precis = re.search(r'(BUT\d(?:-[A-Z0-9\-]+)?)', ligne)
                        if match_precis:
                            nom_groupe_trouve = match_precis.group(1)[:16]
                            break
                if nom_groupe_trouve == "Groupe Inconnu":
                    match_groupe = re.search(r'(BUT\d(?:-[A-Z0-9\-]+)?)', full_text)
                    if match_groupe:
                        nom_groupe_trouve = match_groupe.group(1)[:16]
                
                groupe = db.query(models.GroupeDB).filter(models.GroupeDB.nom_groupe == nom_groupe_trouve).first()
                if not groupe:
                    groupe = models.GroupeDB(nom_groupe=nom_groupe_trouve)
                    db.add(groupe)
                    db.commit()
                    db.refresh(groupe)

                prof_nom = "N/A"
                prof_prenom = ""
                for line in description.split('\n'):
                    line_clean = line.strip()
                    if not line_clean or "Exporté" in line_clean or line_clean.startswith("("):
                        continue
                    if any(c.isupper() for c in line_clean) and len(line_clean) > 3 and "BUT" not in line_clean:
                        parts = line_clean.split()
                        if len(parts) >= 2:
                            prof_nom = parts[0]
                            prof_prenom = " ".join(parts[1:])
                            break
                
                if prof_nom == "N/A":
                    professeur = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.nom == "N/A").first()
                    if not professeur:
                        professeur = models.ProfesseurDB(nom="N/A", prenom="")
                        db.add(professeur)
                        db.commit()
                        db.refresh(professeur)
                else:
                    professeur = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.nom == prof_nom).first()
                    if not professeur:
                        professeur = models.ProfesseurDB(nom=prof_nom[:64], prenom=prof_prenom[:64])
                        db.add(professeur)
                        db.commit()
                        db.refresh(professeur)

                db.add(models.SeanceDB(
                    id_enseignement=enseignement.id,
                    id_groupe=groupe.id,
                    id_salle=salle.id,
                    id_prof=professeur.id,
                    date_debut=dtstart_naive,
                    date_fin=dtend_naive
                ))
                
        db.commit()
        return RedirectResponse(url="/admin/seances", status_code=303)
        
    except Exception as e:
        print(f"Erreur lors de la synchro iCal : {e}")
        return RedirectResponse(url="/admin/config", status_code=303)

@app.get("/admin/seances", response_class=HTMLResponse)
def admin_seances_page(
    request: Request, 
    date: str = None, 
    id_groupe: int = None, 
    id_prof: int = None, 
    db: Session = Depends(get_db)
):
    aujourdhui = datetime.now()
    jour_cible = datetime.strptime(date, "%Y-%m-%d") if date else aujourdhui
        
    debut_jour = jour_cible.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_jour = debut_jour + timedelta(days=1)
    
    query = db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut >= debut_jour,
        models.SeanceDB.date_debut < fin_jour
    )
    
    if id_groupe and id_groupe > 0:
        query = query.filter(models.SeanceDB.id_groupe == id_groupe)
    if id_prof and id_prof > 0:
        query = query.filter(models.SeanceDB.id_prof == id_prof)
        
    seances = query.order_by(models.SeanceDB.date_debut.asc()).all()
    
    jours_semaine = defaultdict(lambda: defaultdict(list))
    jours_trad = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}

    for s in seances:
        enseignement = db.query(models.EnseignementDB).filter(models.EnseignementDB.id == s.id_enseignement).first()
        groupe = db.query(models.GroupeDB).filter(models.GroupeDB.id == s.id_groupe).first()
        salle = db.query(models.SalleDB).filter(models.SalleDB.id == s.id_salle).first()
        prof = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.id == s.id_prof).first()
        
        nom_jour = jours_trad[s.date_debut.weekday()]
        date_formatee = f"{nom_jour} {s.date_debut.strftime('%d/%m/%Y')}"
        nom_groupe = groupe.nom_groupe if groupe else "Inconnu"
        
        promo = "Autres"
        if "BUT1" in nom_groupe: promo = "BUT 1"
        elif "BUT2" in nom_groupe: promo = "BUT 2"
        elif "BUT3" in nom_groupe: promo = "BUT 3"
            
        prof_str = f"{prof.nom} {prof.prenom}".strip() if prof and prof.nom != "N/A" else "N/A"
            
        jours_semaine[date_formatee][promo].append({
            "id": s.id,
            "heure_debut": s.date_debut.strftime("%H:%M"),
            "heure_fin": s.date_fin.strftime("%H:%M"),
            "enseignement": enseignement.libelle if enseignement else "Inconnu",
            "code": enseignement.code_cours if enseignement else "",
            "groupe": nom_groupe,
            "salle": salle.nom_salle if salle else "Inconnue",
            "prof": prof_str
        })

    jours_semaine_fusionnes = {}
    for jour, promos in jours_semaine.items():
        jours_semaine_fusionnes[jour] = {}
        for promo, cours_list in promos.items():
            groupes_cours = defaultdict(list)
            for c in cours_list:
                groupes_cours[(c["code"], c["groupe"], c["salle"], c["prof"])].append(c)

            fusionnes = []
            for sig, list_c in groupes_cours.items():
                list_c.sort(key=lambda x: x["heure_debut"])
                current = list_c[0].copy()
                for next_c in list_c[1:]:
                    if current["heure_fin"] == next_c["heure_debut"]:
                        current["heure_fin"] = next_c["heure_fin"]
                    else:
                        fusionnes.append(current)
                        current = next_c.copy()
                fusionnes.append(current)

            fusionnes.sort(key=lambda x: (x["heure_debut"], x["heure_fin"]))
            jours_semaine_fusionnes[jour][promo] = fusionnes

    ordre_promos = ["BUT 1", "BUT 2", "BUT 3", "Autres"]
    jours_semaine_ordonnes = {
        jour: {promo: promos[promo] for promo in ordre_promos if promo in promos}
        for jour, promos in jours_semaine_fusionnes.items()
    }

    return templates.TemplateResponse(
        request=request, 
        name="seances.html", 
        context={
            "jours_semaine": jours_semaine_ordonnes,
            "date_courante": jour_cible.strftime("%Y-%m-%d"),
            "groupes": db.query(models.GroupeDB).all(),
            "professeurs": db.query(models.ProfesseurDB).all(),
            "selected_groupe": id_groupe,
            "selected_prof": id_prof
        }
    )

@app.get("/admin/seances/{seance_id}/presences", response_class=HTMLResponse)
def admin_seance_presences(seance_id: int, request: Request, db: Session = Depends(get_db)):
    seance = db.query(models.SeanceDB).filter(models.SeanceDB.id == seance_id).first()
    if not seance:
        return RedirectResponse(url="/admin/seances", status_code=303)
        
    enseignement = db.query(models.EnseignementDB).filter(models.EnseignementDB.id == seance.id_enseignement).first()
    groupe = db.query(models.GroupeDB).filter(models.GroupeDB.id == seance.id_groupe).first()
    salle = db.query(models.SalleDB).filter(models.SalleDB.id == seance.id_salle).first()
    prof = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.id == seance.id_prof).first()
    
    etudiants = []
    if groupe:
        etudiants = db.query(models.EtudiantDB).filter(models.EtudiantDB.groupes.any(models.GroupeDB.id == groupe.id)).all()
        
    pointages_nfc = {p.nfc_uid: p for p in db.query(models.PointageDB).filter(models.PointageDB.id_seance == seance.id).all()}
    
    liste_presences = []
    for etudiant in etudiants:
        statut = "Absent"
        badge_uid = "Non attribué"
        if etudiant.carte:
            badge_uid = etudiant.carte.nfc_uid
            if badge_uid in pointages_nfc:
                statut = "Présent" 
                
        liste_presences.append({
            "numero": etudiant.numero_etudiant,
            "nom": etudiant.nom,
            "prenom": etudiant.prenom,
            "badge": badge_uid,
            "statut": statut
        })

    seance_info = {
        "id": seance.id,
        "date_debut": seance.date_debut.strftime("%d/%m/%Y à %H:%M"),
        "date_fin": seance.date_fin.strftime("%H:%M"),
        "enseignement": enseignement.libelle if enseignement else "Inconnu",
        "code": enseignement.code_cours if enseignement else "",
        "groupe": groupe.nom_groupe if groupe else "Inconnu",
        "salle": salle.nom_salle if salle else "Inconnue",
        "prof": f"{prof.nom} {prof.prenom}" if prof else "Inconnu"
    }

    return templates.TemplateResponse(
        request=request, 
        name="seance_presences.html", 
        context={"seance": seance_info, "presences": liste_presences}
    )


# ==========================================
# 5. EXPORT EXCEL PROPRE (AVEC INSERTION DE LIGNES)
# ==========================================

@app.get("/admin/seances/{seance_id}/export-excel")
def export_seance_excel(seance_id: int, db: Session = Depends(get_db)):
    seance = db.query(models.SeanceDB).filter(models.SeanceDB.id == seance_id).first()
    if not seance:
        return RedirectResponse(url="/admin/seances", status_code=303)
        
    enseignement = db.query(models.EnseignementDB).filter(models.EnseignementDB.id == seance.id_enseignement).first()
    groupe = db.query(models.GroupeDB).filter(models.GroupeDB.id == seance.id_groupe).first()
    salle = db.query(models.SalleDB).filter(models.SalleDB.id == seance.id_salle).first()
    prof = db.query(models.ProfesseurDB).filter(models.ProfesseurDB.id == seance.id_prof).first()
    
    etudiants = []
    if groupe:
        etudiants = db.query(models.EtudiantDB).filter(models.EtudiantDB.groupes.any(models.GroupeDB.id == groupe.id)).all()
        
    pointages_nfc = {p.nfc_uid: p for p in db.query(models.PointageDB).filter(models.PointageDB.id_seance == seance.id).all()}
    
    data = []
    for etudiant in etudiants:
        statut = "Absent"
        badge_uid = "Non attribué"
        if etudiant.carte:
            badge_uid = etudiant.carte.nfc_uid
            if badge_uid in pointages_nfc:
                statut = "Présent" 
                
        data.append({
            "N° Étudiant": etudiant.numero_etudiant,
            "Nom": etudiant.nom,
            "Prénom": etudiant.prenom,
            "Badge NFC": badge_uid,
            "Statut": statut
        })
        
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # On écrit d'abord le dataframe normalement
        df.to_excel(writer, index=False, sheet_name='Emargement')
        worksheet = writer.sheets['Emargement']
        
        # On insère 5 lignes tout en haut pour y caler les métadonnées proprement
        worksheet.insert_rows(1, amount=5)
        
        worksheet['A1'] = "FEUILLE D'ÉMARGEMENT - IUT"
        worksheet['A2'] = f"Cours : {enseignement.libelle if enseignement else 'Inconnu'} ({enseignement.code_cours if enseignement else ''})"
        worksheet['A3'] = f"Professeur : {prof.nom} {prof.prenom}" if prof and prof.nom != "N/A" else "Professeur : N/A"
        worksheet['A4'] = f"Date & Horaire : {seance.date_debut.strftime('%d/%m/%Y de %H:%M')} à {seance.date_fin.strftime('%H:%M')} | Salle : {salle.nom_salle if salle else 'Inconnue'}"
        worksheet['A5'] = f"Groupe : {groupe.nom_groupe if groupe else 'Inconnu'}"
        
    output.seek(0)
    
    nom_groupe_clean = groupe.nom_groupe if groupe else "groupe"
    filename = f"emargement_{seance.date_debut.strftime('%Y-%m-%d_%H-%M')}_{nom_groupe_clean}.xlsx"
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )