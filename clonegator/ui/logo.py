"""Le logo GatorTools de l'écran d'accueil, à la taille de l'écran.

`logo.txt` est une grille fine tirée du logo par `outils/fabriquer-logo.py` :
« v » vert, « b » blanc, espace pour le fond. On la réduit ici à la plus
grande taille qui tient dans l'écran, sans dépasser LARGEUR_MAX ; en dessous de
LARGEUR_MIN, les formes ne se lisent plus et l'écran d'accueil montre le texte
seul.
"""

from __future__ import annotations

import os

VERT = "v"
BLANC = "b"

LARGEUR_MAX = 170
LARGEUR_MIN = 60

_FICHIER = os.path.join(os.path.dirname(__file__), "logo.txt")
_grille: list[str] | None = None


def _base() -> list[str]:
    global _grille
    if _grille is None:
        with open(_FICHIER, encoding="utf-8") as fichier:
            lignes = fichier.read().splitlines()
        largeur = max(len(ligne) for ligne in lignes)
        _grille = [ligne.ljust(largeur) for ligne in lignes]
    return _grille


def reduire(largeur_max: int, hauteur_max: int) -> list[str] | None:
    """La grille à la plus grande taille qui tient, ou None si elle serait
    trop petite pour se lire."""
    base = _base()
    base_l, base_h = len(base[0]), len(base)
    largeur = min(LARGEUR_MAX, largeur_max)
    hauteur = round(largeur * base_h / base_l)
    if hauteur > hauteur_max:
        hauteur = hauteur_max
        largeur = round(hauteur * base_l / base_h)
    if largeur < LARGEUR_MIN or hauteur < 1:
        return None

    # Chaque case réduite prend la couleur qui couvre plus de la moitié de sa
    # zone dans la grille fine.
    lignes = []
    for r in range(hauteur):
        y0, y1 = r * base_h // hauteur, max((r + 1) * base_h // hauteur, r * base_h // hauteur + 1)
        ligne = []
        for c in range(largeur):
            x0, x1 = c * base_l // largeur, max((c + 1) * base_l // largeur, c * base_l // largeur + 1)
            vert = blanc = 0
            for y in range(y0, y1):
                morceau = base[y][x0:x1]
                vert += morceau.count(VERT)
                blanc += morceau.count(BLANC)
            moitie = (y1 - y0) * (x1 - x0) / 2
            ligne.append(VERT if vert > moitie else BLANC if blanc > moitie else " ")
        lignes.append("".join(ligne))
    return lignes
