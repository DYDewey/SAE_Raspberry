# Résultats des tests

Tests automatiques avec **pytest**. Ils tournent sur une base SQLite jetable (`tests/conftest.py`) : la vraie base PostgreSQL n'est jamais touchée.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

**Résultat au 09/11/2026 : 53 tests, 53 réussis (≈ 24 s).**

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

## Absences justifiées — `tests/test_justificatifs.py` (6) et `tests/test_justificatifs_web.py` (1)

| Test | Ce qui est vérifié |
|---|---|
| `test_absence_dans_la_periode_justifiee` | absence le jour du justificatif → justifiée ; taux de présence inchangé, pas « à risque » |
| `test_absence_hors_periode_non_justifiee` | justificatif qui finit la veille ou commence le lendemain → sans effet |
| `test_justificatif_d_un_autre_etudiant_sans_effet` | le justificatif ne vaut que pour son étudiant |
| `test_retard_jamais_justifie` | un retard reste un retard |
| `test_detail_historique_et_classe` | fiche, liste détaillée et bilan par classe comptent les absences justifiées |
| `test_fin_annee_efface_les_justificatifs` | l'anonymisation supprime les justificatifs (motif médical, RGPD) |
| `test_ajout_affichage_export_suppression` | de bout en bout : saisie (fin avant début refusée), pages, 3 exports Excel, suppression |

## Import des étudiants — `tests/test_import_etudiants.py` (6)

| Test | Ce qui est vérifié |
|---|---|
| `test_groupes_depuis_colonnes` | ANNEE / PARCOURS / TD / TP → groupes ADE, apprentis compris |
| `test_liste_scolarite_sans_numero` | liste sans numéro importée, numéros provisoires `PROV-0001`… |
| `test_reimport_sans_doublon_et_changement_de_groupe` | réimport : pas de doublon, changement de TP pris en compte |
| `test_vrai_numero_remplace_le_provisoire` | un fichier avec numéros remplace `PROV-…` (accents ignorés) |
| `test_ancien_format_avec_numero` | l'ancien format numero / nom / prenom / groupe marche toujours |
| `test_homonyme_avec_vrai_numero_pas_ecrase` | deux homonymes aux numéros différents restent deux étudiants |

## Tests manuels

| Scénario | Résultat |
|---|---|
| Sauvegarde `pg_dump` puis restauration dans une base vide | OK, même nombre de pointages (44) |
| Justificatif ajouté puis supprimé dans le navigateur (vraie base PostgreSQL) | OK : badges « Justifiée » sur la fiche, « dont 4 justifiées » sur la page Absences |
| Import de la vraie liste de la scolarité (173 étudiants), puis réimport simulé | OK : 173 ajoutés, réimport = 0 ajout, 0 modification |

À compléter avec les essais sur le vrai Raspberry Pi (voir `performances.md`).

## Menu Aide (tutoriels) — `tests/test_aide.py` (5)

| Test | Ce qui est vérifié |
|---|---|
| `test_non_connecte_renvoye_vers_login` | l'aide n'est pas accessible sans connexion |
| `test_admin_voit_les_trois_tutos` | l'administrateur voit et ouvre les 3 tutoriels |
| `test_prof_ne_voit_que_le_tuto_enseignant` | un prof ne voit que le tuto enseignant ; les autres → 403 |
| `test_tuto_inconnu` | tuto inexistant → 404 |
| `test_lien_aide_dans_le_menu` | le lien Aide est dans le menu |

## Feuille d'émargement — `tests/test_emargement_appel.py` (2)

Bug trouvé en faisant les captures des tutos : le bandeau « Pas d'appel » s'affichait sur tous les cours passés.

| Test | Ce qui est vérifié |
|---|---|
| `test_pas_de_bandeau_quand_des_etudiants_ont_badge` | cours avec badges : pas de bandeau (page et panneau) |
| `test_bandeau_quand_personne_n_a_badge` | cours sans aucun badge : le bandeau s'affiche |
