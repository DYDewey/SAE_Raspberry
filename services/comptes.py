"""Mots de passe des comptes professeurs (hachés, jamais stockés en clair)."""
import hashlib
import hmac
import secrets

ITERATIONS = 200_000


def hacher(mot_de_passe: str) -> str:
    sel = secrets.token_hex(16)
    empreinte = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), bytes.fromhex(sel), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${sel}${empreinte}"


def verifier(mot_de_passe: str, stocke: str) -> bool:
    try:
        _, iterations, sel, empreinte = (stocke or "").split("$")
        calcule = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), bytes.fromhex(sel), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(calcule, empreinte)
