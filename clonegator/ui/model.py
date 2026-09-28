"""Ce que l'interface affiche et comment elle réagit aux touches, sans curses.

Tout ce qui se décide ici — où va le curseur, quel disque est coché, ce qu'on a
tapé dans un champ — est une structure de données ordinaire : on peut la
tester, et l'imprimer en texte brut, sans jamais ouvrir un écran. `ecran.py`
ne fait que dessiner ces structures et traduire les touches.

Les touches arrivent déjà traduites : « haut », « bas », « entree », « espace »,
« echap », « effacer », « tab », un chiffre « 1 » à « 9 », ou un caractère.

Un écran peut être reconstruit à tout moment, dans une autre langue (F2) :
`reprendre` recopie dans la nouvelle structure ce que l'opérateur avait fait
dans l'ancienne — curseur, cases cochées, texte saisi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..langue import t

# Styles d'un morceau de ligne ; ecran.py leur donne couleur et graisse. Une
# couleur n'a qu'un sens : vert, le choix et la réussite ; rouge, l'échec et
# l'effacement ; gris, ce qui n'est pas disponible (§9.8).
NORMAL = "normal"
FORT = "fort"
GRISE = "grise"
OK = "ok"
ECHEC = "echec"
AVERTISSEMENT = "avertissement"
DETAIL = "detail"  # le second plan : nom sdX, partitions, explications
AIDE = DETAIL

# Ce qu'une touche provoque dans une liste ou un formulaire.
VALIDER = "valider"
RETOUR = "retour"

# Symboles, tous présents dans la police de la console (Uni2-Fixed16).
CURSEUR = "▶"
BARRE_PLEINE = "█"
BARRE_VIDE = "░"
CROIX = "✗"
POINT = "●"


@dataclass
class Ligne:
    """Une ligne d'écran : des morceaux de texte, chacun avec son style."""

    morceaux: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def de(cls, texte: str = "", style: str = NORMAL) -> "Ligne":
        return cls([(texte, style)])

    def texte(self) -> str:
        return "".join(t for t, _ in self.morceaux)


def barre(fraction: float, largeur: int = 30) -> list[tuple[str, str]]:
    """Une barre de progression : la part faite en vert, le reste en gris."""
    fraction = max(0.0, min(1.0, fraction))
    pleine = int(round(fraction * largeur))
    return [(BARRE_PLEINE * pleine, OK), (BARRE_VIDE * (largeur - pleine), GRISE)]


@dataclass
class Element:
    """Un choix d'une liste. Un élément inactif reste visible, grisé, avec son
    motif : on comprend ainsi pourquoi un disque manque (§9.3)."""

    libelle: str
    valeur: object = None
    actif: bool = True
    motif: str = ""
    detail: str = ""  # ajouté en second plan, après le libellé
    forcable: bool = False  # un refus que l'opérateur peut lever (touche F)
    motif_force: str = ""  # ce qu'on affiche une fois forcé


@dataclass
class Liste:
    titre: str
    elements: list[Element]
    multiple: bool = False
    explication: str = ""
    curseur: int = 0
    coches: set[int] = field(default_factory=set)
    message: str = ""  # une remarque passagère, par exemple « cochez au moins un disque »
    valider: str = ""  # la ligne du bas d'une liste à cocher ; {n} : le nombre coché
    forces: bool = False

    def __post_init__(self):
        actifs = self._actifs()
        if actifs and self.curseur not in actifs:
            self.curseur = actifs[0]

    def _actifs(self) -> list[int]:
        """Les rangs où le curseur peut aller. Une liste à cocher se termine par
        une ligne « Continuer », au rang len(elements)."""
        rangs = [i for i, e in enumerate(self.elements) if e.actif]
        if self.multiple:
            rangs.append(len(self.elements))
        return rangs

    @property
    def sur_valider(self) -> bool:
        return self.multiple and self.curseur == len(self.elements)

    def placer(self, valeur) -> None:
        """Présélectionne l'élément qui porte cette valeur, s'il est actif."""
        for i, element in enumerate(self.elements):
            if element.valeur == valeur and element.actif:
                self.curseur = i
                return

    def cocher(self, valeurs) -> None:
        self.coches = {i for i, e in enumerate(self.elements) if e.valeur in valeurs and e.actif}

    def reprendre(self, ancienne: "Liste") -> None:
        """Garde ce que l'opérateur avait fait dans la version précédente de
        cette liste : l'écran vient d'être reconstruit."""
        if ancienne.forces:
            self._forcer()
        if len(ancienne.elements) == len(self.elements):
            self.coches = {i for i in ancienne.coches if self.elements[i].actif}
            if ancienne.curseur in self._actifs():
                self.curseur = ancienne.curseur
        self.message = ancienne.message

    def _forcer(self) -> None:
        for element in self.elements:
            if element.forcable and not element.actif:
                element.actif = True
                element.motif = element.motif_force
        self.forces = True

    def touche(self, touche: str) -> str | None:
        """Applique une touche ; rend VALIDER, RETOUR ou None."""
        self.message = ""
        actifs = self._actifs()
        if touche == "echap":
            return RETOUR
        if touche in ("f", "F") and any(e.forcable and not e.actif for e in self.elements):
            self._forcer()
            self.message = t("Disques déclarés défaillants par SMART : choisissables, à vos risques.")
            return None
        if not actifs:
            return None
        if touche in ("haut", "bas"):
            rang = actifs.index(self.curseur) if self.curseur in actifs else 0
            rang = (rang - 1) % len(actifs) if touche == "haut" else (rang + 1) % len(actifs)
            self.curseur = actifs[rang]
        elif touche.isdigit() and touche != "0":
            numero = int(touche) - 1
            if numero < len(self.elements) and self.elements[numero].actif:
                self.curseur = numero
                if self.multiple:
                    self._basculer(numero)
                else:
                    return VALIDER
        elif touche in ("espace", "entree") and self.multiple and not self.sur_valider:
            # Dans une liste à cocher, Entrée coche comme Espace ; on valide
            # sur la ligne du bas.
            self._basculer(self.curseur)
        elif touche == "entree":
            if self.multiple and not self.coches:
                self.message = t("Cochez au moins un élément avant de continuer.")
                return None
            return VALIDER
        return None

    def _basculer(self, rang: int) -> None:
        if rang in self.coches:
            self.coches.discard(rang)
        else:
            self.coches.add(rang)

    @property
    def choix(self):
        """La valeur choisie, ou la liste des valeurs cochées dans leur ordre."""
        if self.multiple:
            return [self.elements[i].valeur for i in sorted(self.coches)]
        return self.elements[self.curseur].valeur if self.elements else None

    def lignes(self) -> list[Ligne]:
        """Une ligne par élément : curseur, numéro, case, libellé aligné, puis le
        motif d'un refus ou le détail, en second plan."""
        lignes = []
        largeur = max((len(e.libelle) for e in self.elements), default=0)
        for i, element in enumerate(self.elements):
            marque = CURSEUR if i == self.curseur else " "
            numero = str(i + 1) if i < 9 else " "
            case = ""
            if self.multiple:
                case = "[x] " if i in self.coches else "[ ] "
            style = FORT if element.actif else GRISE
            libelle = element.libelle.ljust(largeur) if element.detail or element.motif else element.libelle
            ligne = Ligne([(f" {marque} {numero}  {case}{libelle}", style)])
            # Le motif d'un refus passe avant le détail : c'est lui qu'on cherche.
            if element.motif:
                ligne.morceaux.append((f"   {CROIX} {element.motif}",
                                       AVERTISSEMENT if element.actif else GRISE))
            if element.detail:
                ligne.morceaux.append((f"   {element.detail}", DETAIL if element.actif else GRISE))
            lignes.append(ligne)
        if self.multiple:
            marque = CURSEUR if self.sur_valider else " "
            modele = self.valider or t("Continuer ({n} coché(s))")
            lignes.append(Ligne.de(""))
            lignes.append(Ligne.de(f" {marque}    → {modele.format(n=len(self.coches))}", FORT))
        return lignes

    @property
    def rang_affiche(self) -> int:
        """La ligne de `lignes()` qui porte le curseur."""
        return self.curseur + (1 if self.sur_valider else 0)


@dataclass
class Champ:
    cle: str  # nom stable, pour relire la valeur, quelle que soit la langue
    libelle: str
    valeur: str = ""
    masque: bool = False  # un mot de passe : affiché en points, jamais conservé


@dataclass
class Formulaire:
    titre: str
    champs: list[Champ]
    explication: str = ""
    curseur: int = 0
    message: str = ""

    def reprendre(self, ancien: "Formulaire") -> None:
        valeurs = {champ.cle: champ.valeur for champ in ancien.champs}
        for champ in self.champs:
            champ.valeur = valeurs.get(champ.cle, champ.valeur)
        self.curseur = ancien.curseur
        self.message = ancien.message

    def touche(self, touche: str) -> str | None:
        self.message = ""
        champ = self.champs[self.curseur]
        if touche == "echap":
            return RETOUR
        if touche in ("haut",):
            self.curseur = (self.curseur - 1) % len(self.champs)
        elif touche in ("bas", "tab"):
            self.curseur = (self.curseur + 1) % len(self.champs)
        elif touche == "entree":
            if self.curseur < len(self.champs) - 1:
                self.curseur += 1
            else:
                return VALIDER
        elif touche == "effacer":
            champ.valeur = champ.valeur[:-1]
        elif touche == "espace":
            champ.valeur += " "
        elif len(touche) == 1 and touche.isprintable():
            champ.valeur += touche
        return None

    @property
    def valeurs(self) -> dict[str, str]:
        return {champ.cle: champ.valeur for champ in self.champs}

    def lignes(self) -> list[Ligne]:
        lignes = []
        largeur = max(len(c.libelle) for c in self.champs)
        for i, champ in enumerate(self.champs):
            valeur = "•" * len(champ.valeur) if champ.masque else champ.valeur
            actif = i == self.curseur
            marque = CURSEUR if actif else " "
            lignes.append(Ligne([(f" {marque} {champ.libelle:<{largeur}}  ", FORT if actif else NORMAL),
                                 (f" {valeur}{'_' if actif else ''} ", "saisie" if actif else DETAIL)]))
            lignes.append(Ligne.de(""))
        return lignes


@dataclass
class Page:
    """Ce qu'un écran montre : la question posée, des lignes d'en-tête, et en bas
    les touches utiles. Une liste ou un formulaire s'insère entre les deux.

    Pendant une opération, `operation` et `etapes` dessinent le fil des étapes
    (Cloner : Source › Cibles › Confirmation) ; `etape` est l'étape en cours."""

    titre: str
    entete: list[Ligne] = field(default_factory=list)
    touches: list[tuple[str, str]] = field(default_factory=list)
    operation: str = ""
    etapes: list[str] = field(default_factory=list)
    etape: int = -1
    mode: str = ""
