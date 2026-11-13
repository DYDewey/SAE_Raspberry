@echo off
title Boitier - mode Prof
echo Passage du boitier en mode Prof (salle, appel)...
ssh -t pi@raspberrypi.local "sudo systemctl disable --now pointage-boitier_acceuil; sudo systemctl enable --now pointage-boitier && echo OK : mode Prof actif"
pause
