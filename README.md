# Système de pointage par badge NFC (SAE5.B.01)

Serveur et interface d'administration du système de pointage des étudiants : les boîtiers Raspberry Pi envoient les bips de cartes NFC, le serveur les rattache aux cours de l'emploi du temps et calcule les présences, retards et absences.

---

## Stack technique

* **Back-end :** FastAPI (Python), SQLAlchemy, PostgreSQL
* **Interface :** Jinja2, Bootstrap 5, Bootstrap Icons
* **Emploi du temps :** flux iCal de l'université (`icalendar`)
* **Exports :** Pandas et Openpyxl (Excel)

## Fonctionnalités

* **Tableau de bord :** cours du jour avec le nombre de présents, taux de présence sur 7 jours, état des boîtiers, derniers pointages.
* **Emploi du temps en grille semaine :** choix de la classe (les CM de la promo sont inclus), filtres professeur et salle, navigation entre les semaines, présents/inscrits sur chaque cours. Un clic sur un cours ouvre la feuille d'émargement (présent / en retard / absent, heures d'arrivée et de sortie, export Excel).
* **Étudiants :** import du fichier Excel de la scolarité, multi-groupes, association des cartes NFC (lecteur USB), recherche.
* **Suivi des absences :** bilan par classe et par période, fiche individuelle avec l'historique, exports Excel.
* **Configuration :** boîtiers (professeur attitré, token), salles, groupes, purge RGPD de fin d'année.
* **Connexion administrateur** obligatoire pour toute l'interface.

---

## Organisation du code

```
main.py              point d'entrée : crée l'application et branche les routes
config.py            paramètres lus dans le .env
database.py          connexion à PostgreSQL
models.py            tables + mise à jour automatique du schéma
web.py               outils des pages : templates, messages, connexion obligatoire

services/            logique métier (sans HTML, testable seule)
  temps.py           dates (UTC -> heure de Paris), format des UID NFC
  presences.py       rattachement pointage -> cours, calcul des présences
  ical.py            import de l'emploi du temps
  etudiants.py       import Excel, association des cartes
  export.py          génération des fichiers Excel

routers/             une partie de l'interface par fichier
  api.py             API des boîtiers (/api/v1/...)
  auth.py            connexion / déconnexion
  tableau_de_bord.py page d'accueil
  edt.py             emploi du temps et émargement
  etudiants.py       étudiants, fiche individuelle, suivi des absences
  professeurs.py     professeurs
  configuration.py   boîtiers, salles, groupes, RGPD

templates/           pages HTML (toutes héritent de base.html)
static/              CSS et JavaScript
```

---

## Installation et lancement

```bash
git clone https://github.com/DYDewey/SAE_Raspberry
cd SAE_Backend
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/Mac : source venv/bin/activate)
pip install -r requirements.txt

docker compose up -d             # PostgreSQL
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Puis ouvrir http://localhost:8000. `--host 0.0.0.0` permet aux boîtiers du réseau de joindre le serveur.
Les tables manquantes sont créées au démarrage et les tables existantes mises à jour automatiquement.

### Fichier `.env`

| Variable | Rôle | Défaut |
|---|---|---|
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Connexion PostgreSQL | — |
| `DB_HOST`, `DB_PORT` | Adresse de PostgreSQL | `localhost`, `5432` |
| `ADMIN_USER`, `ADMIN_PASSWORD` | Compte de l'interface d'administration | `admin` / `admin` |
| `SECRET_KEY` | Clé de signature des sessions (une longue chaîne aléatoire) | générée à chaque démarrage |
| `RETARD_TOLERANCE_MIN` | Minutes après le début avant d'être « En retard » | `15` |
| `AVANCE_POINTAGE_MIN` | Minutes avant le début où un bip est déjà accepté | `15` |
| `ICAL_URL` | Lien iCal ADE de l'emploi du temps | — (obligatoire pour la synchro) |
| `ICAL_SEMAINES` | Semaines importées à chaque synchro | `4` |
| `BOITIER_EN_LIGNE_MIN` | Délai après lequel un boîtier est affiché hors ligne | `10` |

Pour générer une `SECRET_KEY` : `python -c "import secrets; print(secrets.token_hex(32))"`

---

## Boîtiers Raspberry Pi

1. Dans **Configuration > Boîtiers**, créer le boîtier (identifiant, professeur attitré, salle de repli).
2. Recopier son **token** dans le `.env` du boîtier. Un boîtier inconnu ou avec un mauvais token est refusé (401) : il garde ses pointages en local et réessaie plus tard.

### API de synchronisation

`POST /api/v1/sync` avec l'en-tête `Authorization: Bearer <token>` :

```json
{
  "device_id": "RPI-001",
  "batch": [
    {"uuid": "3f2b…", "nfc_uid": "10D65D56", "timestamp": "2026-10-07T06:02:11Z"}
  ]
}
```

Réponse : `{"status": "success", "synced_uuids": [...], "rejected_uuids": [...], "server_time_utc": "..."}`.
Le boîtier marque comme synchronisés les pointages dont l'uuid est dans `synced_uuids`. Renvoyer un pointage déjà reçu est sans effet (idempotence).
`GET /api/v1/status` permet au boîtier de vérifier que le serveur répond.

### Règles de calcul

* **Heures :** le boîtier envoie de l'UTC ; le serveur stocke tout en heure de Paris (heure d'été/hiver gérée).
* **UID NFC :** hexadécimal majuscule sans séparateur (`10:d6:5d:56` → `10D65D56`), à l'enrôlement comme au pointage.
* **Rattachement :** un bip est relié au cours du professeur du boîtier qui couvre l'heure du bip (dès 15 min avant le début). À défaut, la salle du boîtier est utilisée.
* **Statut :** premier bip avant début + 15 min → *Présent*, après → *En retard*, aucun bip → *Absent*. Le dernier bip est l'heure de *Sortie*. Les créneaux qui se suivent (8h-9h30 + 9h30-11h) forment un seul cours.
* **Bilans d'absences :** seuls les cours terminés sont comptés.
* **Synchro EDT :** les cours sont mis à jour via l'UID iCal (leurs identifiants ne changent pas) et les pointages sont recalculés.
