#!/bin/bash
# Installation du boîtier sur le Raspberry Pi :  bash installer.sh
# - crée l'environnement Python et installe les bibliothèques
# - installe le service qui lance le boîtier au démarrage
set -e
DOSSIER="$(cd "$(dirname "$0")" && pwd)"
UTILISATEUR="$(whoami)"
cd "$DOSSIER"

echo "== Vérification du SPI (lecteur NFC)"
if ! ls /dev/spidev0.0 >/dev/null 2>&1; then
    echo "Le SPI n'est pas activé : sudo raspi-config > Interface Options > SPI > Oui, puis redémarrer."
    exit 1
fi

echo "== Environnement Python"
python3 -m venv --system-site-packages venv
venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt -q

if [ ! -f .env ]; then
    cp .env.example .env
    echo "!! Fichier .env créé : complétez SERVEUR_URL, DEVICE_ID et API_TOKEN (nano .env)"
fi

echo "== Service au démarrage"
sed -e "s#/home/pi/boitier#$DOSSIER#g" -e "s#User=pi#User=$UTILISATEUR#" pointage-boitier.service \
    | sudo tee /etc/systemd/system/pointage-boitier.service >/dev/null
sudo usermod -aG gpio,spi "$UTILISATEUR"
sudo systemctl daemon-reload
sudo systemctl enable pointage-boitier

echo
echo "Installation terminée."
echo "  Tester à la main  : venv/bin/python boitier.py"
echo "  Lancer le service : sudo systemctl start pointage-boitier"
echo "  Voir le journal   : journalctl -u pointage-boitier -f"
