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

# Un service par dossier : boitier -> pointage-boitier, boitier_acceuil -> pointage-boitier_acceuil
SERVICE="pointage-$(basename "$DOSSIER")"

echo "== Service au démarrage ($SERVICE)"
sed -e "s#/home/pi/boitier#$DOSSIER#g" -e "s#User=pi#User=$UTILISATEUR#" pointage-boitier.service \
    | sudo tee "/etc/systemd/system/$SERVICE.service" >/dev/null
sudo usermod -aG gpio,spi "$UTILISATEUR"
sudo systemctl daemon-reload

# Un seul lecteur NFC par Raspberry : on arrête les autres boîtiers installés sur ce Pi
for autre in $(systemctl list-unit-files 'pointage-*.service' --no-legend | awk '{print $1}'); do
    if [ "$autre" != "$SERVICE.service" ]; then
        echo "   arrêt de $autre (un seul boîtier actif à la fois)"
        sudo systemctl disable --now "$autre" >/dev/null 2>&1 || true
    fi
done
sudo systemctl enable --now "$SERVICE"

echo
echo "Installation terminée : $SERVICE est lancé et démarrera tout seul."
echo "  Voir le journal   : journalctl -u $SERVICE -f"
echo "  Redémarrer        : sudo systemctl restart $SERVICE"
echo "  Arrêter           : sudo systemctl stop $SERVICE"
echo "  Changer de mode   : bash installer.sh dans l'autre dossier"
