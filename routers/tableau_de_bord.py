"""Page d'accueil de l'interface : la journée en un coup d'œil."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

import config
import models
from database import get_db
from services.presences import construire_blocs, resumes_blocs, taux
from services.temps import maintenant_paris
from web import admin_requis, promo_de, render

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_requis)], tags=["Tableau de bord"])


@router.get("")
def tableau_de_bord(request: Request, db: Session = Depends(get_db)):
    maintenant = maintenant_paris()
    aujourdhui = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)

    # Cours du jour
    blocs_jour = construire_blocs(db, db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut >= aujourdhui,
        models.SeanceDB.date_debut < aujourdhui + timedelta(days=1),
    ).all())
    resumes_jour = resumes_blocs(db, blocs_jour)

    # Taux de présence sur les 7 derniers jours (cours terminés uniquement)
    blocs_semaine = [b for b in construire_blocs(db, db.query(models.SeanceDB).filter(
        models.SeanceDB.date_debut >= aujourdhui - timedelta(days=6),
        models.SeanceDB.date_debut <= maintenant,
    ).all()) if b.fin <= maintenant]
    resumes_semaine = resumes_blocs(db, blocs_semaine).values()
    taux_semaine = taux(sum(r["present"] for r in resumes_semaine), sum(r["retard"] for r in resumes_semaine),
                        sum(r["effectif"] for r in resumes_semaine))

    # Étudiants et cartes
    nb_etudiants = db.query(models.EtudiantDB).count()
    nb_cartes = db.query(models.CarteDB).count()

    # Boîtiers
    boitiers = db.query(models.BoitierDB).order_by(models.BoitierDB.device_id).all()
    seuil = maintenant - timedelta(minutes=config.BOITIER_EN_LIGNE_MIN)
    nb_en_ligne = sum(1 for b in boitiers if b.derniere_synchro and b.derniere_synchro >= seuil)

    # Derniers pointages, avec le nom et l'année de l'étudiant si la carte est connue.
    # On en charge plus que le nombre affiché : la page en montre 8 par onglet d'année.
    derniers = db.query(models.PointageDB).order_by(models.PointageDB.timestamp.desc()).limit(80).all()
    cartes = {c.nfc_uid: c.etudiant for c in db.query(models.CarteDB).filter(
        models.CarteDB.nfc_uid.in_([p.nfc_uid for p in derniers])).all()}

    def promo_etudiant(etudiant):
        if not etudiant:
            return "Inconnues"
        return next((p for p in (promo_de(g.nom_groupe) for g in etudiant.groupes) if p != "Autres"), "Autres")

    return render(
        request, "tableau_de_bord.html", actif="accueil",
        maintenant=maintenant,
        cours_du_jour=[(b, resumes_jour[b.id]) for b in blocs_jour],
        taux_semaine=taux_semaine,
        nb_etudiants=nb_etudiants,
        nb_cartes=nb_cartes,
        nb_sans_carte=nb_etudiants - nb_cartes,
        boitiers=boitiers,
        seuil_en_ligne=seuil,
        nb_en_ligne=nb_en_ligne,
        derniers=[(p, cartes.get(p.nfc_uid), promo_etudiant(cartes.get(p.nfc_uid))) for p in derniers],
        nb_seances=db.query(models.SeanceDB).count(),
    )
