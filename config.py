"""Paramètres de l'application, lus dans le fichier .env (avec des valeurs par défaut)."""
import os
import secrets
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

PARIS = ZoneInfo("Europe/Paris")

# --- Règles de présence ---
# Un étudiant qui badge plus de X minutes après le début du cours est "En retard"
TOLERANCE_RETARD_MIN = int(os.getenv("RETARD_TOLERANCE_MIN", "15"))
# On accepte un pointage jusqu'à X minutes AVANT le début du cours
AVANCE_POINTAGE_MIN = int(os.getenv("AVANCE_POINTAGE_MIN", "15"))
# Boîtier en mode SAE : une séance est une SAE si son intitulé dans l'EDT contient ce motif
# (expression régulière, majuscules/minuscules ignorées). Ex : "SAE5.B.01", "SAÉ 3.02"
MOTIF_SAE = os.getenv("MOTIF_SAE", r"\bSA[EÉ]")
# Un boîtier est considéré "en ligne" s'il a synchronisé il y a moins de X minutes
BOITIER_EN_LIGNE_MIN = int(os.getenv("BOITIER_EN_LIGNE_MIN", "10"))

# --- Emploi du temps ---
ICAL_URL = os.getenv("ICAL_URL", "").strip()
# Nombre de semaines importées à chaque synchro (semaine en cours incluse)
ICAL_SEMAINES = int(os.getenv("ICAL_SEMAINES", "4"))

# --- Connexion à l'interface d'administration ---
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
MOT_DE_PASSE_PAR_DEFAUT = "ADMIN_PASSWORD" not in os.environ

# Clé de signature des cookies de session. Sans SECRET_KEY dans le .env, une clé est
# générée une fois et gardée dans le fichier .secret_key : sinon chaque redémarrage du
# serveur (y compris les rechargements automatiques de --reload) déconnecterait tout le monde.
def _cle_secrete():
    if os.getenv("SECRET_KEY"):
        return os.getenv("SECRET_KEY")
    fichier = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")
    try:
        with open(fichier) as f:
            cle = f.read().strip()
        if cle:
            return cle
    except FileNotFoundError:
        pass
    cle = secrets.token_hex(32)
    with open(fichier, "w") as f:
        f.write(cle)
    return cle


SECRET_KEY = _cle_secrete()

# Déconnexion automatique après X minutes sans aucune page ouverte sur le site.
# Tant qu'une page est ouverte, elle prévient le serveur régulièrement : on reste connecté.
SESSION_INACTIVITE_MIN = int(os.getenv("SESSION_INACTIVITE_MIN", "30"))
