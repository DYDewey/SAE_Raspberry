# Boîtier de pointage (Raspberry Pi)

Programme qui tourne sur le Raspberry Pi : il lit les cartes NFC, enregistre chaque bip dans une base SQLite locale, puis l'envoie au serveur dès qu'il est joignable.

## Fonctionnement

```
badge -> lecteur RC522 -> UID (hexa) -> SQLite locale (synced = 0) -> LED verte + bip
                                                 |
                       thread de synchro (toutes les 10 s et après chaque bip)
                                                 v
                         POST /api/v1/sync (token) -> synced = 1
```

* **Hors ligne d'abord :** le bip est enregistré en local avant tout envoi. Si le Wi-Fi ou le serveur tombe, les pointages attendent et partent au retour du réseau.
* **Heure :** chaque bip est horodaté en UTC grâce au module RTC DS3231, même sans réseau.
* **Anti-rebond :** une carte enregistrée ne peut pas repasser avant 1 minute (`ANTI_REBOND_S`), même si d'autres cartes sont passées entre-temps. Si l'enregistrement a échoué (LED rouge), elle peut repasser tout de suite.
* **Cartes :** seul l'identifiant (UID, 4 ou 7 octets) est lu, sans authentification ; fonctionne aussi avec les cartes protégées.

## Signaux

| Signal | Signification |
|---|---|
| LED rouge fixe | démarrage du Raspberry (avant le lancement du script) |
| LED bleue fixe | boîtier opérationnel, serveur joignable |
| LED bleue qui clignote lentement | serveur injoignable : les bips sont gardés sur le boîtier et envoyés au retour du réseau |
| LED verte + 1 bip | carte lue, pointage enregistré |
| LED rouge 2 s + 2 bips courts | carte mal lue pendant plus d'1 s, carte inconnue ou erreur d'enregistrement |
| LED bleue qui clignote vite | envoi des pointages au serveur en cours (redevient fixe ensuite) |
| LED rouge qui clignote 3 fois | envoi au serveur échoué, nouvel essai un peu plus tard |
| LED rouge qui clignote 3 s | le script s'est arrêté sur une erreur ; systemd le relance (5 plantages en 5 min : le Pi redémarre) |
| LED verte qui clignote 2 fois + 2 bips très courts | badge déjà pris en compte il y a moins d'1 minute |
| LED verte + bleue 1,5 s + 1 bip | nouvelle carte enregistrée pendant un « Scanner la carte » |

* **Carte inconnue :** à chaque synchro, le serveur envoie la liste des cartes associées à un étudiant ; le boîtier la garde en local (elle marche donc hors ligne). Le bip d'une carte inconnue est quand même enregistré, pour pouvoir l'attribuer ensuite. Sur le boîtier d'accueil, mettre `CONTROLE_CARTES=0` : il sert justement à enregistrer des cartes nouvelles.
* **Carte mal lue :** un échec isolé est réessayé en silence ; la LED rouge s'allume si la carte reste mal lue 1 s d'affilée (`ECHEC_LECTURE_S`). Pour tester : poser deux cartes l'une sur l'autre, ou taper `!` en mode `--simulation`.

## Câblage (BCM)

| Élément | GPIO |
|---|---|
| LED bleue / verte / rouge | 17 / 27 / 22 |
| Buzzer (actif, sonne à l'état bas) | 14 |
| RC522 : SDA, SCK, MOSI, MISO, RST | 8, 11, 10, 9, 25 (SPI) |
| RTC DS3231 : SDA, SCL | 2, 3 (I2C) |

## Installation

1. Copier le dossier `boitier` sur le Pi, dans `/home/pi/boitier` (clé USB, `scp` ou `git clone`).
2. Dans l'interface web : **Configuration > Boîtiers**, créer le boîtier et copier son token.
3. Sur le Pi :
   ```bash
   cd ~/boitier
   bash installer.sh
   nano .env            # SERVEUR_URL, DEVICE_ID, API_TOKEN
   sudo systemctl restart pointage-boitier   # relance avec le .env complété
   ```
4. Le boîtier démarre ensuite tout seul à chaque allumage. Journal : `journalctl -u pointage-boitier -f`.
   Le service porte le nom du dossier (`pointage-boitier_acceuil` pour le dossier `boitier_acceuil`). Un seul lecteur NFC par Pi : lancer `installer.sh` dans un dossier arrête le service de l'autre.

## Un seul Raspberry pour la salle et l'accueil

Un même Raspberry peut jouer le rôle de plusieurs boîtiers, un à la fois, avec un fichier de configuration par boîtier :

```bash
cp .env .env.accueil
nano .env.accueil      # DEVICE_ID=RPI-ACCUEIL, API_TOKEN=token de RPI-ACCUEIL, ANTI_REBOND_S=5, CONTROLE_CARTES=0
venv/bin/python boitier.py --config .env.accueil
```

Chaque configuration a sa propre base locale (`pointages_RPI-ACCUEIL.db`) : les bips gardés hors ligne partent toujours avec le bon identifiant de boîtier.

## Tester sans Raspberry Pi

```bash
pip install requests python-dotenv
python boitier.py --simulation
```
Les UID se tapent au clavier et les LED s'affichent dans la console.

## Fichiers

| Fichier | Rôle |
|---|---|
| `boitier.py` | programme principal (boucle de lecture) |
| `materiel.py` | lecteur NFC, LED, buzzer (+ versions simulées) |
| `stockage.py` | base SQLite locale |
| `synchro.py` | envoi au serveur, gestion du hors-ligne |
| `config.py` | paramètres (`.env`) et câblage |
| `installer.sh`, `pointage-boitier.service` | installation et démarrage automatique |
