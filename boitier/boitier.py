"""Programme principal du boîtier de pointage.

    python boitier.py                        sur le Raspberry Pi (configuration .env)
    python boitier.py --config .env.accueil  même Raspberry, utilisé comme boîtier d'accueil
    python boitier.py --simulation           sur un PC, sans matériel (UID tapés au clavier)

Boucle de lecture (thread principal) :
    badge détecté -> UID -> écriture SQLite (synced = 0) -> LED verte + bip
                                        (LED rouge si carte inconnue ou mal lue)
Thread de synchronisation (synchro.py) :
    envoie les pointages en attente au serveur, réessaie tant qu'il est injoignable.
"""
import argparse
import logging
import os
import signal
import sys
import time

log = logging.getLogger("boitier")


class AntiRebond:
    """Une carte enregistrée ne peut pas être réenregistrée avant `delai` secondes
    (1 minute par défaut), même si d'autres cartes sont passées entre-temps.
    Le délai ne démarre qu'une fois le bip réellement enregistré : si l'enregistrement
    échoue (LED rouge), l'étudiant peut repasser sa carte tout de suite."""
    PRESENCE_CONTINUE_S = 2      # carte encore posée : relue en boucle, on l'ignore en silence

    def __init__(self, delai: int):
        self.delai = delai
        self.enregistrees = {}       # uid -> heure du dernier bip enregistré
        self.dernier_lu = None       # dernière carte lue (enregistrée ou non)
        self.derniere_lecture = 0.0

    def analyser(self, uid: str) -> str:
        """'nouveau', 'toujours_posee' ou 'repassee_trop_tot'."""
        maintenant = time.monotonic()
        posee = uid == self.dernier_lu and maintenant - self.derniere_lecture < self.PRESENCE_CONTINUE_S
        self.dernier_lu, self.derniere_lecture = uid, maintenant
        if uid not in self.enregistrees:
            return "nouveau"
        if posee:
            return "toujours_posee"
        if maintenant - self.enregistrees[uid] < self.delai:
            return "repassee_trop_tot"
        return "nouveau"

    def restant(self, uid: str) -> int:
        return max(0, round(self.delai - (time.monotonic() - self.enregistrees.get(uid, 0))))

    def confirmer(self, uid: str):
        """À appeler seulement quand le bip est bien enregistré : démarre le délai."""
        maintenant = time.monotonic()
        self.enregistrees[uid] = maintenant
        # Oubli des cartes dont le délai est écoulé (la liste ne grossit pas indéfiniment)
        self.enregistrees = {u: t for u, t in self.enregistrees.items() if maintenant - t < self.delai}


def main():
    parser = argparse.ArgumentParser(description="Boîtier de pointage NFC")
    parser.add_argument("--config", default=".env", help="fichier de configuration (défaut : .env)")
    parser.add_argument("--simulation", action="store_true", help="sans matériel : UID tapés au clavier")
    parser.add_argument("-v", "--verbose", action="store_true", help="journal détaillé")
    args = parser.parse_args()

    # Le fichier de configuration doit être choisi AVANT de charger config.py
    os.environ["BOITIER_ENV"] = args.config
    import config
    from stockage import Stockage
    from synchro import Synchro
    if not config.CHEMIN_ENV.exists():
        sys.exit(f"Fichier de configuration introuvable : {config.CHEMIN_ENV}")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s : %(message)s", datefmt="%H:%M:%S")
    if not config.API_TOKEN:
        log.warning("API_TOKEN vide dans le .env : le serveur refusera les pointages.")

    if args.simulation:
        from materiel import LecteurSimule, SignauxSimules
        signaux, lecteur = SignauxSimules(), LecteurSimule()
    else:
        from materiel import LecteurNFC, Signaux
        signaux, lecteur = Signaux(), LecteurNFC()

    from materiel import LectureIncomplete

    stockage = Stockage(config.BASE_LOCALE)
    synchro = Synchro(stockage, au_changement_etat=signaux.etat_reseau)
    anti_rebond = AntiRebond(config.ANTI_REBOND_S)

    # Arrêt propre quand systemd arrête le service (SIGTERM)
    def arreter(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, arreter)

    signaux.demarrage()
    signaux.etat_reseau(False)
    synchro.start()
    log.info("Boîtier %s prêt. Serveur : %s. %d pointage(s) en attente d'envoi.",
             config.DEVICE_ID, config.SERVEUR_URL, stockage.nb_en_attente())

    # Carte mal lue : on réessaie en silence (souvent la lecture suivante réussit).
    # Si elle reste mal lue pendant ECHEC_LECTURE_S d'affilée : LED rouge.
    debut_echecs = dernier_echec = None

    try:
        while True:
            try:
                uid = lecteur.lire_uid()
            except LectureIncomplete:
                maintenant = time.monotonic()
                if debut_echecs is None or maintenant - dernier_echec > 0.5:
                    debut_echecs = maintenant        # nouvelle série d'échecs
                dernier_echec = maintenant
                log.debug("Carte mal lue, nouvelle tentative")
                if maintenant - debut_echecs >= config.ECHEC_LECTURE_S:
                    log.warning("Carte mal lue : la repasser bien à plat au centre du lecteur")
                    signaux.erreur()
                    debut_echecs = None
                time.sleep(0.05)
                continue
            if not uid:
                time.sleep(0.1)
                continue
            debut_echecs = None

            etat = anti_rebond.analyser(uid)
            if etat == "toujours_posee":
                time.sleep(0.2)
                continue
            if etat == "repassee_trop_tot":
                log.info("Badge %s déjà enregistré : réessayer dans %d s", uid, anti_rebond.restant(uid))
                signaux.deja_vu()
                continue

            try:
                pointage = stockage.ajouter(uid)
            except Exception:
                log.exception("Impossible d'écrire le pointage dans la base locale")
                signaux.erreur()
                continue
            anti_rebond.confirmer(uid)
            connue = stockage.carte_connue(uid)
            # Carte nouvelle et serveur joignable : on envoie tout de suite pour savoir
            # si un "Scanner la carte" l'attend sur ce boîtier (LED bleue)
            if not connue and synchro.en_ligne and synchro.envoyer_maintenant(pointage["uuid"]):
                log.info("Badge %s enregistré pour un étudiant (Scanner la carte)", uid)
                signaux.enrolement()
                continue
            synchro.demander_envoi()
            # Carte associée à aucun étudiant : le bip est gardé (on pourra l'attribuer
            # ensuite depuis l'interface web), mais l'étudiant voit la LED rouge
            if config.CONTROLE_CARTES and connue is False:
                log.warning("Badge %s INCONNU : associé à aucun étudiant (bip enregistré)", uid)
                signaux.erreur()
                continue
            log.info("Badge %s enregistré (%s)", uid, pointage["timestamp"])
            signaux.succes()
    except KeyboardInterrupt:
        log.info("Arrêt demandé")
    finally:
        synchro.arreter()
        signaux.fermer()
        log.info("Boîtier arrêté. %d pointage(s) restent à envoyer.", stockage.nb_en_attente())


if __name__ == "__main__":
    sys.exit(main())
