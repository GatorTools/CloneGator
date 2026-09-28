"""Chaque phrase montrée à l'opérateur a sa traduction anglaise (§9.8).

On parcourt le code : tout appel `t("…")` dont le premier argument est un texte
littéral doit avoir son entrée dans `traductions.ANGLAIS`, avec exactement les
mêmes champs {…}. Une phrase oubliée s'afficherait en français à un
anglophone ; un champ oublié ferait échouer l'écran.
"""

import ast
import string
import unittest
from pathlib import Path

from clonegator.traductions import ANGLAIS

RACINE = Path(__file__).resolve().parent.parent / "clonegator"


def textes_du_code() -> dict[str, str]:
    """Texte → premier endroit où il apparaît."""
    trouves = {}
    for fichier in sorted(RACINE.rglob("*.py")):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name) and noeud.func.id == "t"
                    and noeud.args and isinstance(noeud.args[0], ast.Constant)
                    and isinstance(noeud.args[0].value, str)):
                trouves.setdefault(noeud.args[0].value, f"{fichier.relative_to(RACINE.parent)}:{noeud.lineno}")
    return trouves


def champs(texte: str) -> set[str]:
    return {nom for _, nom, _, _ in string.Formatter().parse(texte) if nom}


class Traductions(unittest.TestCase):
    def test_chaque_phrase_a_sa_traduction(self):
        manquantes = [f"{ou} : {texte!r}" for texte, ou in textes_du_code().items() if texte not in ANGLAIS]
        self.assertEqual(manquantes, [], "phrases sans traduction anglaise :\n" + "\n".join(manquantes))

    def test_memes_champs_des_deux_cotes(self):
        differents = [f"{fr!r} → {en!r}" for fr, en in ANGLAIS.items() if champs(fr) != champs(en)]
        self.assertEqual(differents, [])

    def test_pas_de_traduction_orpheline(self):
        orphelines = sorted(set(ANGLAIS) - set(textes_du_code()))
        self.assertEqual(orphelines, [], "traductions que le code n'utilise plus")


if __name__ == "__main__":
    unittest.main()
