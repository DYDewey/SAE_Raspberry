"""Paramètres du boîtier, lus dans le fichier .env (à côté de ce fichier).

Un même Raspberry peut servir de plusieurs boîtiers (ex : salle et accueil) avec
un fichier de configuration par boîtier :
    python boitier.py                       -> .env
    python boitier.py --config .env.accueil -> .env.accueil
"""
import os
from pathlib import Path

from dotenv import load_dotenv

DOSSIER = Path(__file__).resolve().parent
FICHIER_ENV = os.getenv("BOITIER_ENV", ".env")
CHEMIN_ENV = Path(FICHIER_ENV) if Path(FICHIER_ENV).is_absolute() else DOSSIER / FICHIER_ENV
load_dotenv(CHEMIN_ENV)

# --- Serveur ---
SERVEUR_URL = os.getenv("SERVEUR_URL", "http://192.168.1.10:8000").rstrip("/")
DEVICE_ID = os.getenv("DEVICE_ID", "RPI-001")
API_TOKEN = os.getenv("API_TOKEN", "")

# --- Synchronisation ---
INTERVALLE_SYNCHRO = int(os.getenv("INTERVALLE_SYNCHRO", "10"))   # secondes entre deux envois
TAILLE_LOT = int(os.getenv("TAILLE_LOT", "100"))                  # pointages max par envoi
DELAI_HTTP = int(os.getenv("DELAI_HTTP", "5"))                     # secondes avant abandon d'un envoi
CONSERVATION_JOURS = int(os.getenv("CONSERVATION_JOURS", "30"))    # pointages envoyés gardés en local

# --- Lecture ---
# Une carte enregistrée ne peut pas être réenregistrée avant ce délai (secondes),
# sauf si l'enregistrement a échoué
ANTI_REBOND_S = int(os.getenv("ANTI_REBOND_S", "60"))
# Carte détectée mais mal lue pendant ce délai d'affilée (secondes) : LED rouge
ECHEC_LECTURE_S = float(os.getenv("ECHEC_LECTURE_S", "1"))
# 1 = LED rouge pour une carte associée à aucun étudiant (le bip est quand même enregistré)
# 0 = pas de contrôle : à mettre sur le boîtier d'accueil, qui sert à enregistrer les nouvelles cartes
CONTROLE_CARTES = os.getenv("CONTROLE_CARTES", "1") == "1"

# --- Base locale ---
# Une base par boîtier : les bips gardés hors ligne partent avec le bon DEVICE_ID
BASE_LOCALE = os.getenv("BASE_LOCALE", str(
    DOSSIER / ("pointages.db" if FICHIER_ENV == ".env" else f"pointages_{DEVICE_ID}.db")))

# --- Câblage (numérotation BCM) ---
PIN_LED_BLEUE = 17
PIN_LED_VERTE = 27
PIN_LED_ROUGE = 22
PIN_BUZZER = 14
# Le module buzzer du boîtier sonne quand la broche est à 0 V (LOW) : logique inversée.
# Avec un buzzer qui sonne à l'état haut (HIGH), mettre BUZZER_INVERSE=0 dans le .env
BUZZER_INVERSE = os.getenv("BUZZER_INVERSE", "1") == "1"
PIN_RST_NFC = 25
# Gain de réception du lecteur NFC (registre RFCfgReg) : vide = réglage par défaut (0x48).
# Valeurs possibles : 0x48, 0x58, 0x68, 0x70 (max). Trouver la meilleure avec test_gain.py
_gain = os.getenv("GAIN_ANTENNE", "").strip()
GAIN_ANTENNE = int(_gain, 0) if _gain else None
