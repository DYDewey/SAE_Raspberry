@echo off
title Boitier - mode Secretariat
echo Passage du boitier en mode Secretariat (accueil, cartes)...
ssh -t pi@raspberrypi.local "sudo systemctl disable --now pointage-boitier; sudo systemctl enable --now pointage-boitier_acceuil && echo OK : mode Secretariat actif"
pause
