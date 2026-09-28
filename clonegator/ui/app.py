"""L'application : l'accueil, les trois opérations, le mode station, les
journaux (§9 de l'analyse).

Chaque opération suit les étapes décidées avec Kevin : choisir les disques,
confirmer — « Annuler » par défaut —, suivre la progression, lire le rapport.
Échap revient à l'étape précédente. Les disques qu'on ne peut pas choisir restent
visibles, grisés, avec leur motif ; ce qu'un disque peut devenir se décide dans
`devices`, jamais ici.

Chaque écran est décrit par une fonction qui le construit, dans la langue du
moment : `ecran` la rappelle après F2, et l'écran change de langue sans perdre
ce que l'opérateur y avait fait (§9.8).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time

from .. import clavier, config, demarrage, devices, filesystems, health, image, journal, langue, layout
from .. import storage, sysexec, texte
from ..engine import backup, clone, fanout, sources
from ..journal import Journal
from ..langue import t
from .model import (
    AVERTISSEMENT, DETAIL, ECHEC, FORT, GRISE, NORMAL, OK,
    Champ, Element, Formulaire, Ligne, Liste, Page, barre,
)

_log = logging.getLogger("clonegator.ui")

# Débits nominaux pour les estimations de l'écran de confirmation (§9.5) :
# lecture d'un disque source courant, relecture d'une sauvegarde compressée.
DEBIT_LECTURE = 150e6
DEBIT_SAUVEGARDE = {False: 100e6, True: 55e6}  # disque USB, partage réseau

# Largeur de la colonne des libellés dans les écrans de confirmation et de rapport.
COLONNE = 14


# ----------------------------------------------------------- barres du bas ---
# Construites à la demande : elles suivent la langue.

def _touches_liste():
    return [("↑↓", t("Choisir")), (t("Entrée"), t("Valider")), (t("Échap"), t("Retour"))]


def _touches_cocher():
    return [("↑↓", t("Se déplacer")), (t("Espace"), t("Cocher")), (t("Entrée"), t("Cocher ou continuer")),
            (t("Échap"), t("Retour"))]


def _touches_formulaire():
    return [(t("Entrée"), t("Champ suivant, puis valider")), (t("Échap"), t("Retour"))]


def _touches_lire():
    return [("↑↓", t("Faire défiler")), (t("Entrée"), t("Revenir"))]


def _touches_confirmer(copie_integrale: bool = False):
    touches = [("↑↓", t("Choisir")), (t("Entrée"), t("Valider"))]
    if copie_integrale:
        touches.append(("I", t("Copie intégrale")))
    return touches + [(t("Échap"), t("Annuler"))]


# ------------------------------------------------------- fils des étapes ---

def _etapes_cloner():
    return t("Cloner"), [t("Source"), t("Cibles"), t("Confirmation")]


def _etapes_sauvegarder():
    return t("Sauvegarder"), [t("Disque"), t("Emplacement"), t("Nom"), t("Confirmation")]


def _etapes_restaurer():
    return t("Restaurer"), [t("Emplacement"), t("Sauvegarde"), t("Cibles"), t("Confirmation")]


def _etapes_station():
    etapes = [t("Source"), t("Cibles")]
    if not demarrage.en_live():
        etapes.append(t("Démarrage"))
    return t("Mode station"), etapes


class ArretDemande(Exception):
    """Le système demande à CloneGator de s'arrêter : extinction de la
    machine, terminal perdu (SIGTERM, SIGHUP)."""


class Application:
    def __init__(self, ecran):
        self.ecran = ecran
        self.reglages = config.lire()
        self.arret_demande = False
        langue.choisir(self.reglages.langue)
        ecran.changer_langue = self.changer_langue
        ecran.changer_clavier = self.changer_clavier
        ecran.clavier_actuel = self.reglages.clavier

    # ----------------------------------------------------- langue et clavier ---

    def changer_langue(self, code: str) -> None:
        langue.choisir(code)
        self.reglages.langue = code
        self._memoriser()

    def changer_clavier(self, code: str) -> None:
        if clavier.appliquer(code):
            self.reglages.clavier = code
            self.ecran.clavier_actuel = code
            self._memoriser()

    def _memoriser(self) -> None:
        try:
            config.ecrire(self.reglages)
        except OSError as erreur:
            _log.warning("réglages non enregistrés : %s", erreur)

    # -------------------------------------------------------------- accueil ---

    def lancer(self) -> None:
        if self.ecran.console_physique:
            # Le clavier mémorisé, ou l'anglais (États-Unis) par défaut (§9.8).
            clavier.appliquer(self.reglages.clavier)
        try:
            if self.reglages.mode == config.MODE_STATION and self.reglages.station:
                if not self.station():
                    return
            self.accueil()
        except ArretDemande:
            pass  # une opération éventuelle a déjà été interrompue et rapportée

    def accueil(self) -> None:
        def construire():
            liste = Liste("", [
                Element(t("Sauvegarder"), "sauvegarder", detail=t("Enregistrer un disque dans une sauvegarde")),
                Element(t("Restaurer"), "restaurer", detail=t("Écrire une sauvegarde sur un ou plusieurs disques")),
                Element(t("Cloner"), "cloner", detail=t("Copier un disque vers un ou plusieurs disques")),
                Element(t("Mode station"), "station",
                        detail=t("Le même réglage à chaque fois, pour une machine à baies")),
                Element(t("Journaux"), "journaux", detail=t("Les dernières opérations")),
                Element(t("Quitter"), "quitter"),
            ])
            return self._page(t("Que voulez-vous faire ?"), touches=_touches_liste()), liste

        while True:
            choix = self.ecran.choisir(construire)
            if choix == "quitter":
                if not demarrage.en_live() or self.quitter_live():
                    return
                continue
            if choix == "sauvegarder":
                self.sauvegarder()
            elif choix == "restaurer":
                self.restaurer()
            elif choix == "cloner":
                self.cloner()
            elif choix == "station":
                if self.configurer_station() and not self.station():
                    return
            elif choix == "journaux":
                self.journaux()

    def quitter_live(self) -> bool:
        """En live, quitter CloneGator laisserait un écran vide : on éteint, on
        redémarre, ou on ouvre une console. Rend False pour revenir à l'accueil."""
        def construire():
            liste = Liste("", [
                Element(t("Éteindre"), "eteindre"),
                Element(t("Redémarrer"), "redemarrer"),
                Element(t("Ouvrir une console"), "console",
                        detail=t("Un shell root, pour dépanner ; « clonegator » pour revenir")),
                Element(t("Revenir à l'accueil"), None),
            ])
            return self._page(t("Quitter CloneGator ?"), touches=_touches_liste()), liste

        choix = self.ecran.choisir(construire)
        if choix in ("eteindre", "redemarrer"):
            sysexec.executer(["systemctl", "--no-block", "poweroff" if choix == "eteindre" else "reboot"])
        return choix is not None

    # ------------------------------------------------------------ opérations ---

    def cloner(self, source: devices.Disque | None = None, cibles=None) -> None:
        """§9.3 : source → cibles → confirmation → progression → rapport. En mode
        station, source et cibles sont imposées : on arrive à la confirmation."""
        impose = source is not None
        etape = 2 if impose else 0
        while True:
            if etape == 0:
                source = self._choisir_source(_etapes_cloner, t("Quel disque voulez-vous copier ?"))
                if source is None:
                    return
                etape = 1
            elif etape == 1:
                cibles = self._choisir_cibles(_etapes_cloner, 1, source=source, precedentes=cibles)
                etape = 2 if cibles else 0
            else:
                plan = _plan_disque(source)
                decision = self._confirmer_clonage(source, cibles, plan)
                while decision == "brut":
                    plan = _plan_disque(source, brut=not plan.brut)
                    decision = self._confirmer_clonage(source, cibles, plan)
                if decision != "lancer":
                    if impose:
                        return
                    etape = 1
                    continue
                self._executer_clonage(sources.SourceDisque(source, brut=plan.brut), cibles,
                                       "clonage", plan.volume)
                return

    def sauvegarder(self, source: devices.Disque | None = None) -> None:
        """§9.3 : disque → où sont les sauvegardes → nom → confirmation → …"""
        impose = source is not None
        etape = 1 if impose else 0
        stockage = None
        nom = None
        try:
            while True:
                if etape == 0:
                    source = self._choisir_source(_etapes_sauvegarder, t("Quel disque voulez-vous sauvegarder ?"))
                    if source is None:
                        return
                    etape = 1
                elif etape == 1:
                    if stockage is not None:
                        storage.fermer(stockage)
                    stockage = self._choisir_stockage(_etapes_sauvegarder, 1,
                                                      t("Où voulez-vous ranger la sauvegarde ?"))
                    if stockage is None:
                        if impose:
                            return
                        etape = 0
                        continue
                    etape = 2
                elif etape == 2:
                    nom = self._saisir_nom(source, nom)
                    etape = 1 if nom is None else 3
                else:
                    plan = _plan_disque(source)
                    decision = self._confirmer_sauvegarde(source, stockage, nom, plan)
                    while decision == "brut":
                        plan = _plan_disque(source, brut=not plan.brut)
                        decision = self._confirmer_sauvegarde(source, stockage, nom, plan)
                    if decision != "lancer":
                        etape = 2
                        continue
                    self._executer_sauvegarde(source, stockage, nom, plan)
                    return
        finally:
            if stockage is not None:
                storage.fermer(stockage)

    def restaurer(self, cibles_imposees=None) -> None:
        """§9.3 : où sont les sauvegardes → la sauvegarde → cibles → confirmation → …"""
        stockage = None
        try:
            stockage = self._choisir_stockage(_etapes_restaurer, 0, t("Où sont les sauvegardes ?"))
            if stockage is None:
                return
            while True:
                img = self._choisir_sauvegarde(stockage)
                if img is None:
                    return
                if cibles_imposees is not None:
                    cibles = self._cibles_station_pour(img.taille_requise, int(img.meta.get("secteur", 512)),
                                                       cibles_imposees)
                else:
                    cibles = self._choisir_cibles(_etapes_restaurer, 2, image=img)
                if not cibles:
                    continue
                if self._confirmer_restauration(img, stockage, cibles) != "lancer":
                    continue
                # Le volume décompressé, inscrit par la sauvegarde ; une image qui
                # ne l'a pas donne une progression sans pourcentage.
                volume = sum(int(p.get("volume", 0)) for p in img.partitions)
                self._executer_clonage(sources.SourceImage(img), cibles, "restauration", volume,
                                       reseau=stockage.reseau)
                return
        finally:
            if stockage is not None:
                storage.fermer(stockage)

    # --------------------------------------------------------- mode station ---

    def configurer_station(self) -> bool:
        """L'assistant du §3.3, pré-rempli avec le dernier réglage. Rend True si
        le mode station est activé."""
        precedent = self.reglages.station
        emplacements = _emplacements_internes()
        presents = {d.emplacement.cle: d for d in devices.inventaire() if d.emplacement}

        def element(e: devices.Emplacement) -> Element:
            disque = presents.get(e.cle)
            detail = (f"{disque.nom_noyau:<8} {disque.description[:22]:<22} {texte.taille(disque.taille):>9}"
                      if disque else t("(vide)"))
            return Element(e.nom, e.cle, detail=detail)

        def page(etape: int, titre: str, touches):
            operation, etapes = _etapes_station()
            return self._page(titre, touches=touches, operation=operation, etapes=etapes, etape=etape)

        etape = 0
        source = precedent.source if precedent else None
        cibles = list(precedent.cibles) if precedent else []
        while True:
            if etape == 0:
                def construire():
                    liste = Liste("", [element(e) for e in emplacements])
                    if source:
                        liste.placer(source)
                    return page(0, t("Sélectionnez l'emplacement source."), _touches_liste()), liste
                choix = self.ecran.choisir(construire)
                if choix is None:
                    return False
                source = choix
                etape = 1
            elif etape == 1:
                autres = [e for e in emplacements if e.cle != source]

                def construire():
                    liste = Liste("", [element(e) for e in autres], multiple=True,
                                  valider=t("Continuer avec {n} emplacement(s)"))
                    liste.cocher(cibles or [e.cle for e in autres])
                    p = page(1, t("Sélectionnez les emplacements cibles."), _touches_cocher())
                    p.entete = [Ligne.de(t("Leur contenu sera effacé à chaque clonage."), ECHEC)]
                    return p, liste
                choix = self.ecran.choisir(construire)
                if choix is None:
                    etape = 0
                    continue
                cibles = choix
                etape = 2
                if demarrage.en_live():
                    # Le live démarre déjà sur CloneGator, et n'enregistre rien.
                    self.reglages.station = config.ReglageStation(source, cibles, False)
                    self.reglages.mode = config.MODE_STATION
                    self._memoriser()
                    return True
            else:
                def construire():
                    liste = Liste("", [
                        Element(t("Oui"), True, detail=t("La machine démarre directement sur le mode station")),
                        Element(t("Non"), False, detail=t("On lance CloneGator soi-même")),
                    ])
                    liste.placer(bool(precedent and precedent.lancement_auto))
                    return page(2, t("Voulez-vous que CloneGator démarre automatiquement en mode station "
                                     "au démarrage de cet ordinateur ?"), _touches_liste()), liste
                choix = self.ecran.choisir(construire)
                if choix is None:
                    etape = 1
                    continue
                self.reglages.station = config.ReglageStation(source, cibles, bool(choix))
                self.reglages.mode = config.MODE_STATION
                self._memoriser()
                motif = demarrage.activer() if choix else demarrage.desactiver()
                if motif:
                    self._message(t("Lancement automatique"), [
                        Ligne.de(t("Le mode station est activé, mais pas son lancement automatique :"),
                                 AVERTISSEMENT),
                        Ligne.de(motif)])
                return True

    def station(self) -> bool:
        """L'accueil du mode station (§9.4). Rend False pour quitter CloneGator,
        True pour revenir à l'accueil du mode libre."""
        while True:
            choix = self.ecran.choisir(self._accueil_station, intervalle=2.0)
            reglage = self.reglages.station
            if choix is None:
                continue
            source, cibles = _disques_station(reglage)
            if choix == "cloner":
                if source is None:
                    self._message(t("Cloner"), [Ligne.de(t("Aucun disque dans l'emplacement source."),
                                                         AVERTISSEMENT)])
                    continue
                cibles_ok = self._cibles_station_pour(_taille_requise(source), source.secteur_logique, cibles,
                                                      source=source)
                if not cibles_ok:
                    self._message(t("Cloner"), [Ligne.de(t("Aucune cible prête."), AVERTISSEMENT)])
                    continue
                self.cloner(source, cibles_ok)
            elif choix == "restaurer":
                self.restaurer(cibles_imposees=cibles)
            elif choix == "sauvegarder":
                if source is None:
                    self._message(t("Sauvegarder"), [Ligne.de(t("Aucun disque dans l'emplacement source."),
                                                              AVERTISSEMENT)])
                    continue
                self.sauvegarder(source)
            elif choix == "quitter":
                self.reglages.mode = config.MODE_LIBRE
                self._memoriser()
                motif = demarrage.desactiver()
                if motif:
                    self._message(t("Lancement automatique"), [Ligne.de(motif, AVERTISSEMENT)])
                return True

    def _accueil_station(self):
        """Le tableau des baies : chaque emplacement du réglage, son disque et
        son état, puis les opérations."""
        reglage = self.reglages.station
        source, cibles = _disques_station(reglage)
        noms = {e.cle: e.nom for e in _emplacements_internes()}
        requis = _taille_requise(source) if source else None

        def rangee(nom_emplacement, role, disque, etat, style):
            if disque is None:
                return Ligne([(f"{nom_emplacement:<7} {'':<8} ", NORMAL), (f"{role:<12}", FORT),
                              (t("(vide)"), GRISE)])
            return Ligne([
                (f"{nom_emplacement:<7} {disque.nom_noyau:<8} ", NORMAL), (f"{role:<12}", FORT),
                (f"{disque.description[:20]:<20} {texte.taille(disque.taille):>9}   ", NORMAL),
                (etat, style)])

        lignes = []
        nom_source = noms.get(reglage.source, "?")
        if source is not None:
            refus = devices.refus_comme_source(source)
            lignes.append(rangee(nom_source, t("SOURCE"), source,
                                 refus or texte.contenu(source), AVERTISSEMENT if refus else DETAIL))
        else:
            lignes.append(rangee(nom_source, t("SOURCE"), None, "", NORMAL))
        for cle, disque in cibles:
            etat, style = t("prêt"), OK
            if disque is not None:
                refus = devices.refus_comme_cible(disque)
                sante = health.etat(disque)
                if refus:
                    etat, style = refus, AVERTISSEMENT
                elif requis is not None and disque.taille < requis:
                    etat, style = t("trop petit ({requis} requis)", requis=texte.taille(requis)), AVERTISSEMENT
                elif sante.niveau == health.USURE:
                    etat, style = t("prêt, {sante}", sante=health.resume(sante)), AVERTISSEMENT
            lignes.append(rangee(noms.get(cle, "?"), t("CIBLE"), disque, etat, style))

        for candidat in storage.candidats():
            libre = (t("{taille} libres", taille=texte.taille(candidat.libre)) if candidat.libre is not None
                     else t("sera monté"))
            lignes.append(Ligne([
                (f"{candidat.disque.emplacement.nom if candidat.disque.emplacement else '':<7} "
                 f"{candidat.disque.nom_noyau:<8} ", DETAIL), (f"{t('SAUVEGARDES'):<12}", DETAIL),
                (f"{candidat.disque.description[:20]:<20} {'':>9}   {libre}", DETAIL)]))

        liste = Liste("", [
            Element(t("Cloner la source vers les cibles"), "cloner"),
            Element(t("Restaurer une sauvegarde vers les cibles"), "restaurer"),
            Element(t("Sauvegarder la source"), "sauvegarder"),
            Element(t("Quitter le mode station"), "quitter"),
        ])
        page = self._page(t("Changez les disques, puis choisissez une opération."), lignes, _touches_liste())
        return page, liste

    def _cibles_station_pour(self, requis: int, secteur: int, cibles, source=None) -> list[devices.Disque]:
        """Les cibles du réglage prêtes pour cette source : présentes, admises par
        devices, assez grandes."""
        retenues = []
        for _, disque in cibles:
            if disque is None or (source is not None and disque.chemin == source.chemin):
                continue
            if devices.refus_comme_cible(disque) or disque.taille < requis:
                continue
            if disque.secteur_logique != secteur:
                continue
            retenues.append(disque)
        return retenues

    # ------------------------------------------------------------- journaux ---

    def journaux(self) -> None:
        while True:
            entrees = journal.lister()
            if not entrees:
                self._message(t("Journaux"), [Ligne.de(t("Aucune opération enregistrée."))])
                return

            def construire():
                liste = Liste("", [
                    Element(f"{e.date}  {_nom_operation(e.operation):<14}", e, detail=_resume_rapport(e.rapport))
                    for e in entrees
                ])
                return self._page(t("Quelle opération voulez-vous relire ?"), touches=_touches_liste()), liste

            choix = self.ecran.choisir(construire)
            if choix is None:
                return

            def construire_rapport(entree=choix):
                rapport = entree.rapport
                lignes = [Ligne.de(l) for l in rapport.splitlines()] if rapport else [
                    Ligne.de(t("Pas de rapport pour cette opération."), GRISE),
                    Ligne.de(""), Ligne.de(t("Journal : {dossier}", dossier=entree.dossier), DETAIL)]
                titre = f"{_nom_operation(entree.operation)} — {entree.date}"
                return self._page(titre, touches=_touches_lire()), lignes

            self.ecran.afficher(construire_rapport)

    # --------------------------------------------------------------- étapes ---

    def _choisir_source(self, etapes, titre: str) -> devices.Disque | None:
        disques = devices.inventaire()
        if not disques:
            self._message(titre, [Ligne.de(t("Aucun disque détecté."), AVERTISSEMENT)])
            return None

        def construire():
            elements = []
            for disque in disques:
                refus = devices.refus_comme_source(disque)
                elements.append(Element(_libelle_disque(disque), disque, actif=not refus, motif=refus,
                                        detail=texte.contenu(disque)))
            operation, noms = etapes()
            return self._page(titre, touches=_touches_liste(), operation=operation, etapes=noms,
                              etape=0), Liste("", elements)

        return self.ecran.choisir(construire)

    def _choisir_cibles(self, etapes, etape: int, source: devices.Disque | None = None,
                        image=None, precedentes=None) -> list[devices.Disque] | None:
        if source is not None:
            requis, secteur = _taille_requise(source), source.secteur_logique
        else:
            requis, secteur = image.taille_requise, int(image.meta.get("secteur", 512))
        disques = [d for d in devices.inventaire() if source is None or d.chemin != source.chemin]

        def construire():
            elements = []
            for disque in disques:
                motif = devices.refus_comme_cible(disque)
                if not motif and disque.taille < requis:
                    motif = t("trop petit : {requis} requis", requis=texte.taille(requis))
                if not motif and disque.secteur_logique != secteur:
                    motif = t("secteurs de {cible} octets, la source en a de {source}",
                              cible=disque.secteur_logique, source=secteur)
                smart = motif == devices.refus_smart()
                elements.append(Element(_libelle_disque(disque), disque,
                                        actif=not motif, motif=motif, detail=texte.contenu(disque),
                                        forcable=smart,
                                        motif_force=t("SMART défaillant, choisi quand même") if smart else ""))
            liste = Liste("", elements, multiple=True, valider=t("Continuer avec {n} disque(s)"))
            if precedentes:
                # Revenir de la confirmation ne doit pas faire tout recocher.
                chemins = {d.chemin for d in precedentes}
                liste.cocher([e.valeur for e in elements if e.valeur.chemin in chemins])
            touches = _touches_cocher()
            if any(e.forcable for e in elements):
                touches.insert(-1, ("F", t("Forcer un disque SMART défaillant")))
            operation, noms = etapes()
            page = self._page(t("Vers quels disques ?"), [
                Ligne.de(t("Tout le contenu des disques cochés sera effacé."), ECHEC)],
                touches, operation=operation, etapes=noms, etape=etape)
            return page, liste

        return self.ecran.choisir(construire)

    def _choisir_stockage(self, etapes, etape: int, titre: str) -> storage.Stockage | None:
        """§7.4 : un disque USB ou le partage réseau ; l'étape apparaît toujours."""
        while True:
            candidats = storage.candidats()

            def construire():
                elements = []
                for candidat in candidats:
                    libre = (t("{taille} libres", taille=texte.taille(candidat.libre))
                             if candidat.libre is not None else t("sera monté"))
                    elements.append(Element(candidat.nom, candidat, actif=candidat.utilisable,
                                            motif=candidat.refus, detail=libre))
                connexion = self.reglages.reseau
                libelle = (t("Partage réseau {unc}", unc=connexion.unc) if connexion.renseignee
                           else t("Partage réseau Windows…"))
                elements.append(Element(libelle, "reseau", detail=t("mot de passe demandé")))
                operation, noms = etapes()
                return self._page(titre, touches=_touches_liste(), operation=operation, etapes=noms,
                                  etape=etape), Liste("", elements)

            choix = self.ecran.choisir(construire)
            if choix is None:
                return None
            if choix == "reseau":
                ouvert = self._ouvrir_partage(etapes, etape)
                if ouvert is not None:
                    return ouvert
                continue
            try:
                return storage.ouvrir(choix)
            except storage.ErreurStockage as erreur:
                self._message(titre, [Ligne.de(f"{choix.nom} : {erreur}", AVERTISSEMENT)])

    def _ouvrir_partage(self, etapes, etape: int) -> storage.Stockage | None:
        connexion = self.reglages.reseau
        saisi = {}

        def construire():
            formulaire = Formulaire("", [
                Champ("hote", t("Hôte"), connexion.hote),
                Champ("partage", t("Partage"), connexion.partage),
                Champ("utilisateur", t("Utilisateur"), connexion.utilisateur),
                Champ("mot_de_passe", t("Mot de passe"), "", masque=True),
            ], explication=t("Partage Windows : \\\\hôte\\partage. Le mot de passe n'est jamais enregistré."))
            formulaire.curseur = 3 if connexion.renseignee else 0
            formulaire.message = saisi.get("message", "")
            operation, noms = etapes()
            return self._page(t("À quel partage réseau voulez-vous vous connecter ?"),
                              touches=_touches_formulaire(), operation=operation, etapes=noms,
                              etape=etape), formulaire

        while True:
            valeurs = self.ecran.saisir(construire)
            if valeurs is None:
                return None
            essai = config.ConnexionReseau(valeurs["hote"].strip().strip("\\/"),
                                           valeurs["partage"].strip().strip("\\/"),
                                           valeurs["utilisateur"].strip())
            connexion = essai
            self.ecran.dessiner(self._page(t("Connexion à {unc}…", unc=essai.unc)), [])
            try:
                ouvert = storage.ouvrir(storage.partage(essai), valeurs["mot_de_passe"])
            except storage.ErreurStockage as erreur:
                saisi["message"] = str(erreur)
                continue
            finally:
                valeurs["mot_de_passe"] = ""
            # Hôte, partage et utilisateur sont mémorisés ; le mot de passe, jamais.
            self.reglages.reseau = essai
            self._memoriser()
            return ouvert

    def _choisir_sauvegarde(self, stockage: storage.Stockage):
        sauvegardes = list(reversed(image.lister(stockage.racine)))  # la plus récente en haut
        if not sauvegardes:
            self._message(t("Restaurer"), [Ligne.de(t("Aucune sauvegarde sur {stockage}.", stockage=stockage.nom),
                                                     AVERTISSEMENT)])
            return None

        def construire():
            elements = []
            for img in sauvegardes:
                detail = t("{modele}, {taille} — sauvegarde de {poids}",
                           modele=img.origine.get("modele", "?"),
                           taille=texte.taille(int(img.origine.get("taille", 0))),
                           poids=texte.taille(img.taille_sur_disque))
                if img.mode == image.MODE_BRUT:
                    detail += t("  (copie intégrale)")
                elements.append(Element(f"{img.etiquette:<24} {img.meta.get('date', '?'):<17}", img, detail=detail))
            operation, noms = _etapes_restaurer()
            return self._page(t("Quelle sauvegarde voulez-vous restaurer ?"), touches=_touches_liste(),
                              operation=operation, etapes=noms, etape=1), Liste("", elements)

        return self.ecran.choisir(construire)

    def _saisir_nom(self, source: devices.Disque, precedent: str | None = None) -> str | None:
        propose = precedent or "".join(
            c if c.isalnum() or c in "-_" else "-" for c in source.description).strip("-")
        saisi = {}

        def construire():
            formulaire = Formulaire("", [Champ("nom", t("Nom"), propose or "sauvegarde")],
                                    explication=t("Pour la reconnaître dans la liste de restauration, "
                                                  "par exemple Win11-labo-info."))
            formulaire.message = saisi.get("message", "")
            operation, noms = _etapes_sauvegarder()
            return self._page(t("Quel nom voulez-vous donner à la sauvegarde ?"), touches=_touches_formulaire(),
                              operation=operation, etapes=noms, etape=2), formulaire

        while True:
            valeurs = self.ecran.saisir(construire)
            if valeurs is None:
                return None
            nom = valeurs["nom"].strip()
            if nom:
                return nom
            propose = ""
            saisi["message"] = t("Donnez un nom à la sauvegarde.")

    # --------------------------------------------------------- confirmations ---

    def _confirmer_clonage(self, source, cibles, plan) -> str | None:
        def construire():
            lignes = [_ligne_disque(t("Source"), source), Ligne.de(""),
                      Ligne.de(t("Effacés — tout leur contenu sera perdu :"), ECHEC)]
            lignes += [_ligne_disque("", c) for c in cibles]
            lignes += [Ligne.de("")] + plan.lignes(DEBIT_LECTURE)
            operation, noms = _etapes_cloner()
            page = self._page(t("Tout est prêt. Vérifiez avant de lancer."), lignes,
                              _touches_confirmer(copie_integrale=True),
                              operation=operation, etapes=noms, etape=2)
            return page, [("annuler", t("Annuler")),
                          ("lancer", t("Lancer le clonage vers {n} disque(s)", n=len(cibles)))]
        return self.ecran.confirmer(construire, {"i": "brut"})

    def _confirmer_sauvegarde(self, source, stockage, nom, plan) -> str | None:
        def construire():
            lignes = [_ligne_disque(t("Source"), source),
                      _ligne_champ(t("Vers"), t("{stockage}, {taille} libres", stockage=stockage.nom,
                                                taille=texte.taille(stockage.libre))),
                      _ligne_champ(t("Nom"), nom), Ligne.de("")]
            lignes += plan.lignes(DEBIT_LECTURE)
            if stockage.libre is not None and stockage.libre < plan.volume:
                lignes.append(Ligne.de(t("Espace libre inférieur au volume à lire : la compression le "
                                         "réduit souvent assez, sans garantie."), AVERTISSEMENT))
            operation, noms = _etapes_sauvegarder()
            page = self._page(t("Tout est prêt. Vérifiez avant de lancer."), lignes,
                              _touches_confirmer(copie_integrale=True),
                              operation=operation, etapes=noms, etape=3)
            return page, [("annuler", t("Annuler")), ("lancer", t("Lancer la sauvegarde"))]
        return self.ecran.confirmer(construire, {"i": "brut"})

    def _confirmer_restauration(self, img, stockage, cibles) -> str | None:
        debit = DEBIT_SAUVEGARDE[stockage.reseau]
        volume = img.taille_sur_disque

        def construire():
            lignes = [_ligne_champ(t("Sauvegarde"), t("{nom}, du {date}, d'un {modele}", nom=img.etiquette,
                                                      date=img.meta.get("date", "?"),
                                                      modele=img.origine.get("modele", "?"))),
                      _ligne_champ("", t("sur {stockage}", stockage=stockage.nom)), Ligne.de(""),
                      Ligne.de(t("Effacés — tout leur contenu sera perdu :"), ECHEC)]
            lignes += [_ligne_disque("", c) for c in cibles]
            lignes += [Ligne.de(""),
                       Ligne.de(t("La sauvegarde ({taille}) est d'abord vérifiée, puis copiée : environ {duree} en tout.",
                                  taille=texte.taille(volume), duree=texte.duree(2 * volume / debit)))]
            operation, noms = _etapes_restaurer()
            page = self._page(t("Tout est prêt. Vérifiez avant de lancer."), lignes, _touches_confirmer(),
                              operation=operation, etapes=noms, etape=3)
            return page, [("annuler", t("Annuler")),
                          ("lancer", t("Lancer la restauration vers {n} disque(s)", n=len(cibles)))]
        return self.ecran.confirmer(construire)

    # -------------------------------------------------------------- exécution ---

    def _executer_clonage(self, source, cibles, nom_operation: str, volume: int, reseau: bool = False) -> None:
        # Une cible choisie malgré un SMART défaillant l'a été délibérément (touche F).
        forcees = frozenset(c.chemin for c in cibles if health.etat(c).niveau == health.DEFAILLANT)
        with Journal(nom_operation) as j:
            operation = clone.Clonage(source, cibles, j, forcer_smart=forcees)
            suivi = _Suivi(operation, volume)
            titre = lambda: t("Clonage") if nom_operation == "clonage" else t("Restauration")
            self._executer(operation, lambda: suivi.page(self, titre()))
            j.ecrire_rapport("\n".join(l.texte() for l in _rapport_clonage(operation, j, titre())))
        if self.arret_demande:
            raise ArretDemande()
        self.ecran.afficher(lambda: (self._page(t("{operation} — rapport", operation=titre()),
                                                touches=[(t("Entrée"), t("Revenir"))]),
                                     _rapport_clonage(operation, j, titre())))

    def _executer_sauvegarde(self, source, stockage, nom, plan) -> None:
        with Journal("sauvegarde") as j:
            operation = backup.Sauvegarde(source, stockage.racine, nom, j, brut=plan.brut)
            suivi = _Suivi(operation, plan.volume)
            self._executer(operation, lambda: suivi.page(self, t("Sauvegarde")))
            j.ecrire_rapport("\n".join(l.texte() for l in _rapport_sauvegarde(operation, j, stockage)))
        if self.arret_demande:
            raise ArretDemande()
        self.ecran.afficher(lambda: (self._page(t("Sauvegarde — rapport"), touches=[(t("Entrée"), t("Revenir"))]),
                                     _rapport_sauvegarde(operation, j, stockage)))

    def _executer(self, operation, construire) -> None:
        erreurs = []

        def tourner():
            try:
                operation.executer()
            except BaseException as erreur:  # déjà consignée par l'opération
                erreurs.append(erreur)

        def confirmer_arret():
            page = self._page(t("Interrompre l'opération ?"), [
                Ligne.de(t("Les disques en cours d'écriture seront déclarés invalides."), ECHEC)],
                [("↑↓", t("Choisir")), (t("Entrée"), t("Valider"))])
            return page, [("continuer", t("Continuer l'opération")), ("interrompre", t("Interrompre"))]

        fil = threading.Thread(target=tourner, name="operation")
        fil.start()
        try:
            self.ecran.suivre(construire, fil.is_alive, operation.arreter, confirmer_arret)
        except ArretDemande:
            # §13 : une coupure arrête proprement les écritures ; les cibles
            # sont déclarées interrompues, et le rapport est quand même écrit.
            self.arret_demande = True
            operation.arreter()
        fil.join()

    # ---------------------------------------------------------------- outils ---

    def _page(self, titre: str, entete=None, touches=None, operation: str = "", etapes=None,
              etape: int = -1) -> Page:
        mode = t("Mode station") if self.reglages.mode == config.MODE_STATION else t("Mode libre")
        return Page(titre, entete or [], touches or [], operation, etapes or [], etape, mode)

    def _message(self, titre: str, lignes: list[Ligne]) -> None:
        self.ecran.afficher(lambda: (self._page(titre, touches=[(t("Entrée"), t("Revenir"))]), lignes))


# ---------------------------------------------------------------- calculs ---

class _Plan:
    """Ce que copiera une source disque, pour l'écran de confirmation (§9.5)."""

    def __init__(self, disque: devices.Disque, brut: bool):
        self.disque = disque
        self.brut = brut
        self.volume = 0
        self._notes: list[tuple[int, str, int]] = []  # numéro, raison, volume
        if brut:
            self.volume = disque.taille
            return
        partitions = {p.numero: p for p in disque.partitions}
        table = layout.lire(disque.chemin)
        for entree in table.entrees:
            partition = partitions.get(entree.numero)
            if partition is None:
                continue
            choix = filesystems.choisir(partition, entree.etendue)
            volume = filesystems.volume_a_copier(partition, choix)
            self.volume += volume
            if choix.avertissement:
                self._notes.append((entree.numero, choix.raison, volume))

    def lignes(self, debit: float) -> list[Ligne]:
        if self.brut:
            return [_ligne_champ(t("À copier"), t("tout le disque, secteur par secteur : {taille}, environ {duree}. "
                                                  "C'est lent.", taille=texte.taille(self.volume),
                                                  duree=texte.duree(self.volume / debit)), AVERTISSEMENT)]
        lignes = [_ligne_champ(t("À copier"), t("{taille}, environ {duree}", taille=texte.taille(self.volume),
                                                duree=texte.duree(self.volume / debit)))]
        for numero, raison, volume in self._notes:
            lignes.append(Ligne.de(t("Partition {numero} : {raison} — {taille}, environ {duree} à elle seule",
                                     numero=numero, raison=raison, taille=texte.taille(volume),
                                     duree=texte.duree(volume / DEBIT_LECTURE)), AVERTISSEMENT))
        return lignes


def _plan_disque(disque: devices.Disque, brut: bool | None = None) -> _Plan:
    """Le plan de copie ; une table non reconnue impose la copie intégrale (§9.3)."""
    if brut is None:
        try:
            return _Plan(disque, brut=False)
        except layout.ErreurTable:
            return _Plan(disque, brut=True)
    try:
        return _Plan(disque, brut=brut)
    except layout.ErreurTable:
        return _Plan(disque, brut=True)


def _taille_requise(disque: devices.Disque) -> int:
    try:
        return layout.lire(disque.chemin).taille_requise
    except layout.ErreurTable:
        return disque.taille


def _emplacements_internes() -> list[devices.Emplacement]:
    emplacements = list(devices.emplacements_sata())
    for disque in devices.inventaire():
        e = disque.emplacement
        if e and devices.admis_en_station(e) and e not in emplacements:
            emplacements.append(e)
    return emplacements


def _disques_station(reglage: config.ReglageStation):
    presents = {d.emplacement.cle: d for d in devices.inventaire() if d.emplacement}
    return presents.get(reglage.source), [(cle, presents.get(cle)) for cle in reglage.cibles]


class _Suivi:
    """Les chiffres de l'écran de progression, cumulés d'une partition à l'autre."""

    def __init__(self, operation, volume: int):
        self.operation = operation
        self.volume = volume
        self.debut = time.monotonic()
        self._terminees = 0
        self._ecrits: dict[str, int] = {}  # par cible, les partitions terminées
        self._courante = None

    def page(self, app: Application, titre: str):
        operation = self.operation
        diffusion = operation.diffusion
        if diffusion is not self._courante:
            if self._courante is not None:
                self._terminees += self._courante.octets_lus
                for cible in self._courante.cibles:
                    self._ecrits[cible.nom] = self._ecrits.get(cible.nom, 0) + cible.octets
            self._courante = diffusion
        lu = self._terminees + (diffusion.octets_lus if diffusion else 0)
        ecoule = time.monotonic() - self.debut

        entete = [_ligne_champ(t("Étape"), operation.etape)]
        if isinstance(operation, backup.Sauvegarde):
            entete.append(_ligne_champ(t("Écrit"), t("{taille} compressés", taille=texte.taille(lu))))
        elif self.volume:
            part = min(100, 100 * lu / self.volume)
            valeur = t("{lu} sur {total} ({part} %)", lu=texte.taille(lu), total=texte.taille(self.volume),
                       part=f"{part:.0f}")
            # Au tout début, ou si une cible bloque la lecture, l'estimation n'a
            # aucun sens (« 934 h ») : ne la donner qu'une fois la copie lancée.
            if part >= 1 and ecoule >= 30 and part < 100:
                valeur += t(" — reste environ {duree}", duree=texte.duree(ecoule * (self.volume - lu) / lu))
            entete.append(_ligne_champ(t("Lu"), valeur))
        entete.append(_ligne_champ(t("Écoulé"), texte.duree(ecoule)))

        lignes = []
        suivis = {c.nom: c for c in diffusion.cibles} if diffusion else {}
        if isinstance(operation, clone.Clonage):
            for cible in operation.cibles:
                suivi = suivis.get(cible.nom)
                nom = Ligne([(f"{cible.disque.emplacement.nom if cible.disque.emplacement else cible.nom:<7} "
                              f"{cible.disque.nom_noyau:<8} ", FORT)])
                if cible.etat in (fanout.EN_COURS, clone.REUSSIE) and self.volume:
                    ecrit = self._ecrits.get(cible.nom, 0) + (suivi.octets if suivi else 0)
                    fraction = 1.0 if cible.etat == clone.REUSSIE else min(1.0, ecrit / self.volume)
                    nom.morceaux += barre(fraction) + [(f" {fraction * 100:3.0f} %  ", NORMAL)]
                if cible.etat == fanout.EN_COURS:
                    nom.morceaux.append((texte.debit(suivi.debit) if suivi and suivi.active else "", DETAIL))
                elif cible.etat == clone.REUSSIE:
                    nom.morceaux.append((_nom_etat(cible.etat), OK))
                elif cible.etat == clone.EN_ATTENTE:
                    nom.morceaux.append((_nom_etat(cible.etat), GRISE))
                else:
                    nom.morceaux.append((f"✗ {_nom_etat(cible.etat)}" + (f" — {cible.motif}" if cible.motif else ""),
                                         ECHEC))
                lignes.append(nom)
        elif diffusion:
            suivi = diffusion.cibles[0]
            lignes.append(Ligne([(t("Débit"), FORT), (f"   {texte.debit(suivi.debit)}", NORMAL)]))
        page = app._page(t("{operation} en cours", operation=titre), entete, [(t("Échap"), t("Interrompre"))])
        return page, lignes


def _libelle_disque(disque: devices.Disque) -> str:
    """« SATA2   sdb      Kingston SA400S3      480.1 GB » : l'emplacement d'abord,
    le nom système à titre indicatif (P3)."""
    emplacement = disque.emplacement.nom if disque.emplacement else ""
    return (f"{emplacement:<7} {disque.nom_noyau:<8} {disque.description[:22]:<22} "
            f"{texte.taille(disque.taille):>9}")


def _ligne_champ(libelle: str, valeur: str, style: str = NORMAL) -> Ligne:
    return Ligne([(f"{libelle:<{COLONNE}}", DETAIL), (valeur, style)])


def _ligne_disque(libelle: str, disque: devices.Disque) -> Ligne:
    return Ligne([(f"{libelle:<{COLONNE}}", DETAIL), (_libelle_disque(disque), FORT),
                  (f"   s/n {disque.serie or '?'}", DETAIL)])


def _nom_etat(etat: str) -> str:
    """Le verdict d'une cible, dans la langue de l'interface."""
    return {
        fanout.EN_ATTENTE: t("en attente"),
        fanout.EN_COURS: t("en cours"),
        fanout.REUSSIE: t("RÉUSSIE"),
        fanout.ECHEC: t("ÉCHEC"),
        fanout.BLOQUEE: t("BLOQUÉE"),
        fanout.INTERROMPUE: t("INTERROMPUE"),
        clone.ECARTEE: t("ÉCARTÉE"),
    }.get(etat, etat.upper())


def _nom_operation(operation: str) -> str:
    return {"clonage": t("Clonage"), "sauvegarde": t("Sauvegarde"),
            "restauration": t("Restauration")}.get(operation, operation)


def _rapport_clonage(operation: clone.Clonage, j: Journal, titre: str) -> list[Ligne]:
    reussies = sum(1 for c in operation.cibles if c.etat == clone.REUSSIE)
    lignes = [Ligne.de(t("{operation} du {date} — {n} réussie(s) sur {total}", operation=titre,
                         date=time.strftime("%Y-%m-%d %H:%M"), n=reussies, total=len(operation.cibles)),
                       OK if reussies == len(operation.cibles) else ECHEC),
              Ligne.de(""),
              _ligne_champ(t("Source"), operation.source.description),
              _ligne_champ(t("Durée totale"), texte.duree(operation.duree)), Ligne.de("")]
    for cible in operation.cibles:
        style = OK if cible.etat == clone.REUSSIE else ECHEC
        lignes.append(Ligne([(f"  {cible.disque.libelle:<14} s/n {cible.disque.serie or '?':<18} ", NORMAL),
                             (_nom_etat(cible.etat), style),
                             ((f" — {cible.motif}" if cible.motif else ""), NORMAL)]))
        for avertissement in cible.avertissements:
            lignes.append(Ligne.de(f"      ! {avertissement}", AVERTISSEMENT))
    lignes += [Ligne.de(""), _ligne_champ(t("Journal"), j.dossier)]
    return lignes


def _rapport_sauvegarde(operation: backup.Sauvegarde, j: Journal, stockage) -> list[Ligne]:
    reussie = operation.etat == backup.REUSSIE
    lignes = [Ligne.de(t("Sauvegarde du {date} — {etat}", date=time.strftime("%Y-%m-%d %H:%M"),
                         etat=_nom_etat(operation.etat)), OK if reussie else ECHEC),
              Ligne.de(""),
              _ligne_champ(t("Source"), operation.source.description),
              _ligne_champ(t("Vers"), stockage.nom),
              _ligne_champ(t("Durée totale"), texte.duree(operation.duree)), Ligne.de("")]
    if reussie:
        img = image.lire(operation.dossier)
        lignes.append(_ligne_champ(t("Sauvegarde"), f"« {img.etiquette} », {texte.taille(img.taille_sur_disque)}"))
        lignes.append(_ligne_champ(t("Dossier"), storage.chemin_affiche(stockage, operation.dossier)))
    else:
        lignes.append(_ligne_champ(t("Motif"), operation.motif, ECHEC))
        lignes.append(Ligne.de(t("Le dossier reste incomplet : il ne sera jamais proposé à la restauration."),
                               DETAIL))
    for avertissement in operation.avertissements:
        lignes.append(Ligne.de(f"! {avertissement}", AVERTISSEMENT))
    lignes += [Ligne.de(""), _ligne_champ(t("Journal"), j.dossier)]
    return lignes


def _resume_rapport(rapport: str | None) -> str:
    if not rapport:
        return ""
    premiere = rapport.splitlines()[0]
    return premiere.split(" — ", 1)[1] if " — " in premiere else premiere


def demarrer() -> int:
    """Ouvre l'interface sur le terminal courant."""
    import curses
    import locale
    import signal

    from .. import verrou
    from .ecran import Ecran

    langue.choisir(config.lire().langue)
    tenu = verrou.prendre()
    if tenu is None:
        print(t("CloneGator est déjà ouvert sur un autre écran de cette machine."))
        return 1
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")  # Échap répond tout de suite

    def arreter(_signal, _cadre):
        raise ArretDemande()

    # Extinction de la machine, terminal perdu : arrêt propre, jamais brutal.
    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGHUP, arreter)

    console = _console_physique()

    def principal(fenetre):
        curses.raw()  # Ctrl-C devient une touche : l'interface ne meurt pas en pleine copie
        Application(Ecran(fenetre, console_physique=console)).lancer()

    # Sur une console physique, le noyau écrit ses erreurs (« I/O error… ») par
    # dessus l'écran et le fait défiler. Seules les urgences y passent pendant
    # que CloneGator tourne ; tout reste dans le journal du système.
    niveau = _taire_le_noyau() if console else None
    try:
        curses.wrapper(principal)
    except ArretDemande:
        pass  # demandé hors d'une page : rien à interrompre
    finally:
        if niveau is not None:
            sysexec.ecrire("/proc/sys/kernel/printk", niveau)
        tenu.close()
    return 0


def _console_physique() -> bool:
    """Tourne-t-on sur une console texte de la machine (tty1…), et pas par SSH ?"""
    try:
        return re.fullmatch(r"/dev/tty\d+", os.ttyname(0)) is not None
    except OSError:
        return False


def _taire_le_noyau() -> str | None:
    """Ne laisse passer sur la console que les urgences ; rend le niveau d'origine."""
    reglage = sysexec.lire("/proc/sys/kernel/printk")
    if not reglage:
        return None
    ancien = reglage.split()[0]
    return ancien if sysexec.ecrire("/proc/sys/kernel/printk", "1") else None
