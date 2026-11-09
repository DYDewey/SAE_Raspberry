# Tutoriels d'utilisation

| Tuto | Pour | PDF |
|---|---|---|
| Enseignant | professeurs (compte prof) | [tuto_enseignant.pdf](../../static/aide/tuto_enseignant.pdf) |
| Secrétariat | secrétariat pédagogique (compte administrateur) | [tuto_secretariat.pdf](../../static/aide/tuto_secretariat.pdf) |
| Administrateur | responsable technique | [tuto_administrateur.pdf](../../static/aide/tuto_administrateur.pdf) |

Les mêmes tutos sont lisibles **dans le site** : icône <kbd>?</kbd> du menu → `/admin/aide`.
Un professeur connecté ne voit que le tuto enseignant.

## Une seule source

```
templates/aide/<tuto>.html  ──►  page du site /admin/aide/<tuto>
          │
          └── impression (CSS @media print) ──►  PDF
```

Le PDF **est** l'impression de la page du site (page de garde et sommaire n'apparaissent qu'à l'impression) :
les deux ne peuvent pas se contredire. Pour modifier un tuto, on modifie seulement le template, puis on régénère.

## Régénérer les captures et les PDF

```bash
venv/Scripts/python -m pip install -r requirements-dev.txt   # une fois (playwright)
venv/Scripts/python outils/demo_tutos.py    # base de démo fictive : demo_tutos.db
venv/Scripts/python outils/tutos.py         # captures + PDF   (ou : captures / pdf)
```

* `outils/demo_tutos.py` crée une base **SQLite jetable** (jamais PostgreSQL) avec les 224 étudiants **fictifs**
  de `etudiants_fictifs.xlsx`, 4 profs inventés, 4 semaines de cours et ~2 200 badges envoyés par la vraie API
  des boîtiers (présences et retards calculés comme en production). → **aucune vraie donnée personnelle dans les captures (RGPD).**
* `outils/tutos.py` lance un serveur temporaire (port 8790) sur cette base, pilote **Microsoft Edge déjà installé**
  (Playwright, `channel="msedge"` : aucun navigateur à télécharger), et produit :
  * 19 captures → `static/aide/*.png` (utilisées par les templates) ;
  * 3 PDF → `static/aide/tuto_*.pdf` (bouton « Télécharger le PDF » du site).
* Comptes de la démo : administrateur `secretariat` / `demo-admin`, professeur `pmartin` / `demo-prof`.

Les captures sont faites « en direct » : refaire la commande après un changement de l'interface suffit à tout remettre à jour.

## Ce que la réalisation des captures a permis de trouver

* **Bug corrigé** : la feuille d'émargement affichait « Pas d'appel : personne n'a badgé » sur **tous** les cours passés,
  même avec des badges (la variable `appel` n'était pas transmise par `templates/edt/_emargements.html`).
  Test de non-régression : `tests/test_emargement_appel.py`.
