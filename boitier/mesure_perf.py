"""Mesures de performance du boîtier (résultats à reporter dans docs/performances.md).

Chaque mesure affiche min / médiane / 95e centile / max et ajoute une ligne
dans mesures_perf.csv (à côté de ce fichier).

    python mesure_perf.py sqlite                 écriture d'un bip dans SQLite (PC ou Pi)
    python mesure_perf.py lecture                temps de lecture NFC, cartes passées à la main (Pi)
    python mesure_perf.py enchainement           bips à la chaîne, signal LED compris (Pi)
    python mesure_perf.py synchro                envoi de 10 / 100 / 1000 / 5000 bips au serveur
    python mesure_perf.py concurrence            plusieurs boîtiers qui envoient en même temps
    python mesure_perf.py demarrage              temps de démarrage du Pi et du service (Pi)

synchro et concurrence utilisent le serveur et le token du .env : prendre un boîtier
de test (ex : DEVICE_ID=PERF-01 créé dans Configuration > Boîtiers), car les faux bips
sont enregistrés sur le serveur. Pour les effacer ensuite (psql) :
    DELETE FROM pointages WHERE device_id = 'PERF-01';
    DELETE FROM boitiers WHERE device_id = 'PERF-01';
Les bips sont écrits dans une base SQLite temporaire : la vraie base du boîtier n'est pas touchée.
"""
import argparse
import csv
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
FICHIER_CSV = DOSSIER / "mesures_perf.csv"


# ---------- outils ----------

def stats(nom, durees_ms, details=""):
    """Affiche les statistiques et les ajoute au CSV."""
    if not durees_ms:
        print(f"{nom} : aucune mesure")
        return
    d = sorted(durees_ms)
    p95 = d[min(len(d) - 1, int(round(0.95 * (len(d) - 1))))]
    ligne = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "mesure": nom, "n": len(d),
        "min_ms": round(d[0], 2), "mediane_ms": round(statistics.median(d), 2),
        "p95_ms": round(p95, 2), "max_ms": round(d[-1], 2), "details": details,
    }
    print(f"{nom:<38} n={ligne['n']:<5} min={ligne['min_ms']:>9} ms  médiane={ligne['mediane_ms']:>9} ms  "
          f"p95={ligne['p95_ms']:>9} ms  max={ligne['max_ms']:>9} ms  {details}")
    nouveau = not FICHIER_CSV.exists()
    with open(FICHIER_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ligne), delimiter=";")
        if nouveau:
            w.writeheader()
        w.writerow(ligne)


def base_temporaire():
    from stockage import Stockage
    chemin = Path(tempfile.mkdtemp()) / "perf.db"
    return Stockage(str(chemin))


def charger_config(args):
    os.environ["BOITIER_ENV"] = args.config
    import config
    if args.serveur:
        config.SERVEUR_URL = args.serveur.rstrip("/")
    if args.device:
        config.DEVICE_ID = args.device
    if args.token:
        config.API_TOKEN = args.token
    return config


# ---------- mesures ----------

def mesure_sqlite(args):
    """Temps d'écriture d'un bip dans la base locale (commit sur la carte SD compris)."""
    stockage = base_temporaire()
    durees = []
    for i in range(args.n):
        t0 = time.perf_counter()
        stockage.ajouter(f"PERF{i:08X}")
        durees.append((time.perf_counter() - t0) * 1000)
    stats("Écriture SQLite d'un bip", durees, f"{args.n} écritures")


def mesure_lecture(args):
    """Temps de lire_uid() quand une carte est posée (la boucle à vide n'est pas comptée)."""
    from materiel import LecteurNFC, LectureIncomplete
    lecteur = LecteurNFC()
    print(f"Passez des cartes devant le lecteur ({args.n} lectures, Ctrl+C pour arrêter)...")
    durees, echecs, dernier = [], 0, None
    try:
        while len(durees) < args.n:
            t0 = time.perf_counter()
            try:
                uid = lecteur.lire_uid()
            except LectureIncomplete:
                echecs += 1
                continue
            if not uid:
                dernier = None
                time.sleep(0.02)
                continue
            if uid == dernier:           # carte restée posée : une seule mesure par passage
                continue
            dernier = uid
            durees.append((time.perf_counter() - t0) * 1000)
            print(f"  {len(durees):>3}. {uid}  {durees[-1]:.1f} ms")
    except KeyboardInterrupt:
        pass
    stats("Lecture NFC (lire_uid)", durees, f"{echecs} lecture(s) incomplète(s)")


def mesure_enchainement(args):
    """Cycle complet d'un bip comme dans boitier.py : lecture + SQLite + signal LED/buzzer.
    Mesure aussi l'intervalle entre deux bips enregistrés (débit réel)."""
    from materiel import LecteurNFC, LectureIncomplete, Signaux
    lecteur, signaux, stockage = LecteurNFC(), Signaux(), base_temporaire()
    signaux.demarrage()
    print(f"Faites passer {args.n} cartes à la suite le plus vite possible (Ctrl+C pour arrêter)...")
    cycles, intervalles, vus, precedent = [], [], set(), None
    debut_serie = None
    try:
        while len(cycles) < args.n:
            t0 = time.perf_counter()
            try:
                uid = lecteur.lire_uid()
            except LectureIncomplete:
                continue
            if not uid or uid in vus:
                time.sleep(0.02)
                continue
            vus.add(uid)
            stockage.ajouter(uid)
            t_enregistre = time.perf_counter()
            signaux.succes()
            cycles.append((time.perf_counter() - t0) * 1000)
            if precedent is not None:
                intervalles.append((t_enregistre - precedent) * 1000)
            precedent = t_enregistre
            debut_serie = debut_serie or t0
            print(f"  {len(cycles):>3}. {uid}  cycle {cycles[-1]:.1f} ms")
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)   # un 2e Ctrl+C ne doit pas couper les stats
        signaux.fermer()
    stats("Cycle d'un bip (lecture+SQLite+signal)", cycles)
    stats("Intervalle entre deux bips", intervalles, "inclut le temps de présenter la carte suivante")
    if len(cycles) > 1:
        # du 1er au dernier bip enregistré : l'attente après le dernier bip ne compte pas
        duree = precedent - debut_serie
        print(f"Débit : {len(cycles)} bips en {duree:.1f} s = {(len(cycles) - 1) / duree * 60:.0f} bips/minute")


def mesure_synchro(args):
    """Temps pour vider la file d'attente de N bips vers le serveur (par lots de TAILLE_LOT)."""
    config = charger_config(args)
    from synchro import Synchro
    print(f"Serveur {config.SERVEUR_URL}, boîtier {config.DEVICE_ID}, lots de {config.TAILLE_LOT}")
    for n in args.tailles:
        stockage = base_temporaire()
        for i in range(n):
            stockage.ajouter(f"PERF{i:08X}")
        synchro = Synchro(stockage)
        t0 = time.perf_counter()
        synchro._cycle()
        duree = (time.perf_counter() - t0) * 1000
        restants = stockage.nb_en_attente()
        if restants:
            print(f"  {n} bips : ÉCHEC, {restants} non envoyés (serveur joignable ? token correct ?)")
            continue
        stats(f"Synchro de {n} bips", [duree], f"{n / (duree / 1000):.0f} bips/s")


def mesure_concurrence(args):
    """K boîtiers simulés envoient chacun N bips en même temps (même device_id,
    uuid différents) : vérifie que le serveur tient la charge sans perte ni doublon."""
    config = charger_config(args)
    from synchro import Synchro
    resultats, erreurs = [], []

    def un_boitier(k):
        stockage = base_temporaire()
        for i in range(args.n):
            stockage.ajouter(f"PERF{k:02X}{i:06X}")
        t0 = time.perf_counter()
        Synchro(stockage)._cycle()
        resultats.append((time.perf_counter() - t0) * 1000)
        if stockage.nb_en_attente():
            erreurs.append(k)

    fils = [threading.Thread(target=un_boitier, args=(k,)) for k in range(args.boitiers)]
    t0 = time.perf_counter()
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    total = time.perf_counter() - t0
    stats(f"Synchro concurrente ({args.boitiers} boîtiers)", resultats,
          f"{args.n} bips chacun, total {total:.1f} s, {len(erreurs)} boîtier(s) en échec")


def mesure_demarrage(args):
    """Temps de boot (systemd-analyze) + moment où le boîtier affiche 'prêt' depuis la mise sous tension."""
    def lancer(cmd):
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()

    print("systemd-analyze :", lancer(["systemd-analyze"]) or "indisponible")
    print("\nServices les plus lents :")
    print("\n".join(lancer(["systemd-analyze", "blame"]).splitlines()[:8]))
    # short-monotonic = secondes écoulées depuis le démarrage du noyau
    # (pas de --grep : il gère mal l'accent de "prêt" selon la version de journalctl)
    journal = lancer(["journalctl", "-u", "pointage-boitier", "-b", "-o", "short-monotonic", "--no-pager"])
    lignes = [l for l in journal.splitlines() if "prêt" in l or "Started" in l]
    for l in lignes:
        print(" ", l)
    ligne = next((l for l in lignes if "prêt" in l), "")
    if ligne.startswith("["):
        secondes = float(ligne[1:ligne.index("]")])
        stats("Démarrage jusqu'à 'boîtier prêt'", [secondes * 1000], "depuis le démarrage du noyau")
    else:
        print("\nLigne 'prêt' introuvable dans le journal du service (le service tourne-t-il ?)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mesure", choices=["sqlite", "lecture", "enchainement", "synchro", "concurrence", "demarrage"])
    p.add_argument("-n", type=int, default=None, help="nombre de mesures / de bips")
    p.add_argument("--tailles", type=int, nargs="+", default=[10, 100, 1000, 5000],
                   help="tailles de file pour 'synchro'")
    p.add_argument("--boitiers", type=int, default=5, help="nombre de boîtiers pour 'concurrence'")
    p.add_argument("--config", default=".env", help="fichier de configuration du boîtier")
    p.add_argument("--serveur", help="remplace SERVEUR_URL du .env")
    p.add_argument("--device", help="remplace DEVICE_ID du .env")
    p.add_argument("--token", help="remplace API_TOKEN du .env")
    args = p.parse_args()
    args.n = args.n or {"sqlite": 1000, "lecture": 30, "enchainement": 20, "concurrence": 200}.get(args.mesure, 0)

    sys.path.insert(0, str(DOSSIER))
    os.environ.setdefault("BOITIER_ENV", args.config)
    globals()[f"mesure_{args.mesure}"](args)
    print(f"\nRésultats ajoutés à {FICHIER_CSV}")


if __name__ == "__main__":
    main()
