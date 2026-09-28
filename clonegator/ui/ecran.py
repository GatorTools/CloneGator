"""Dessin curses et lecture des touches (§9 de l'analyse).

Ce module ne décide de rien : il dessine les structures de `model.py` et leur
passe les touches, traduites en mots (« haut », « entree », « echap »…). Chaque
interaction — choisir dans une liste, remplir un formulaire, lire un rapport —
est une méthode bloquante, qui rend la réponse de l'opérateur.

Chaque interaction reçoit de quoi *construire* son écran plutôt que l'écran
tout fait : après `F2`, l'écran est reconstruit dans la nouvelle langue, et la
structure du modèle reprend ce que l'opérateur y avait fait.

Présentation (§9.8) : une bande verte en haut, le fil des étapes, la question,
le contenu, un message éventuel, et la barre des touches en bas. Les couleurs
soulignent, elles ne portent jamais seules une information : un état est
toujours écrit en toutes lettres.
"""

from __future__ import annotations

import curses
import time

from .. import VERSION, clavier, langue
from ..langue import t
from .model import (
    AVERTISSEMENT, CURSEUR, DETAIL, ECHEC, FORT, GRISE, NORMAL, OK, POINT, RETOUR, VALIDER,
    Element, Formulaire, Ligne, Liste, Page,
)

_TOUCHES = {
    curses.KEY_UP: "haut",
    curses.KEY_DOWN: "bas",
    curses.KEY_ENTER: "entree",
    curses.KEY_BACKSPACE: "effacer",
    curses.KEY_RESIZE: "redim",
    curses.KEY_PPAGE: "haut",
    curses.KEY_NPAGE: "bas",
}
_CARACTERES = {
    "\n": "entree", "\r": "entree", " ": "espace", "\x1b": "echap",
    "\x7f": "effacer", "\b": "effacer", "\t": "tab",
    "\x03": "echap",  # Ctrl-C, en mode brut : un retour, jamais un arrêt brutal
}

# Rendu par `touche()` quand l'écran doit être reconstruit : la langue vient de
# changer, ou le terminal de taille.
RECONSTRUIRE = "reconstruire"

# Sur une console physique, tout l'écran est redessiné à ce rythme : ce que
# quelqu'un d'autre y aurait écrit disparaît.
_REDESSIN_COMPLET = 10.0

# Le contenu tient dans une colonne centrée : sur un grand écran, il ne reste
# pas collé au bord gauche.
MARGE = 2
LARGEUR_CONTENU = 110

# Styles supplémentaires, propres au dessin.
_BANDE = "bande"
_SELECTION = "selection"
_BARRE = "barre"
_BARRE_TOUCHE = "barre_touche"
_SAISIE = "saisie"
_CADRE = "cadre"


class Ecran:
    def __init__(self, fenetre, console_physique: bool = False):
        self.fenetre = fenetre
        self.console_physique = console_physique
        # Branchés par l'application : ce qu'il faut faire d'un choix de F2 ou F3.
        self.changer_langue = lambda code: None
        self.changer_clavier = lambda code: None
        self.clavier_actuel = clavier.ANGLAIS_US
        self._dernier_redessin = time.monotonic()
        self.fenetre.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self._styles = self._preparer_styles()

    def _preparer_styles(self) -> dict[str, int]:
        styles = {
            NORMAL: curses.A_NORMAL,
            FORT: curses.A_BOLD,
            GRISE: curses.A_DIM,
            DETAIL: curses.A_NORMAL,
            OK: curses.A_BOLD,
            ECHEC: curses.A_BOLD,
            AVERTISSEMENT: curses.A_BOLD,
            _BANDE: curses.A_REVERSE | curses.A_BOLD,
            _SELECTION: curses.A_REVERSE | curses.A_BOLD,
            _BARRE: curses.A_REVERSE,
            _BARRE_TOUCHE: curses.A_REVERSE | curses.A_BOLD,
            _SAISIE: curses.A_REVERSE,
            _CADRE: curses.A_BOLD,
        }
        if not curses.has_colors():
            return styles
        curses.start_color()
        try:
            curses.use_default_colors()
            fond = -1
        except curses.error:
            fond = curses.COLOR_BLACK
        # Le gris : la couleur 8 là où elle existe ; sur la console Linux, qui
        # n'a que huit couleurs, le noir en gras donne le même gris.
        if curses.COLORS >= 16:
            gris, gras_gris = 8, 0
        else:
            gris, gras_gris = curses.COLOR_BLACK, curses.A_BOLD
        paires = {
            _BANDE: (curses.COLOR_WHITE, curses.COLOR_GREEN, curses.A_BOLD),
            _SELECTION: (curses.COLOR_WHITE, curses.COLOR_GREEN, curses.A_BOLD),
            OK: (curses.COLOR_GREEN, fond, curses.A_BOLD),
            ECHEC: (curses.COLOR_RED, fond, curses.A_BOLD),
            AVERTISSEMENT: (curses.COLOR_YELLOW, fond, curses.A_BOLD),
            GRISE: (gris, fond, gras_gris),
            DETAIL: (curses.COLOR_CYAN, fond, 0),
            _BARRE: (curses.COLOR_BLACK, curses.COLOR_WHITE, 0),
            _BARRE_TOUCHE: (curses.COLOR_WHITE, curses.COLOR_GREEN, curses.A_BOLD),
            _SAISIE: (curses.COLOR_BLACK, curses.COLOR_WHITE, 0),
            _CADRE: (curses.COLOR_GREEN, fond, curses.A_BOLD),
        }
        for numero, (style, (avant, arriere, attribut)) in enumerate(paires.items(), start=1):
            curses.init_pair(numero, avant, arriere)
            styles[style] = curses.color_pair(numero) | attribut
        return styles

    # ---------------------------------------------------------------- touches ---

    def touche(self, delai: float | None = None) -> str | None:
        """La prochaine touche, traduite ; None si le délai (en secondes) passe.
        F2 et F3 sont traités ici, pour tous les écrans : leur menu s'ouvre, et
        l'appelant reçoit RECONSTRUIRE."""
        self.fenetre.timeout(-1 if delai is None else int(delai * 1000))
        try:
            brute = self.fenetre.get_wch()
        except curses.error:
            return None
        if brute == curses.KEY_F2:
            code = self._menu(t("Langue"), list(langue.LANGUES.items()), langue.actuelle())
            if code is not None:
                self.changer_langue(code)
            return RECONSTRUIRE
        if brute == curses.KEY_F3 and self.console_physique:
            options = [(code, clavier.nom(code)) for code in clavier.DISPOSITIONS]
            code = self._menu(t("Clavier"), options, self.clavier_actuel)
            if code is not None:
                self.changer_clavier(code)
            return RECONSTRUIRE
        if isinstance(brute, int):
            touche = _TOUCHES.get(brute)
            return RECONSTRUIRE if touche == "redim" else touche
        return _CARACTERES.get(brute, brute)

    def _menu(self, titre: str, options: list[tuple[str, str]], actuel: str) -> str | None:
        """Le petit menu de F2 et F3, par-dessus l'écran : le réglage actuel
        marqué d'un point, les flèches et Entrée pour choisir, Échap pour
        refermer sans rien changer."""
        hauteur, largeur = self.fenetre.getmaxyx()
        largeur_menu = min(largeur - 4, max(len(titre) + 6, max(len(n) for _, n in options) + 10))
        hauteur_menu = len(options) + 4
        y0, x0 = max(0, (hauteur - hauteur_menu) // 2), max(0, (largeur - largeur_menu) // 2)
        curseur = next((i for i, (code, _) in enumerate(options) if code == actuel), 0)
        try:
            cadre = curses.newwin(hauteur_menu, largeur_menu, y0, x0)
        except curses.error:
            return None
        cadre.keypad(True)
        while True:
            cadre.erase()
            cadre.attrset(self._styles[_CADRE])
            cadre.box()
            cadre.attrset(0)
            self._ecrire_dans(cadre, 0, 2, f" {titre} ", self._styles[FORT])
            for i, (code, nom) in enumerate(options):
                marque = POINT if code == actuel else " "
                texte = f" {marque} {nom}".ljust(largeur_menu - 4)
                style = self._styles[_SELECTION] if i == curseur else self._styles[NORMAL]
                self._ecrire_dans(cadre, 2 + i, 2, texte, style)
            cadre.refresh()
            try:
                brute = cadre.get_wch()
            except curses.error:
                continue
            if brute in (curses.KEY_UP,):
                curseur = (curseur - 1) % len(options)
            elif brute in (curses.KEY_DOWN,):
                curseur = (curseur + 1) % len(options)
            elif brute in ("\n", "\r", curses.KEY_ENTER):
                return options[curseur][0]
            elif brute in ("\x1b", "\x03", curses.KEY_F2, curses.KEY_F3):
                return None
            elif isinstance(brute, str) and brute.isdigit() and 0 < int(brute) <= len(options):
                return options[int(brute) - 1][0]

    # ----------------------------------------------------------------- dessin ---

    def dessiner(self, page: Page, corps: list[Ligne], choisie: int | None = None,
                 message: str = "", style_message: str = AVERTISSEMENT, haut: int = 0) -> None:
        if self.console_physique and time.monotonic() - self._dernier_redessin > _REDESSIN_COMPLET:
            self.fenetre.clearok(True)
            self._dernier_redessin = time.monotonic()
        self.fenetre.erase()
        hauteur, largeur = self.fenetre.getmaxyx()
        x = max(MARGE, (largeur - LARGEUR_CONTENU) // 2)
        droite = min(largeur, x + LARGEUR_CONTENU)

        self._bande(page, largeur)
        y = 2
        if page.etapes:
            self._fil(page, y, droite, x)
            y += 2
        if page.titre:
            self._ecrire(y, Ligne.de(page.titre, FORT), droite, x=x)
            y += 2
        for ligne in page.entete:
            if y >= hauteur - 3:
                break
            self._ecrire(y, ligne, droite, x=x)
            y += 1
        if page.entete:
            y += 1

        # Le corps défile pour garder la ligne choisie visible.
        place = max(1, hauteur - y - 3)
        debut = haut
        if choisie is not None and choisie >= place:
            debut = choisie - place + 1
        for rang, ligne in enumerate(corps[debut:debut + place]):
            self._ecrire(y + rang, ligne, droite, x=x, surligner=(debut + rang == choisie))

        if message:
            self._ecrire(hauteur - 3, Ligne.de(message, style_message), droite, x=x)
        self._barre(page, hauteur - 1, largeur)
        self.fenetre.refresh()

    def _bande(self, page: Page, largeur: int) -> None:
        """La bande du haut : CloneGator, sa version, et le mode à droite."""
        gauche = f"  CloneGator  {VERSION}"
        droite = f"{page.mode}  " if page.mode else ""
        texte = gauche + " " * max(1, largeur - len(gauche) - len(droite)) + droite
        self._ecrire(0, Ligne.de(texte[:largeur], _BANDE), largeur + 1)

    def _fil(self, page: Page, y: int, largeur: int, x: int) -> None:
        """« Cloner   Source › Cibles › Confirmation » : ce qui est fait en vert,
        l'étape en cours en évidence, ce qui reste en gris."""
        ligne = Ligne([(page.operation, FORT), ("    ", NORMAL)])
        for i, etape in enumerate(page.etapes):
            if i:
                ligne.morceaux.append(("  ›  ", GRISE))
            if i < page.etape:
                ligne.morceaux.append((etape, OK))
            elif i == page.etape:
                ligne.morceaux.append((f"{CURSEUR} {etape}", FORT))
            else:
                ligne.morceaux.append((etape, GRISE))
        self._ecrire(y, ligne, largeur, x=x)

    def _barre(self, page: Page, y: int, largeur: int) -> None:
        """La barre du bas : les touches de l'écran à gauche, F2 et F3 à droite."""
        gauche = [(" ", _BARRE)]
        for touche, action in page.touches:
            gauche += [(f" {touche} ", _BARRE_TOUCHE), (f"{action}   ", _BARRE)]
        droite = [(" F2 ", _BARRE_TOUCHE), (f"{t('Changer de langue')}  ", _BARRE)]
        if self.console_physique:
            droite += [(" F3 ", _BARRE_TOUCHE), (f"{t('Changer de clavier')} ", _BARRE)]
        longueur = sum(len(texte) for texte, _ in gauche + droite)
        # Sur un écran étroit, les touches de l'écran passent avant F2 et F3.
        if longueur > largeur - 1:
            droite = []
            longueur = sum(len(texte) for texte, _ in gauche)
        milieu = [(" " * max(0, largeur - 1 - longueur), _BARRE)]
        self._ecrire(y, Ligne(gauche + milieu + droite), largeur)

    def _ecrire(self, y: int, ligne: Ligne, largeur: int, x: int = 0, surligner: bool = False) -> None:
        """Écrit une ligne à partir de la colonne x, sans dépasser `largeur`."""
        if surligner:
            # La ligne choisie est peinte sur toute la largeur du contenu, en vert.
            texte = ligne.texte()
            self._ecrire_dans(self.fenetre, y, x, texte.ljust(largeur - x)[: largeur - 1 - x],
                              self._styles[_SELECTION])
            return
        for texte, style in ligne.morceaux:
            if x >= largeur - 1:
                break
            self._ecrire_dans(self.fenetre, y, x, texte[: largeur - 1 - x],
                              self._styles.get(style, curses.A_NORMAL))
            x += len(texte)

    @staticmethod
    def _ecrire_dans(fenetre, y: int, x: int, texte: str, attribut: int) -> None:
        try:
            fenetre.addstr(y, x, texte, attribut)
        except curses.error:
            pass  # la dernière case de l'écran refuse l'écriture : sans conséquence

    # ------------------------------------------------------------ interactions ---

    def choisir(self, construire, intervalle: float | None = None):
        """Rend la valeur choisie (ou les valeurs cochées), ou None si
        l'opérateur revient en arrière. `construire()` rend la page et la liste ;
        il est rappelé après F2 et, si `intervalle` est donné, à ce rythme : le
        tableau des baies du mode station se met ainsi à jour tout seul (§9.4)."""
        page, liste = construire()
        dernier = time.monotonic()
        while True:
            self._dessiner_liste(page, liste)
            touche = self.touche(0.5 if intervalle else None)
            perime = intervalle is not None and time.monotonic() - dernier >= intervalle
            if touche == RECONSTRUIRE or (touche is None and perime):
                ancienne = liste
                page, liste = construire()
                liste.reprendre(ancienne)
                dernier = time.monotonic()
                continue
            if touche is None:
                continue
            action = liste.touche(touche)
            if action == VALIDER:
                return liste.choix
            if action == RETOUR:
                return None

    def _dessiner_liste(self, page: Page, liste: Liste) -> None:
        entete = list(page.entete)
        if liste.explication:
            entete.append(Ligne.de(liste.explication, DETAIL))
        self.dessiner(Page(page.titre, entete, page.touches, page.operation, page.etapes,
                           page.etape, page.mode),
                      liste.lignes(), liste.rang_affiche, liste.message)

    def saisir(self, construire) -> dict | None:
        """Un formulaire ; rend les valeurs par clé de champ, ou None."""
        page, formulaire = construire()
        while True:
            entete = list(page.entete)
            if formulaire.explication:
                entete.append(Ligne.de(formulaire.explication, DETAIL))
            self.dessiner(Page(page.titre, entete, page.touches, page.operation, page.etapes,
                               page.etape, page.mode),
                          formulaire.lignes(), None, formulaire.message)
            touche = self.touche()
            if touche == RECONSTRUIRE:
                ancien = formulaire
                page, formulaire = construire()
                formulaire.reprendre(ancien)
                continue
            if touche is None:
                continue
            action = formulaire.touche(touche)
            if action == VALIDER:
                return formulaire.valeurs
            if action == RETOUR:
                return None

    def confirmer(self, construire, touches: dict[str, str] | None = None):
        """L'écran de confirmation (§9.5). `construire()` rend la page et les
        boutons, le premier — « Annuler » — choisi par défaut. Rend la clé du
        bouton validé, celle d'une touche spéciale, ou None."""
        touches = touches or {}
        curseur = 0
        while True:
            page, boutons = construire()
            liste = Liste("", [Element(libelle, cle) for cle, libelle in boutons])
            liste.curseur = min(curseur, len(boutons) - 1)
            while True:
                self.dessiner(page, liste.lignes(), liste.curseur)
                touche = self.touche()
                if touche == RECONSTRUIRE:
                    curseur = liste.curseur
                    break
                if touche is None:
                    continue
                if touche.lower() in touches:
                    return touches[touche.lower()]
                action = liste.touche(touche)
                if action == VALIDER:
                    return liste.choix
                if action == RETOUR:
                    return None

    def afficher(self, construire) -> None:
        """Un texte à lire, qu'on fait défiler ; Entrée ou Échap pour revenir.
        Rien ne s'efface tout seul (§9.7)."""
        haut = 0
        page, lignes = construire()
        while True:
            hauteur, _ = self.fenetre.getmaxyx()
            self.dessiner(page, lignes, haut=haut)
            touche = self.touche()
            place = max(1, hauteur - len(page.entete) - 8)
            if touche == RECONSTRUIRE:
                page, lignes = construire()
            elif touche == "bas" and haut + place < len(lignes):
                haut += 1
            elif touche == "haut" and haut > 0:
                haut -= 1
            elif touche in ("entree", "echap"):
                return

    def suivre(self, construire, en_cours, interrompre, confirmer_arret) -> None:
        """L'écran de progression (§9.6), redessiné deux fois par seconde tant
        que l'opération tourne. Échap propose de l'interrompre :
        `confirmer_arret()` construit cette question."""
        demande = False
        while en_cours():
            page, lignes = construire()
            self.dessiner(page, lignes,
                          message=t("Interruption demandée… arrêt en cours.") if demande else "")
            touche = self.touche(0.5)
            if touche == "echap" and not demande:
                if self.confirmer(confirmer_arret) == "interrompre":
                    interrompre()
                    demande = True
        page, lignes = construire()
        self.dessiner(page, lignes)
