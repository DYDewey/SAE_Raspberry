"""Thread d'envoi des pointages au serveur (POST /api/v1/sync).

Toutes les INTERVALLE_SYNCHRO secondes : on envoie les pointages synced = 0,
le serveur répond la liste des uuid reçus, on les passe à synced = 1.
En cas d'échec (réseau, serveur éteint, token refusé), on réessaie plus tard :
les pointages restent dans la base locale."""
import logging
import threading
from datetime import datetime, timezone

import requests

import config

log = logging.getLogger("synchro")


class Synchro(threading.Thread):
    def __init__(self, stockage, au_changement_etat=None, signaux=None):
        super().__init__(daemon=True, name="synchro")
        self.stockage = stockage
        self.signaux = signaux               # LED bleue pendant un envoi, rouge s'il échoue
        self.au_changement_etat = au_changement_etat or (lambda en_ligne: None)
        self.en_ligne = None          # inconnu au démarrage
        self.arret = threading.Event()
        self.reveil = threading.Event()
        self.verrou = threading.Lock()       # un seul envoi à la fois (thread de fond ou boucle de lecture)
        self.uuids_enrolement = set()        # bips reçus par le serveur pendant un "Scanner la carte"

    def demander_envoi(self):
        """Envoi immédiat (appelé après chaque bip) au lieu d'attendre l'intervalle."""
        self.reveil.set()

    def envoyer_maintenant(self, uuid_bip: str) -> bool:
        """Envoie tout de suite (en attendant la réponse) et dit si ce bip a été reçu
        pendant un "Scanner la carte" sur ce boîtier."""
        with self.verrou:
            if uuid_bip not in self.uuids_enrolement:
                self._cycle()
            return uuid_bip in self.uuids_enrolement

    def arreter(self):
        self.arret.set()
        self.reveil.set()

    def run(self):
        compteur = 0
        while not self.arret.is_set():
            with self.verrou:
                self._cycle()
            compteur += 1
            if compteur % 360 == 0:     # environ une fois par heure
                self.stockage.nettoyer(config.CONSERVATION_JOURS)
            self.reveil.wait(config.INTERVALLE_SYNCHRO)
            self.reveil.clear()

    def _changer_etat(self, en_ligne: bool):
        if en_ligne != self.en_ligne:
            self.en_ligne = en_ligne
            log.info("Serveur %s", "joignable" if en_ligne else "INJOIGNABLE : stockage local uniquement")
            self.au_changement_etat(en_ligne)

    def _cycle(self):
        """Envoie tous les pointages en attente, par lots. S'il n'y a rien à envoyer,
        un lot vide sert de signal de vie : le serveur affiche le boîtier "en ligne"
        et vérifie son token."""
        premier = True
        while not self.arret.is_set():
            lot = self.stockage.a_envoyer(config.TAILLE_LOT)
            if not lot and not premier:
                return
            premier = False
            if not self._envoyer(lot) or not lot:
                return

    def _envoyer(self, lot) -> bool:
        """Envoie un lot ; s'il contient des pointages, la LED bleue clignote pendant
        l'envoi et la rouge clignote s'il échoue (logigramme du livrable 2)."""
        if not lot or not self.signaux:
            return self._poster(lot)
        self.signaux.debut_envoi()
        ok = False
        try:
            ok = self._poster(lot)
        finally:
            self.signaux.fin_envoi(ok)
        return ok

    def _poster(self, lot) -> bool:
        try:
            r = requests.post(
                f"{config.SERVEUR_URL}/api/v1/sync",
                # connexion : premier contact depuis le démarrage ou une coupure -> le serveur
                # remet l'emploi du temps à jour
                json={"device_id": config.DEVICE_ID, "batch": lot, "connexion": self.en_ligne is not True},
                headers={"Authorization": f"Bearer {config.API_TOKEN}"},
                timeout=config.DELAI_HTTP,
            )
        except requests.RequestException as e:
            log.debug("Envoi impossible : %s", e)
            self._changer_etat(False)
            return False

        if r.status_code == 401:
            log.error("Token refusé par le serveur : vérifiez DEVICE_ID et API_TOKEN dans le .env "
                      "(Configuration > Boîtiers dans l'interface web).")
            self._changer_etat(False)
            return False
        if r.status_code != 200:
            log.warning("Réponse inattendue du serveur : %s %s", r.status_code, r.text[:200])
            self._changer_etat(False)
            return False

        reponse = r.json()
        self.stockage.marquer_envoyes(reponse.get("synced_uuids", []))
        if reponse.get("enrolement"):
            self.uuids_enrolement = {p["uuid"] for p in lot}
        if "cartes_connues" in reponse:          # absent avec un ancien serveur : on garde la liste
            self.stockage.remplacer_cartes(reponse["cartes_connues"])
        if reponse.get("rejected_uuids"):
            log.warning("%d pointage(s) rejeté(s) (date illisible)", len(reponse["rejected_uuids"]))
        if lot:
            log.info("%d pointage(s) envoyé(s), %d en attente", len(reponse.get("synced_uuids", [])),
                     self.stockage.nb_en_attente())
        self._controler_horloge(reponse.get("server_time_utc"))
        self._changer_etat(True)
        return True

    def _controler_horloge(self, heure_serveur):
        """Prévient si l'horloge du boîtier dérive (pile du RTC vide, NTP absent...)."""
        if not heure_serveur:
            return
        try:
            ecart = abs((datetime.now(timezone.utc) - datetime.fromisoformat(heure_serveur)).total_seconds())
        except ValueError:
            return
        if ecart > 60:
            log.warning("Horloge décalée de %d s par rapport au serveur : vérifiez le RTC (sudo hwclock -r)",
                        ecart)
