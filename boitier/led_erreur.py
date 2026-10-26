"""Lancé par systemd quand boitier.py s'arrête (ExecStopPost) : si c'est sur une erreur,
la LED rouge clignote 3 secondes avant que systemd relance le script.
Après 5 plantages en 5 minutes, systemd redémarre le Raspberry (pointage-boitier.service)."""
import os
import time

import config

if os.environ.get("SERVICE_RESULT", "success") != "success":
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(config.PIN_LED_ROUGE, GPIO.OUT)
    GPIO.setup(config.PIN_LED_BLEUE, GPIO.OUT, initial=GPIO.LOW)
    for _ in range(10):
        GPIO.output(config.PIN_LED_ROUGE, GPIO.HIGH)
        time.sleep(0.15)
        GPIO.output(config.PIN_LED_ROUGE, GPIO.LOW)
        time.sleep(0.15)
    GPIO.cleanup([config.PIN_LED_ROUGE, config.PIN_LED_BLEUE])
