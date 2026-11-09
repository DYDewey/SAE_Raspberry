# Analyse des performances

Les chiffres sont mesurés avec `boitier/mesure_perf.py`. Chaque mesure ajoute une ligne à `boitier/mesures_perf.csv`.

## 1. Objectifs

On part du besoin réel : un groupe de TP compte environ 30 étudiants, et l'appel ne doit pas retarder le début du cours.

| Critère | Objectif | Origine |
|---|---|---|
| Démarrage (prise → boîtier prêt) | < 30 s | le prof branche le boîtier en arrivant |
| Lecture d'une carte | < 20 ms | livrable 1 |
| Écriture locale d'un bip | < 50 ms | livrable 1 |
| Enchaînement des bips | ≥ 30 étudiants/minute | un groupe de TP badgé en 1 minute |
| Synchro après une journée hors ligne (≈ 500 bips) | < 10 s | les données arrivent vite au retour du réseau |
| Plusieurs boîtiers en même temps | aucune perte, aucun doublon | cours en parallèle |

## 2. Méthode

| Mesure | Commande | Ce qui est chronométré |
|---|---|---|
| Écriture SQLite | `python mesure_perf.py sqlite -n 1000` | `Stockage.ajouter()` : insertion + commit sur la carte SD |
| Lecture NFC | `python mesure_perf.py lecture -n 30` | `LecteurNFC.lire_uid()` quand une carte est posée |
| Enchaînement | `python mesure_perf.py enchainement -n 20` | cycle complet d'un bip (lecture + SQLite + LED/buzzer) et intervalle entre deux bips |
| Synchronisation | `python mesure_perf.py synchro --tailles 10 100 1000 5000` | temps pour vider une file de N bips vers le serveur (lots de 100) |
| Concurrence | `python mesure_perf.py concurrence --boitiers 5 -n 200` | 5 boîtiers simulés envoient en même temps |
| Démarrage | `python mesure_perf.py demarrage` (après un redémarrage) | `systemd-analyze` + instant où le journal affiche « Boîtier prêt » |

**Règles suivies :**
* chaque mesure est répétée (n ≥ 20) ; on donne la **médiane** et le **95e centile** (p95) plutôt que la moyenne, pour ne pas se laisser tromper par une valeur isolée ;
* pour l'enchaînement, deux personnes passent 20 cartes différentes le plus vite possible ;
* pour la synchro, on utilise un boîtier de test (`PERF-01`) dont les bips factices sont effacés ensuite (`DELETE FROM pointages WHERE device_id = 'PERF-01';`) ;
* les bips de test sont écrits dans une base SQLite temporaire : la vraie file d'attente du boîtier n'est pas touchée.

## 3. Résultats

### 3.1 Sur le PC de développement (serveur local, base jetable) — 09/11/2026

| Mesure | Médiane | p95 | Remarque |
|---|---|---|---|
| Écriture SQLite d'un bip | 0,45 ms | 0,74 ms | SSD, 500 écritures |
| Synchro de 10 bips | 49 ms | — | |
| Synchro de 100 bips | 133 ms | — | 754 bips/s |
| Synchro de 1 000 bips | 1,26 s | — | 793 bips/s |
| Synchro de 5 000 bips | 6,6 s | — | 754 bips/s, débit stable |
| 3 boîtiers × 100 bips en même temps | 2,3 s | 2,5 s | 0 perte, 0 doublon |

### 3.2 Sur le Raspberry Pi — 09/11/2026

Pi 3 Model B, Raspberry Pi OS **avec bureau** (pas Lite), lecteur RC522. Serveur : PC de dev sur le même réseau (10.125.17.x), **vraie base PostgreSQL** (sauvegardée avant, données de test effacées après).

| Mesure | Médiane | p95 / max | Objectif | OK ? |
|---|---|---|---|---|
| Démarrage : noyau → « Boîtier prêt » | 16,1 s | — | < 30 s | ✅ |
| Lecture NFC (`lire_uid`, 20 lectures) | 2,4 ms | p95 2,6 ms, max 25,7 ms | < 20 ms | ✅ (0 lecture ratée) |
| Écriture SQLite d'un bip (carte SD) | 7,4 ms | p95 10,2 ms, max 75 ms | < 50 ms | ✅ |
| Cycle complet d'un bip (lecture + SQLite + signal) | 714 ms | max 717 ms | — | ≈ 700 ms = signal LED/buzzer |
| Intervalle entre deux bips | 2,6 s | max 2,8 s | ≤ 2 s | ⚠️ voir remarque |
| Débit réel | 23 bips/min | — | ≥ 30 | ⚠️ voir remarque |
| Synchro de 10 bips | 164 ms | — | | |
| Synchro de 100 bips | 434 ms | — | | 230 bips/s |
| Synchro de 1 000 bips | 4,7 s | — | < 10 s pour 500 | ✅ (500 bips ≈ 2,4 s) |
| Synchro de 5 000 bips | 24,1 s | — | | 207 bips/s, débit stable |
| 5 boîtiers × 200 bips en même temps | 3,3 s | max 3,3 s | 0 perte | ✅ 1 000/1 000 reçus, 0 doublon |

**Remarque sur l'enchaînement :** le test a été fait par **une seule personne avec 4 cartes** (il faut des cartes différentes). L'intervalle de 2,6 s mesure surtout le temps de poser la carte, la retirer et prendre la suivante. Le logiciel, lui, est prêt pour la carte suivante après 0,72 s, soit environ **84 bips/minute** au maximum. Avec une vraie file d'étudiants, chacun ayant sa carte en main, l'objectif de 30/min reste atteignable, mais **il faut refaire la mesure en conditions réelles** (un groupe de TP).

**Vérification des pertes :** après les tests, le serveur contenait exactement 7 110 bips du boîtier `PERF-01` (10 + 100 + 1 000 + 5 000 + 5 × 200) : aucun perdu, aucun en double.

## 4. Goulets d'étranglement repérés

| # | Goulet | Effet | Amélioration possible |
|---|---|---|---|
| 1 | **Nom d'hôte au lieu d'une IP** dans `SERVEUR_URL` (`localhost` sous Windows) | +2 s par envoi : la synchro de 1 000 bips passe de 1,3 s à 21,7 s (mesuré). Windows essaie d'abord l'IPv6 avant de se rabattre sur l'IPv4 | mettre l'**adresse IP** du serveur dans le `.env` (c'est ce que dit le guide d'installation) |
| 2 | **Signal de réussite bloquant** (LED verte + bip ≈ 0,8 s) | le lecteur ne lit pas de carte pendant le signal, ce qui plafonne théoriquement à environ 70 bips/minute | c'est voulu : l'étudiant doit voir que son bip est pris. On pourrait jouer le signal dans un thread à part et raccourcir la LED à 0,4 s |
| 3 | **Carte inconnue avec serveur joignable** | le boîtier envoie le bip tout de suite et attend la réponse pour savoir si c'est un enrôlement : un aller-retour réseau dans la boucle de lecture (≤ `DELAI_HTTP` = 5 s si le réseau est lent) | baisser le délai pour cet envoi précis (1 s) ; ne vérifier l'enrôlement que si une page « Scanner la carte » est ouverte |
| 4 | **Serveur : une requête par bip** (contrôle du doublon + recherche de la séance) | débit plafonné autour de 750 bips/s sur le PC | charger d'un coup les uuid déjà reçus et l'emploi du temps du jour ; largement suffisant aujourd'hui (une journée = quelques centaines de bips) |
| 5 | **Liste des cartes connues renvoyée à chaque envoi** | réponse qui grossit avec le nombre de cartes (≈ 200 cartes = quelques ko) | envoyer la liste seulement si elle a changé (numéro de version) |
| 6 | **Démarrage du Pi** | 18,5 s jusqu'à la fin du boot (4,4 s noyau + 14,2 s services) ; le service du boîtier ne démarre qu'à 12,5 s | l'OS installé **n'est pas Lite** (bureau graphique lancé) : passer à Raspberry Pi OS Lite ; désactiver le Bluetooth (`hciuart` = 6,3 s à lui seul) |
| 7 | **Débit de la synchro sur le Pi** (≈ 210 bips/s, contre 750 sur PC) | le Pi 3 est plus lent pour lire SQLite et préparer le JSON, et le réseau ajoute de la latence | sans importance en pratique : une journée hors ligne (≈ 500 bips) repart en ≈ 2,4 s |
| 8 | **Pic d'écriture SQLite sur la carte SD** (max 75 ms, médiane 7 ms) | quelques écritures lentes quand la carte SD vide son cache | reste sous l'objectif ; une carte SD de classe A1/A2 réduirait ces pics |

## 5. Analyse

* **Côté boîtier**, la lecture et l'écriture locale sont très en dessous des objectifs : ce qui limite le débit, c'est le temps que met un humain à présenter sa carte et le signal de 0,8 s, pas le logiciel.
* **La synchronisation** passe par lots de 100 bips. Le débit reste stable quand la file grossit (5 000 bips en moins de 7 s sur PC) : une journée entière hors ligne repart en quelques secondes.
* **Plusieurs boîtiers** peuvent envoyer en même temps sans perte ni doublon, car chaque bip a un uuid unique et le serveur ignore un uuid déjà reçu.
* **PC et Pi comparés :** l'écriture SQLite est 16 fois plus lente sur le Pi (7,4 ms contre 0,45 ms, à cause de la carte SD) et la synchro 3,5 fois plus lente (210 contre 750 bips/s). Les deux restent pourtant **largement sous les objectifs**, et la lecture NFC (2,4 ms) n'est jamais le facteur limitant.
* **Ce qui limite vraiment le boîtier**, c'est le signal de réussite (≈ 0,7 s) et le geste de l'étudiant. Pour le démarrage, c'est l'OS avec bureau. Ce sont les deux améliorations les plus utiles (goulets 2 et 6).
* **Mesure manquante :** l'enchaînement en conditions réelles (un groupe de TP qui badge à la suite).
