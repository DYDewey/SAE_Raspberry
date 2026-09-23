# Système de Gestion d'Assiduité IUT (NFC + FastAPI)

Application web de gestion des présences et des emplois du temps développée dans le cadre d'une SAE en IUT. Le système permet de synchroniser automatiquement les plannings iCal de l'université, de gérer les étudiants avec un système multi-groupes (Many-to-Many), d'associer des badges NFC et de générer des feuilles d'émargement officielles au format Excel.

---

## Stack Technique

* **Back-end :** FastAPI (Python)
* **Base de données :** PostgreSQL avec SQLAlchemy (ORM)
* **Gestion des données :** Pandas & Openpyxl (traitement Excel)
* **Templates / UI :** Jinja2, Bootstrap 5
* **Synchro Agenda :** iCalendar (`icalendar`)

---

## Fonctionnalités principales

1. **Synchronisation EDT (iCal) :** Récupération automatique des emplois du temps de la semaine, fusion intelligente des blocs de cours consécutifs et gestion propre des professeurs.
2. **Gestion des Étudiants & Multi-groupes :** Association d'un étudiant à plusieurs groupes en même temps (ex: `BUT1`, `BUT1-TD1`, `BUT1-TPA`) via une relation Many-to-Many.
3. **Association NFC Rapide :** Liaison des badges NFC (`nfc_uid`) directement depuis le tableau de bord administrateur en un clin d'œil.
4. **Feuilles d'Émargement & Export Excel :** Suivi des présences par séance et export d'un fichier Excel professionnel intégrant toutes les métadonnées (cours, professeur, salle, horaires, groupe).

---

## Installation et Lancement

### 1. Cloner le projet et configurer l'environnement virtuel
```bash
git clone https://github.com/DYDewey/SAE_Raspberry
cd SAE_Backend
python -m venv venv
# Activer l'environnement virtuel :
# Sur Windows :
venv\Scripts\activate
# Sur Linux/Mac :
source venv/bin/activate