"""Hiérarchie des groupes, déduite de leur nom (arborescence d'ADE, IUT Info 2026-2027) :
  BUT1 > BUT1-TD1 > BUT1-TPA, BUT1-TPB ; BUT1-TD2 > TPC, TPD ; BUT1-TD3 > TPE
  BUT2 > BUT2-TD1 > BUT2-TPA-PA, BUT2-TPB-PA ; BUT2-TD2 > BUT2-TPC-PB, BUT2-TPD-PB
         BUT2-TD3-APP > BUT2-TD3-APP-PA, BUT2-TD3-APP-PB  (TD d'apprentis)
  BUT3 > BUT3-TD1 > BUT3-TPA, BUT3-TPB ; BUT3-TD2-APP > BUT3-TD2-PA ; BUT3-TD3-APP > BUT3-TD3-PB
Un cours peut viser n'importe quel niveau (CM de BUT3, TD de BUT3-TD1, TP de BUT3-TPA...).
"-APP" ne change pas le groupe : BUT3-TD2-APP est traité comme BUT3-TD2.

Règle : un étudiant est attendu à un cours si l'un de ses groupes "les plus précis"
est le groupe du cours, un sous-groupe de celui-ci ou un groupe parent. La liste des
étudiants donne le TD et le TP (BUT3-TD1 + BUT3-TPA) :
  - BUT3-TD1 + BUT3-TPA -> attendu en BUT3, BUT3-TD1, BUT3-TPA (pas en BUT3-TPB)
  - BUT3-TD3 + BUT3-TPB -> TPB n'est pas un TP du TD3 : c'est la moitié B des apprentis,
    BUT3-TD3-PB. Attendu en BUT3, BUT3-TD3-APP, BUT3-TD3-PB (pas au TP BUT3-TPB du TD1)
  - BUT3 + BUT3-TD1     -> BUT3-TD1 est plus précis : pas attendu en BUT3-TD2-APP
"""
import re


def cle(nom: str) -> str:
    """Nom sans la mention apprentis d'ADE : 'BUT3-TD2-APP' -> 'BUT3-TD2',
    'BUT2-TD3-APP-PA' -> 'BUT2-TD3-PA'."""
    return re.sub(r"^(BUT\d-TD\d+)-APP(?=-|$)", r"\1", nom)


def parents(nom: str) -> list:
    """'BUT3-TD3-PB' -> ['BUT3', 'BUT3-TD3'] ; 'BUT3-TD2-APP' -> ['BUT3']"""
    nom = cle(nom)
    if not nom.startswith("BUT"):
        return []
    morceaux = nom.split("-")
    return ["-".join(morceaux[:i]) for i in range(1, len(morceaux))]


def sont_lies(a: str, b: str) -> bool:
    """Même groupe, ou l'un est un sous-groupe de l'autre."""
    a, b = cle(a), cle(b)
    return a == b or a.startswith(b + "-") or b.startswith(a + "-")


def avec_demi_groupes(noms) -> list:
    """La liste des étudiants donne le TD et le TP séparément (BUT3-TD3 + BUT3-TPB),
    alors qu'ADE nomme le demi-groupe d'après son TD (BUT3-TD3-PB). On ajoute donc
    BUT3-TD3-PB : l'étudiant n'est plus attendu aux cours de l'autre moitié (BUT3-TD3-PA)."""
    noms = list(noms)
    for td in [n for n in noms if re.fullmatch(r"BUT\d-TD\d+", n)]:
        promo = td.split("-")[0]
        for tp in [n for n in noms if re.fullmatch(promo + r"-TP[A-Z]", n)]:
            demi = f"{td}-P{tp[-1]}"
            if demi not in noms:
                noms.append(demi)
    return noms


def td_du_tp(tp: str) -> str:
    """Dans ADE, les TP sont rangés deux par TD : BUT1-TPA/TPB sous TD1, TPC/TPD sous TD2,
    TPE sous TD3. 'BUT2-TPC' -> 'BUT2-TD2'."""
    return f"{tp[:4]}-TD{(ord(tp[-1]) - ord('A')) // 2 + 1}"


def groupes_effectifs(noms) -> list:
    """Groupes d'un étudiant tels qu'on les compare aux cours d'ADE :
    - sans la mention apprentis (cle) ;
    - avec le demi-groupe BUTn-TDk-Px (avec_demi_groupes) ;
    - sans le TP d'un autre TD : chez les apprentis (BUT2-TD3 + BUT2-TPB), la lettre du TP
      désigne seulement la moitié du TD (BUT2-TD3-APP-PB), pas le TP BUT2-TPB du TD1."""
    noms = avec_demi_groupes(dict.fromkeys(cle(n) for n in noms))
    tds = {n for n in noms if re.fullmatch(r"BUT\d-TD\d+", n)}

    def tp_d_un_autre_td(n):
        return (re.fullmatch(r"BUT\d-TP[A-Z]", n) and any(t.startswith(n[:4]) for t in tds)
                and td_du_tp(n) not in tds)
    return [n for n in noms if not tp_d_un_autre_td(n)]


def plus_precis(noms) -> list:
    """Garde les groupes qui n'ont pas de sous-groupe dans la liste."""
    noms = list(noms)
    return [n for n in noms if not any(m != n and m.startswith(n + "-") for m in noms)]


def groupe_affiche(noms) -> str:
    """Groupe le plus précis d'un étudiant, avec les noms d'ADE, pour l'affichage :
    ['BUT1', 'BUT1-TD1', 'BUT1-TPA'] -> 'BUT1-TPA'    (le TP est rangé sous son TD)
    ['BUT3', 'BUT3-TD3', 'BUT3-TPB'] -> 'BUT3-TD3-PB' (apprentis : moitié du TD3)"""
    precis = plus_precis(groupes_effectifs(noms))
    connus = {cle(n) for n in noms}
    # Demi-groupe ajouté pour le calcul : affiché seulement s'il remplace un TP d'un autre TD
    return ", ".join(sorted(n for n in precis if n in connus or f"{n[:4]}-TP{n[-1]}" not in precis))


def etudiant_concerne(noms_groupes_etudiant, nom_groupe_cours: str) -> bool:
    return any(sont_lies(g, nom_groupe_cours) for g in plus_precis(groupes_effectifs(noms_groupes_etudiant)))
