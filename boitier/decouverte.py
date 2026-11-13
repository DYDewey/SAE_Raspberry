"""Recherche automatique du serveur quand son adresse a changé (PC qui change de réseau).

On teste toutes les adresses du réseau local du boîtier (ex : 192.168.1.1 à .254) sur le
port du serveur. Une machine qui répond n'est retenue que si elle accepte une synchro
avec le token du boîtier : c'est donc forcément notre serveur.
La nouvelle adresse est écrite dans le .env pour être la bonne au prochain démarrage."""
import ipaddress
import logging
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

import config

log = logging.getLogger("decouverte")


def adresses_locales() -> list:
    """Adresses IPv4 du boîtier (hors 127.x), ex : ['192.168.1.42']."""
    try:
        sortie = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
        ips = [ip for ip in sortie.split() if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip)]
    except (OSError, subprocess.SubprocessError):
        ips = []
    if not ips:          # hors Linux (tests sur PC) : adresse de la route par défaut
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))       # UDP : aucun paquet n'est envoyé
                ips = [s.getsockname()[0]]
        except OSError:
            pass
    return [ip for ip in ips if not ip.startswith("127.")]


def _port_ouvert(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=0.5):
            return True
    except OSError:
        return False


def _est_notre_serveur(url: str) -> bool:
    """Synchro vide avec notre token : seul notre serveur répond 200."""
    try:
        r = requests.post(f"{url}/api/v1/sync", json={"device_id": config.DEVICE_ID, "batch": []},
                          headers={"Authorization": f"Bearer {config.API_TOKEN}"}, timeout=config.DELAI_HTTP)
        return r.status_code == 200
    except requests.RequestException:
        return False


def chercher_serveur():
    """Renvoie l'URL du serveur trouvé sur le réseau local, ou None."""
    port = urlparse(config.SERVEUR_URL).port or 8000
    candidats = []
    for ip in adresses_locales():
        reseau = ipaddress.ip_network(f"{ip}/24", strict=False)
        hotes = [str(h) for h in reseau.hosts()]
        with ThreadPoolExecutor(max_workers=64) as pool:
            ouverts = pool.map(lambda h: (h, _port_ouvert(h, port)), hotes)
            candidats += [h for h, ok in ouverts if ok]
    log.info("Recherche du serveur : port %d ouvert sur %s", port, candidats or "aucune machine")
    for h in candidats:
        url = f"http://{h}:{port}"
        if _est_notre_serveur(url):
            return url
    return None


def memoriser(url: str):
    """Remplace SERVEUR_URL dans le .env du boîtier (ou l'ajoute)."""
    chemin = config.CHEMIN_ENV
    try:
        texte = chemin.read_text(encoding="utf-8") if chemin.exists() else ""
        if re.search(r"^SERVEUR_URL=.*$", texte, flags=re.M):
            texte = re.sub(r"^SERVEUR_URL=.*$", f"SERVEUR_URL={url}", texte, flags=re.M)
        else:
            texte += f"\nSERVEUR_URL={url}\n"
        chemin.write_text(texte, encoding="utf-8")
    except OSError as e:
        log.warning("Impossible d'écrire la nouvelle adresse dans %s : %s", chemin, e)
