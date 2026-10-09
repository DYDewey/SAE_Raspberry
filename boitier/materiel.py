"""Matériel du boîtier : lecteur NFC RC522, LED et buzzer.

Signaux :
  LED rouge fixe              démarrage du Raspberry (avant le lancement du script)
  LED bleue fixe              boîtier opérationnel, serveur joignable
  LED bleue clignote lentement  serveur injoignable : les bips sont gardés en local
  LED verte + 1 bip           carte lue, pointage enregistré
  LED rouge 2 s + 2 bips      carte mal lue (plus d'1 s), carte inconnue ou erreur d'enregistrement
  LED bleue clignote vite     envoi des pointages au serveur en cours (redevient fixe à la fin)
  LED rouge clignote          envoi au serveur échoué (nouvel essai un peu plus tard)
  LED rouge clignote (arrêt)  le script s'est arrêté sur une erreur (systemd le relance)
  LED verte clignote + 2 bips très courts  badge déjà enregistré il y a moins d'1 minute
  LED verte + bleue 1,5 s + 1 bip          carte enregistrée sur la fiche d'un étudiant ("Scanner la carte")

Le mode simulation (python boitier.py --simulation) remplace le matériel par
le clavier et la console, pour tester sur un PC sans Raspberry Pi.
"""
import logging
import threading
import time

import config

log = logging.getLogger("materiel")


# ==========================================
# LED et buzzer
# ==========================================

class Signaux:
    """Les LED sont pilotées par deux threads : la boucle de lecture (verte / rouge,
    via _signal) et le thread de synchro (bleue pendant un envoi, rouge si échec).
    Un verrou évite qu'ils écrivent sur les LED en même temps."""

    def __init__(self):
        import RPi.GPIO as GPIO
        self.GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in (config.PIN_LED_BLEUE, config.PIN_LED_VERTE):
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        # La rouge est allumée par le Raspberry pendant le boot (installer.sh) : on la laisse
        # allumée jusqu'à la fin du démarrage du script
        GPIO.setup(config.PIN_LED_ROUGE, GPIO.OUT, initial=GPIO.HIGH)
        # Buzzer éteint dès la configuration de la broche (HIGH si buzzer inversé)
        GPIO.setup(config.PIN_BUZZER, GPIO.OUT, initial=GPIO.HIGH if config.BUZZER_INVERSE else GPIO.LOW)
        self.verrou = threading.RLock()
        self.envoi_en_cours = threading.Event()
        self.pret = threading.Event()          # fin du démarrage : bleue fixe
        self.hors_ligne = threading.Event()    # serveur injoignable : bleue clignote lentement
        self.bleue_jusqu_a = 0.0             # un envoi rapide reste visible au moins 0,6 s
        self.arret = threading.Event()
        threading.Thread(target=self._led_bleue, daemon=True, name="led-bleue").start()

    def _sortie(self, pin, etat):
        if pin == config.PIN_BUZZER and config.BUZZER_INVERSE:
            etat = not etat
        self.GPIO.output(pin, self.GPIO.HIGH if etat else self.GPIO.LOW)

    def _led_bleue(self):
        """LED bleue : fixe quand le boîtier est prêt et le serveur joignable,
        clignote vite pendant un envoi, lentement quand le serveur est injoignable."""
        allumee, tic = False, 0
        while not self.arret.is_set():
            tic += 1
            if not self.pret.is_set():
                allumee = False
            elif self.envoi_en_cours.is_set() or time.monotonic() < self.bleue_jusqu_a:
                allumee = not allumee                  # 0,15 s allumée / 0,15 s éteinte
            elif self.hors_ligne.is_set():
                allumee = (tic // 4) % 2 == 0          # 0,6 s allumée / 0,6 s éteinte
            else:
                allumee = True
            with self.verrou:
                self._sortie(config.PIN_LED_BLEUE, allumee)
            time.sleep(0.15)

    def _bips(self, n, duree=0.08, pause=0.08):
        for i in range(n):
            self._sortie(config.PIN_BUZZER, True)
            time.sleep(duree)
            self._sortie(config.PIN_BUZZER, False)
            if i < n - 1:
                time.sleep(pause)

    def _clignoter(self, pin, fois, periode=0.12, finir_allumee=False):
        for _ in range(fois):
            self._sortie(pin, not finir_allumee)
            time.sleep(periode)
            self._sortie(pin, finir_allumee)
            time.sleep(periode)

    def demarrage(self):
        """Fin du démarrage : la rouge (allumée pendant le boot) s'éteint, la bleue
        s'allume et reste fixe tant que le boîtier est opérationnel."""
        with self.verrou:
            self._sortie(config.PIN_LED_ROUGE, False)
            self._bips(1, 0.05)
        self.pret.set()

    def etat_reseau(self, en_ligne: bool):
        if en_ligne:
            self.hors_ligne.clear()
        else:
            self.hors_ligne.set()

    def debut_envoi(self):
        self.bleue_jusqu_a = time.monotonic() + 0.6
        self.envoi_en_cours.set()

    def fin_envoi(self, ok: bool):
        self.envoi_en_cours.clear()
        if not ok:
            with self.verrou:
                self._sortie(config.PIN_LED_BLEUE, False)
                self._clignoter(config.PIN_LED_ROUGE, 3, 0.1)

    def _signal(self, led, nb_bips, duree_bip, duree_led, bleue=False):
        """Allume une LED (la bleue s'éteint pendant ce temps, sauf bleue=True) + bips.
        Le verrou bloque le thread de la bleue : elle reprend son état à la fin."""
        with self.verrou:
            self._sortie(config.PIN_LED_BLEUE, bleue)
            self._sortie(led, True)
            self._bips(nb_bips, duree_bip)
            time.sleep(max(0, duree_led - nb_bips * 2 * duree_bip))
            self._sortie(led, False)

    def succes(self):
        self._signal(config.PIN_LED_VERTE, 1, 0.1, duree_led=0.8)

    def deja_vu(self):
        with self.verrou:
            self._sortie(config.PIN_LED_BLEUE, False)
            self._bips(2, 0.03, 0.05)
            self._clignoter(config.PIN_LED_VERTE, 2, 0.12)

    def enrolement(self):
        self._signal(config.PIN_LED_VERTE, 1, 0.1, duree_led=1.5, bleue=True)

    def erreur(self):
        """LED rouge 2 secondes + 2 bips courts."""
        self._signal(config.PIN_LED_ROUGE, 2, 0.1, duree_led=2.0)

    def fermer(self):
        self.arret.set()
        time.sleep(0.2)
        self._sortie(config.PIN_BUZZER, False)
        # On libère tout sauf le buzzer, qui garde son état "éteint" après l'arrêt
        self.GPIO.cleanup([config.PIN_LED_BLEUE, config.PIN_LED_VERTE, config.PIN_LED_ROUGE])


class SignauxSimules(Signaux):
    """Affiche les signaux dans la console au lieu d'allumer des LED."""
    def __init__(self):
        pass

    def demarrage(self):
        print("[LED] rouge éteinte, BLEUE fixe : boîtier opérationnel")

    def etat_reseau(self, en_ligne):
        print(f"[réseau] serveur {'joignable' if en_ligne else 'injoignable (stockage local)'}")

    def debut_envoi(self):
        print("[LED] bleue clignote : envoi au serveur")

    def fin_envoi(self, ok):
        print("[LED] bleue fixe : envoi terminé" if ok else "[LED] ROUGE clignote : envoi échoué")

    def succes(self):
        print("[LED] VERTE + bip : pointage enregistré")

    def deja_vu(self):
        print("[LED] verte clignote + 2 bips très courts : badge déjà pris en compte")

    def enrolement(self):
        print("[LED] VERTE + BLEUE 1,5 s + bip : nouvelle carte enregistrée (Scanner la carte)")

    def erreur(self):
        print("[LED] ROUGE 2 s + 2 bips courts : erreur")

    def fermer(self):
        pass


# ==========================================
# Lecteur NFC RC522
# ==========================================

class LecteurNFC:
    """Lit uniquement l'identifiant (UID) des cartes, sans authentification :
    fonctionne aussi avec les cartes dont le contenu est protégé (DESFire...).
    Gère les UID de 4 et 7 octets. Renvoie l'UID en hexadécimal majuscule
    (ex : '10D65D56'), le format attendu par le serveur."""

    SEL_CL1, SEL_CL2 = 0x93, 0x95

    def __init__(self):
        from mfrc522 import MFRC522
        # pin_rst explicite : en mode BCM la bibliothèque prendrait GPIO 15 par défaut
        self.r = MFRC522(pin_rst=config.PIN_RST_NFC)
        if config.GAIN_ANTENNE is not None:
            # RFCfgReg (0x26) : gain de réception. 0x48 = défaut, 0x58, 0x68, 0x70 = max
            self.r.Write_MFRC522(0x26, config.GAIN_ANTENNE)
        self.sans_carte = 0

    def _anticollision(self, sel):
        r = self.r
        r.Write_MFRC522(r.BitFramingReg, 0x00)
        status, data, _ = r.MFRC522_ToCard(r.PCD_TRANSCEIVE, [sel, 0x20])
        if status != r.MI_OK or len(data) != 5 or data[0] ^ data[1] ^ data[2] ^ data[3] != data[4]:
            return None
        return data

    def _selection(self, sel, ser):
        r = self.r
        buf = [sel, 0x70] + list(ser[:5])
        buf += r.CalulateCRC(buf)
        status, data, bits = r.MFRC522_ToCard(r.PCD_TRANSCEIVE, buf)
        return data[0] if status == r.MI_OK and bits == 0x18 else None

    ESSAIS = 4      # tentatives de lecture complète d'une carte détectée

    def lire_uid(self):
        """UID de la carte posée sur le lecteur, ou None.
        Lève LectureIncomplete si une carte est détectée mais mal lue."""
        r = self.r
        status, _ = r.MFRC522_Request(r.PICC_REQIDL)
        if status != r.MI_OK:
            # Une carte restée bloquée après un échange raté ne répond plus jusqu'à ce
            # qu'on la retire. Couper le champ quelques ms la redémarre (2 fois par seconde).
            self.sans_carte += 1
            if self.sans_carte % 5 == 0:
                self._redemarrer_champ()
            return None
        self.sans_carte = 0
        # Les cartes à UID de 7 octets (cartes IUT, DESFire) demandent 3 échanges
        # au lieu d'1 : un seul raté suffit à faire échouer la lecture. On réessaie
        # aussitôt en "réveillant" la carte (WUPA), sans attendre le tour suivant.
        for essai in range(self.ESSAIS):
            if essai:
                self._redemarrer_champ()
                status, _ = r.MFRC522_Request(getattr(r, "PICC_REQALL", 0x52))
                if status != r.MI_OK:
                    continue
            uid = self._lire_uid_carte()
            if uid:
                if essai:
                    log.debug("Carte lue au %de essai", essai + 1)
                return uid
        raise LectureIncomplete()

    def _redemarrer_champ(self):
        """Coupe puis rallume l'antenne : la carte posée redémarre à zéro."""
        r = self.r
        r.ClearBitMask(r.TxControlReg, 0x03)
        time.sleep(0.005)
        r.SetBitMask(r.TxControlReg, 0x03)
        time.sleep(0.005)

    def _lire_uid_carte(self):
        cl1 = self._anticollision(self.SEL_CL1)
        if cl1 is None:
            return None
        if cl1[0] != 0x88:                        # UID de 4 octets, complet
            return bytes(cl1[:4]).hex().upper()
        # 0x88 = "cascade tag" : UID de 7 octets, il faut un 2e niveau
        if self._selection(self.SEL_CL1, cl1) is None:
            return None
        cl2 = self._anticollision(self.SEL_CL2)
        if cl2 is None:
            return None
        return bytes(list(cl1[1:4]) + list(cl2[:4])).hex().upper()


class LectureIncomplete(Exception):
    """Une carte a été détectée mais son UID n'a pas pu être lu entièrement."""


class LecteurSimule:
    """Lit un UID tapé au clavier (Entrée seule = rien)."""
    def __init__(self):
        print("Mode simulation : tapez un UID (ex : 10D65D56) puis Entrée, '!' pour une carte "
              "mal lue, ou 'q' pour quitter.")
        self.mal_lue_jusqua = 0.0

    def lire_uid(self):
        if time.monotonic() < self.mal_lue_jusqua:
            raise LectureIncomplete()
        saisie = input("> ").strip()
        if saisie.lower() == "q":
            raise KeyboardInterrupt
        if saisie == "!":                         # simule une carte mal lue pendant 1,5 s
            self.mal_lue_jusqua = time.monotonic() + 1.5
            raise LectureIncomplete()
        # Même format que le vrai lecteur : hexadécimal majuscule sans séparateur
        return "".join(c for c in saisie.upper() if c in "0123456789ABCDEF") or None
