"""La langue de l'interface (§9.8 de l'analyse) : anglais par défaut, et français.

Tout ce que voit l'opérateur passe par `t()`. Le texte français sert de clé :
le code se lit dans sa langue, et la traduction anglaise vit à côté, dans
`traductions.py`. Les valeurs variables sont des champs nommés, remplis après
la traduction :

    t("trop petit : {requis} requis", requis=texte.taille(n))

Une phrase absente du catalogue s'affiche en français plutôt que de faire
échouer l'écran ; un test vérifie qu'il n'en manque aucune.
"""

from __future__ import annotations

from .traductions import ANGLAIS as _ANGLAIS

ANGLAIS = "en"
FRANCAIS = "fr"

# Dans l'ordre du menu de F2, chaque langue dans sa propre langue.
LANGUES = {ANGLAIS: "English", FRANCAIS: "Français"}

_actuelle = ANGLAIS


def actuelle() -> str:
    return _actuelle


def choisir(code: str) -> None:
    global _actuelle
    if code in LANGUES:
        _actuelle = code


def t(texte: str, **valeurs) -> str:
    modele = _ANGLAIS.get(texte, texte) if _actuelle == ANGLAIS else texte
    return modele.format(**valeurs) if valeurs else modele
