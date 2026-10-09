"""Hiérarchie des groupes, déduite de leur nom.

ADE découpe une classe en sous-groupes : BUT3 > BUT3-TD3 > BUT3-TD3-PA / BUT3-TD3-PB.
Un cours peut viser n'importe quel niveau (CM de BUT3, TD de BUT3-TD3, TP de BUT3-TD3-PB...).
Les TD d'apprentis s'appellent BUT3-TD2-APP dans ADE (avec leurs demi-groupes BUT3-TD2-PA /
BUT3-TD2-PB) : "-APP" ne change pas le groupe, BUT3-TD2-APP est traité comme BUT3-TD2.

Règle : un étudiant est attendu à un cours si l'un de ses groupes "les plus précis"
est le groupe du cours, un sous-groupe de celui-ci ou un groupe parent.
  - inscrit en BUT3-TD3       -> attendu en BUT3 (CM), BUT3-TD3, BUT3-TD3-PA et BUT3-TD3-PB
  - inscrit en BUT3-TD3-PA    -> attendu en BUT3, BUT3-TD3, BUT3-TD3-PA (pas en PB)
  - inscrit en BUT3-TD2       -> attendu aux cours de BUT3-TD2-APP (TD d'apprentis)
  - inscrit en BUT3 + BUT3-TD1 -> BUT3-TD1 est plus précis : pas attendu en BUT3-TD2
  - inscrit en BUT3-TD3 + BUT3-TPB (format de la liste des étudiants) -> traité comme
    BUT3-TD3-PB : attendu en BUT3, BUT3-TD3, BUT3-TD3-PB et BUT3-TPB, pas en BUT3-TD3-PA
"""
import re


def cle(nom: str) -> str:
    """Nom sans le suffixe apprentis d'ADE : 'BUT3-TD2-APP' -> 'BUT3-TD2'."""
    return nom[:-4] if re.fullmatch(r"BUT\d-TD\d+-APP", nom) else nom


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


def plus_precis(noms) -> list:
    """Garde les groupes qui n'ont pas de sous-groupe dans la liste."""
    noms = list(noms)
    return [n for n in noms if not any(m != n and m.startswith(n + "-") for m in noms)]


def groupe_affiche(noms) -> str:
    """Groupe le plus précis d'un étudiant, au format d'ADE, pour l'affichage :
    ['BUT3', 'BUT3-TD3', 'BUT3-TPB'] -> 'BUT3-TD3-PB'."""
    precis = plus_precis(avec_demi_groupes(dict.fromkeys(cle(n) for n in noms)))
    demis = [n for n in precis if re.fullmatch(r"BUT\d-TD\d+-P[A-Z]", n)]
    # Le TP seul (BUT3-TPB) est déjà dans le demi-groupe BUT3-TD3-PB : on ne le répète pas
    precis = [n for n in precis if not (re.fullmatch(r"BUT\d-TP[A-Z]", n)
                                        and any(d.startswith(n[:4]) and d.endswith("-P" + n[-1]) for d in demis))]
    return ", ".join(sorted(precis))


def etudiant_concerne(noms_groupes_etudiant, nom_groupe_cours: str) -> bool:
    noms = list(dict.fromkeys(cle(n) for n in noms_groupes_etudiant))
    return any(sont_lies(g, nom_groupe_cours) for g in plus_precis(avec_demi_groupes(noms)))
