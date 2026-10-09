"""Hiérarchie des groupes, déduite de leur nom.

ADE découpe une classe en sous-groupes : BUT3 > BUT3-TD3 > BUT3-TD3-APP / BUT3-TD3-PB.
Un cours peut viser n'importe quel niveau (CM de BUT3, TD de BUT3-TD3-APP...).

Règle : un étudiant est attendu à un cours si l'un de ses groupes "les plus précis"
est le groupe du cours, un sous-groupe de celui-ci ou un groupe parent.
  - inscrit en BUT3-TD3       -> attendu en BUT3 (CM), BUT3-TD3, BUT3-TD3-APP et BUT3-TD3-PB
  - inscrit en BUT3-TD3-APP   -> attendu en BUT3, BUT3-TD3, BUT3-TD3-APP (pas en PB)
  - inscrit en BUT3 + BUT3-TD1 -> BUT3-TD1 est plus précis : pas attendu en BUT3-TD2
"""


def parents(nom: str) -> list:
    """'BUT3-TD3-APP' -> ['BUT3', 'BUT3-TD3']"""
    if not nom.startswith("BUT"):
        return []
    morceaux = nom.split("-")
    return ["-".join(morceaux[:i]) for i in range(1, len(morceaux))]


def sont_lies(a: str, b: str) -> bool:
    """Même groupe, ou l'un est un sous-groupe de l'autre."""
    return a == b or a.startswith(b + "-") or b.startswith(a + "-")


def plus_precis(noms) -> list:
    """Garde les groupes qui n'ont pas de sous-groupe dans la liste."""
    noms = list(noms)
    return [n for n in noms if not any(m != n and m.startswith(n + "-") for m in noms)]


def etudiant_concerne(noms_groupes_etudiant, nom_groupe_cours: str) -> bool:
    return any(sont_lies(g, nom_groupe_cours) for g in plus_precis(noms_groupes_etudiant))
