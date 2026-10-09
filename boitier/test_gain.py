"""Compare les réglages de gain du lecteur NFC avec TA carte.

    sudo systemctl stop pointage-boitier
    venv/bin/python test_gain.py

Pour chaque réglage, garde la carte posée à plat sur le lecteur pendant 10 s.
Le meilleur réglage est celui qui a le plus de lectures OK et le moins d'échecs.
Mets-le ensuite dans le .env, par exemple : GAIN_ANTENNE=0x58
"""
import time

import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

import config
from materiel import LecteurNFC, LectureIncomplete

lecteur = LecteurNFC()
resultats = []
for gain in (0x48, 0x58, 0x68, 0x70):
    lecteur.r.Write_MFRC522(0x26, gain)
    input(f"\nGain 0x{gain:02X} : pose la carte puis appuie sur Entrée (10 s de test)...")
    ok, echecs, uids = 0, 0, set()
    fin = time.time() + 10
    while time.time() < fin:
        try:
            uid = lecteur.lire_uid()
        except LectureIncomplete:
            echecs += 1
            continue
        if uid:
            ok += 1
            uids.add(uid)
        time.sleep(0.05)
    print(f"  lectures OK : {ok}   échecs : {echecs}   UID : {', '.join(uids) or '-'}")
    resultats.append((ok - echecs, gain))

meilleur = max(resultats)[1]
print(f"\nMeilleur réglage : GAIN_ANTENNE=0x{meilleur:02X}  (à mettre dans le .env)")
GPIO.cleanup()
