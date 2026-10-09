"""API appelée par les boîtiers Raspberry Pi (authentification par token)."""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from database import get_db
from services import scan
from services.presences import trouver_seance
from services.temps import maintenant_paris, normaliser_uid, vers_heure_paris

router = APIRouter(prefix="/api/v1", tags=["API boîtiers"])


class PointageIn(BaseModel):
    uuid: str
    nfc_uid: str
    timestamp: str          # ISO 8601 en UTC, ex : "2026-10-07T11:20:00Z"


class SyncIn(BaseModel):
    device_id: str
    batch: list[PointageIn] = []


@router.get("/status")
def statut():
    return {"status": "ok", "server_time_utc": datetime.now(timezone.utc).isoformat()}


@router.post("/sync")
def synchroniser(payload: SyncIn, authorization: str = Header(None), db: Session = Depends(get_db)):
    """Reçoit un lot de pointages d'un boîtier.
    En-tête obligatoire : Authorization: Bearer <token du boîtier>
    (affiché dans Configuration > Boîtiers)."""
    boitier = db.query(models.BoitierDB).filter(models.BoitierDB.device_id == payload.device_id).first()
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not boitier or not secrets.compare_digest(token, boitier.token):
        # 401 : le boîtier garde ses pointages en local et réessaiera plus tard
        raise HTTPException(status_code=401, detail="Boîtier inconnu ou token invalide")

    recu_le = maintenant_paris()
    # Un "Scanner la carte" attend un bip de CE boîtier : le boîtier affiche alors
    # le signal d'enrôlement (LED bleue) au lieu du rouge "carte inconnue"
    enrolement = scan.en_attente(boitier.device_id)
    confirmes, rejetes = [], []
    for item in payload.batch:
        if db.get(models.PointageDB, item.uuid):
            confirmes.append(item.uuid)          # déjà reçu (idempotence)
            continue
        try:
            t = vers_heure_paris(item.timestamp)
        except ValueError:
            rejetes.append(item.uuid)            # date illisible : inutile de le renvoyer
            confirmes.append(item.uuid)
            continue

        uid = normaliser_uid(item.nfc_uid)
        seance = trouver_seance(db, boitier, uid, t)
        db.add(models.PointageDB(
            uuid=item.uuid, nfc_uid=uid, device_id=boitier.device_id, timestamp=t,
            id_seance=seance.id if seance else None, recu_le=recu_le,
        ))
        db.flush()                               # repère un uuid présent deux fois dans le lot
        confirmes.append(item.uuid)

    boitier.derniere_synchro = recu_le
    db.commit()
    print(f"Boîtier {boitier.device_id} : {len(confirmes)} pointage(s) synchronisé(s).")
    return {
        "status": "success",
        "synced_uuids": list(dict.fromkeys(confirmes)),
        "rejected_uuids": rejetes,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "enrolement": enrolement and bool(payload.batch),
        # Le boîtier garde cette liste en local : une carte absente allume la LED rouge
        "cartes_connues": [uid for (uid,) in db.query(models.CarteDB.nfc_uid).all()],
    }
