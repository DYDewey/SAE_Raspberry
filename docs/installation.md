# Guide d'installation et d'utilisation

Pour quelqu'un qui n'a jamais installé le projet. Compter environ 30 minutes pour le serveur et 30 minutes par boîtier.

## 1. Ce qu'il faut

**Serveur** (un PC sous Windows ou Linux) :
* [Python 3.11 ou plus](https://www.python.org/downloads/) (sous Windows, cocher « Add Python to PATH ») ;
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) (pour la base PostgreSQL) ;
* [Git](https://git-scm.com/downloads).

**Boîtier** :
* Raspberry Pi (3B+, 4 ou Zero 2 W) + carte microSD 16 Go + alimentation ;
* lecteur NFC RC522, module horloge RTC DS3231 ;
* 3 LED (bleue, verte, rouge) avec résistances 220 Ω, un buzzer actif ;
* fils Dupont femelle-femelle.

## 2. Installer le serveur

Ouvrir un terminal :

```bash
git clone https://github.com/DYDewey/SAE_Raspberry
cd SAE_Backend
python -m venv venv
venv\Scripts\activate          # Windows   (Linux : source venv/bin/activate)
pip install -r requirements.txt
```

Créer un fichier `.env` à la racine (les variables sont expliquées dans le README) :

```ini
DB_USER=sae
DB_PASSWORD=un_mot_de_passe
DB_NAME=pointage
ADMIN_USER=admin
ADMIN_PASSWORD=un_autre_mot_de_passe
SECRET_KEY=coller_ici_une_longue_chaine_aleatoire
ICAL_URL=lien_ical_ADE
```

Lancer la base puis le serveur :

```bash
docker compose up -d
uvicorn main:app --host 0.0.0.0 --port 8000
```

Ouvrir http://localhost:8000 et se connecter avec `ADMIN_USER` / `ADMIN_PASSWORD`.

> Les boîtiers doivent pouvoir joindre le PC : noter son adresse IP (`ipconfig` sous Windows, `ip a` sous Linux) et autoriser le port 8000 dans le pare-feu.

## 3. Premier paramétrage dans l'interface

1. **Étudiants > Importer des étudiants** : déposer le fichier Excel de la scolarité.
2. **Emploi du temps > Synchroniser l'EDT** : importe les cours depuis ADE.
3. **Configuration > Boîtiers** : créer un boîtier (identifiant, ex. `RPI-001`, professeur attitré, salle de repli) et **copier son token**.
4. **Associer les cartes** : dans la liste des étudiants, cliquer « Scanner la carte » puis passer la carte sur le lecteur USB (ou sur le boîtier d'accueil).

## 4. Brancher le boîtier

Numéros en mode **BCM** (numéros GPIO, pas les numéros de broches physiques).

| Élément | Patte | GPIO (BCM) | Broche physique |
|---|---|---|---|
| RC522 | SDA | 8 | 24 |
| | SCK | 11 | 23 |
| | MOSI | 10 | 19 |
| | MISO | 9 | 21 |
| | RST | 25 | 22 |
| | 3.3V / GND | — | 1 / 6 |
| RTC DS3231 | SDA / SCL | 2 / 3 | 3 / 5 |
| | VCC / GND | — | 1 / 9 |
| LED bleue / verte / rouge (+ résistance 220 Ω) | anode | 17 / 27 / 22 | 11 / 13 / 15 |
| Buzzer actif | signal | 14 | 8 |

⚠ Le RC522 se branche en **3,3 V**, jamais en 5 V.

## 5. Installer le boîtier

1. Installer **Raspberry Pi OS Lite** avec Raspberry Pi Imager (régler le Wi-Fi et activer SSH dans les options).
2. Activer SPI et I2C : `sudo raspi-config` → *Interface Options*.
3. Copier le dossier `boitier` dans `/home/pi/boitier`, puis :

```bash
cd ~/boitier
bash installer.sh
nano .env        # SERVEUR_URL=http://IP_DU_PC:8000, DEVICE_ID=RPI-001, API_TOKEN=le token copié
sudo systemctl restart pointage-boitier
```

Le boîtier démarre ensuite tout seul à chaque allumage. La LED bleue fixe indique qu'il est prêt et que le serveur répond.

## 6. Utilisation au quotidien

* **Étudiant** : passe sa carte → LED verte + bip. LED rouge + 2 bips : carte mal lue ou inconnue, la repasser.
* **Professeur** : ouvre son cours dans **Emploi du temps** pour voir l'émargement en direct, corrige un statut si besoin, exporte en Excel.
* **Scolarité** : **Absences** pour le bilan par classe et la feuille ScoDoc ; **Pointages** pour retrouver un bip précis.

Signification de toutes les LED : voir `boitier/README.md`.

## 7. En cas de problème

| Symptôme | À vérifier |
|---|---|
| LED bleue qui clignote lentement | le Pi n'atteint pas le serveur : IP dans `SERVEUR_URL`, pare-feu, serveur lancé. Les bips sont gardés et partiront au retour du réseau. |
| Boîtier « hors ligne » dans l'interface alors qu'il tourne | token faux : le recopier depuis **Configuration > Boîtiers** |
| Aucune LED au démarrage | `journalctl -u pointage-boitier -f` sur le Pi |
| Mauvaise heure sur les bips | pile du module RTC, `sudo hwclock -r` |
| Page web inaccessible | `docker compose ps` (la base tourne ?), terminal d'uvicorn |

Sauvegarde de la base : voir la section « Sauvegarde et restauration » du README.
