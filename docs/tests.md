# Résultats des tests

Tests automatiques avec **pytest**. Ils tournent sur une base SQLite jetable (`tests/conftest.py`) : la vraie base PostgreSQL n'est jamais touchée.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

**Résultat au 23/10/2026 : 33 tests, 33 réussis (≈ 6 s).**

## API de synchronisation — `tests/test_api_sync.py` (10)

| Test | Ce qui est vérifié |
|---|---|
| `test_boitier_inconnu_refuse` | boîtier inconnu ou mauvais token → 401 |
| `test_pointages_enregistres_et_rattaches_au_cours` | un bip est enregistré et rattaché au bon cours |
| `test_uid_normalise` | `10:d6:5d:56` devient `10D65D56` |
| `test_renvoi_du_meme_lot_sans_doublon` | renvoyer un lot ne crée pas de doublon (idempotence) |
| `test_meme_uuid_deux_fois_dans_un_lot` | un même uuid répété dans un lot n'est gardé qu'une fois |
| `test_date_illisible_rejetee_sans_bloquer_le_lot` | un bip invalide est rejeté, les autres passent |
| `test_carte_inconnue_enregistree` | le bip d'une carte non associée est conservé |
| `test_lot_vide_signal_de_vie` | un lot vide met à jour « dernière synchro » |
| `test_deux_boitiers_en_parallele` | deux boîtiers simultanés, chacun rattaché à son cours |
| `test_bip_hors_cours_garde_sans_seance` | un bip hors cours est gardé sans séance |

## Boîtier hors ligne — `tests/test_boitier.py` (9)

| Test | Ce qui est vérifié |
|---|---|
| `test_bip_enregistre_en_local_avant_envoi` | le bip est en SQLite avant tout envoi |
| `test_hors_connexion_rien_perdu` | serveur injoignable → bips conservés |
| `test_retour_reseau_synchronisation_automatique` | au retour du réseau, tout part tout seul |
| `test_redemarrage_sans_perte` | coupure de courant / redémarrage → rien perdu |
| `test_coupure_pendant_synchro_sans_doublon` | coupure pendant l'accusé de réception → pas de doublon |
| `test_token_refuse_pointages_gardes` | token refusé → bips gardés |
| `test_cartes_connues_recues_du_serveur` | la liste des cartes connues est stockée en local |
| `test_nettoyage_garde_les_non_envoyes` | le nettoyage ne supprime jamais un bip non envoyé |
| `test_mille_bips_hors_ligne_puis_synchro` | 1 000 bips hors ligne puis synchro complète (≈ 1,3 s) |

## Calcul des présences — `tests/test_presences.py` (8)

| Test | Ce qui est vérifié |
|---|---|
| `test_statut_depuis` | Présent / En retard selon l'heure du premier bip |
| `test_taux` | calcul du taux de présence |
| `test_cours_sans_appel_ne_compte_pas` | cours sans aucun bip exclu des calculs |
| `test_appel_fait_present_retard_absent` | les trois statuts sur un cours avec appel |
| `test_correction_manuelle_prioritaire` | la correction du professeur l'emporte sur le bip |
| `test_correction_manuelle_seule_vaut_appel` | une correction seule suffit à compter le cours |
| `test_etudiant_autre_groupe_non_compte` | un étudiant d'un autre groupe n'est pas compté |
| `test_bloc_de_deux_creneaux` | deux créneaux consécutifs = un seul cours |

## Filtrage des pointages — `tests/test_pointages.py` (5)

| Test | Ce qui est vérifié |
|---|---|
| `test_sans_filtre_tous_les_bips_du_jour` | par défaut, les bips du jour |
| `test_filtre_etudiant_par_nom_ou_uid` | recherche par nom ou par UID |
| `test_filtres_groupe_enseignement_salle` | filtres groupe, enseignement, salle |
| `test_plage_horaire_et_combinaison` | plage horaire et filtres combinés |
| `test_plage_de_dates` | plage de dates (même inversée) |

## Tests manuels

| Scénario | Résultat |
|---|---|
| Sauvegarde `pg_dump` puis restauration dans une base vide | OK, même nombre de pointages (44) |

À compléter avec les essais sur le vrai Raspberry Pi (voir `performances.md`).
