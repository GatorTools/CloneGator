"""Analyser un disque (§18 de l'analyse) : ce qu'il contient et son état.

Rien n'est écrit. Le disque passe en lecture seule noyau pendant les contrôles,
comme la source d'une copie (P1) ; la seule chose montée est la partition EFI,
en lecture seule, le temps d'y chercher un chargeur.

Ce module produit un rapport structuré et ne dessine rien : l'interface le met
en forme, à l'écran et au journal. Chaque constat porte un niveau — sain, à
surveiller, problème, ou neutre (une simple information) — et son texte.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from . import devices, filesystems, health, layout, montage, sysexec, verify
from .devices import Disque, Partition
from .langue import t

_log = logging.getLogger("clonegator.analyse")

SAIN = "sain"
SURVEILLER = "surveiller"
PROBLEME = "probleme"
NEUTRE = "neutre"

# Une partition non reconnue, copiée en entier, compte au-delà de cette taille
# (comme à l'écran de confirmation).
SEUIL_COPIE_INTEGRALE = 1_000_000_000

_TYPES_GPT = {
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b": "efi",
    "e3c9e316-0b5c-4db8-817d-f92df00215ae": "reservee",
    "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7": "donnees",
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac": "recuperation",
    "0fc63daf-8483-4772-8e79-3d69d8477de4": "linux",
    "0657fd6d-a4ab-43c4-84e5-0933c84b4f4f": "swap",
}
_TYPES_MBR = {"ef": "efi", "7": "donnees", "b": "donnees", "c": "donnees", "e": "donnees",
              "83": "linux", "82": "swap", "27": "recuperation"}

# Le chargeur de repli de l'UEFI, qui accompagne souvent un chargeur nommé.
GENERIQUE = "generique"

# Chargeurs cherchés dans la partition EFI, dans cet ordre.
_CHARGEURS = (
    ("EFI/Microsoft/Boot/bootmgfw.efi", "Windows"),
    ("EFI/ubuntu/shimx64.efi", "Ubuntu"),
    ("EFI/debian/shimx64.efi", "Debian"),
    ("EFI/fedora/shimx64.efi", "Fedora"),
    ("EFI/BOOT/BOOTX64.EFI", GENERIQUE),
)


class ErreurAnalyse(Exception):
    pass


@dataclass
class Constat:
    niveau: str
    texte: str


@dataclass
class EtatPartition:
    numero: int
    genre: str  # efi, reservee, donnees, recuperation, linux, swap, ou vide
    partition: Partition
    etat: Constat
    moteur: str  # comme filesystems : partclone, brut, swap, aucun
    volume: int  # octets qu'une copie lirait
    utilise: int | None  # octets occupés, quand on sait le lire


@dataclass
class Analyse:
    disque: Disque
    sante: Constat
    table: Constat
    demarrage: Constat
    partitions: list[EtatPartition] = field(default_factory=list)
    sauvegardes: bool = False  # porte des sauvegardes CloneGator
    conseils: list[str] = field(default_factory=list)

    @property
    def vierge(self) -> bool:
        return not self.disque.table and not self.disque.partitions

    @property
    def volume(self) -> int:
        return sum(p.volume for p in self.partitions)

    @property
    def verdict(self) -> Constat:
        constats = [self.sante, self.table] + [p.etat for p in self.partitions]
        if self.vierge:
            return Constat(NEUTRE, t("Disque vierge : rien à cloner."))
        if any(c.niveau == PROBLEME for c in constats):
            return Constat(PROBLEME, t("En mauvais état : voir les points en rouge."))
        if self.conseils:
            return Constat(SURVEILLER, t("À corriger avant de cloner."))
        if any(c.niveau == SURVEILLER for c in constats + [self.demarrage]):
            return Constat(SURVEILLER, t("Prêt à cloner, avec des points à surveiller."))
        return Constat(SAIN, t("Prêt à cloner."))


def analyser(disque: Disque) -> Analyse:
    """Le rapport d'un disque. Lève ErreurAnalyse s'il ne peut pas être analysé."""
    refus = devices.refus_comme_source(disque)
    if refus:
        raise ErreurAnalyse(f"{disque.libelle} : {refus}")

    try:
        table = layout.lire(disque.chemin)
    except layout.ErreurTable:
        table = None
    # Monter la partition EFI d'abord : la sonde gère elle-même sa lecture seule.
    demarrage = _demarrage(disque, table)
    sauvegardes = devices.contient_sauvegardes(disque)

    if not devices.proteger(disque):
        raise ErreurAnalyse(t("le disque n'a pas pu être mis en lecture seule"))
    try:
        analyse = Analyse(disque, _sante(disque), _table(disque, table), demarrage,
                          sauvegardes=sauvegardes)
        if table is not None:
            for entree in table.entrees:
                partition = next((p for p in disque.partitions if p.numero == entree.numero), None)
                if partition is not None:
                    analyse.partitions.append(_partition(entree, partition, table, analyse.conseils))
    finally:
        devices.liberer(disque)
    _log.info("%s : %s", disque.libelle, analyse.verdict.texte)
    return analyse


# ------------------------------------------------------------------ constats ---

def _sante(disque: Disque) -> Constat:
    sante = health.etat(disque)
    niveau = {health.OK: SAIN, health.USURE: SURVEILLER, health.DEFAILLANT: PROBLEME}.get(sante.niveau, NEUTRE)
    if sante.niveau == health.INCONNU:
        return Constat(NEUTRE, t("SMART indisponible (souvent un adaptateur USB)"))
    return Constat(niveau, health.resume(sante))


def _table(disque: Disque, table: layout.Table | None) -> Constat:
    if not disque.table and not disque.partitions:
        return Constat(NEUTRE, t("aucune table de partitions"))
    if table is None:
        return Constat(PROBLEME, t("table illisible : seule une copie intégrale du disque est possible"))
    n = len(table.entrees)
    if not table.gpt:
        return Constat(SAIN, t("MBR, {n} partition(s)", n=n))
    if _secours_gpt_present(disque):
        return Constat(SAIN, t("GPT, {n} partition(s), table de secours présente", n=n))
    return Constat(SURVEILLER, t("GPT, {n} partition(s), table de secours absente ; une copie la recrée", n=n))


def _secours_gpt_present(disque: Disque) -> bool:
    """L'en-tête GPT de secours, dans le dernier secteur du disque."""
    try:
        fd = sysexec.ouvrir(disque.chemin)
        try:
            secteur = os.pread(fd, disque.secteur_logique, disque.taille - disque.secteur_logique)
        finally:
            os.close(fd)
    except OSError:
        return False
    return secteur[:8] == b"EFI PART"


def _demarrage(disque: Disque, table: layout.Table | None) -> Constat:
    if table is None:
        return Constat(NEUTRE, t("inconnu"))
    if not table.gpt:
        try:
            fd = sysexec.ouvrir(disque.chemin)
            try:
                mbr = os.pread(fd, 512, 0)
            finally:
                os.close(fd)
        except OSError:
            return Constat(NEUTRE, t("inconnu"))
        if mbr[510:512] == b"\x55\xaa" and any(mbr[:440]):
            return Constat(SAIN, t("BIOS : code d'amorçage présent"))
        return Constat(SURVEILLER, t("BIOS : pas de code d'amorçage"))

    efi = next((e for e in table.entrees if _genre(e) == "efi"), None)
    partition = next((p for p in disque.partitions if efi and p.numero == efi.numero), None)
    if partition is None:
        return Constat(SURVEILLER, t("UEFI : pas de partition système EFI"))
    with montage.sonde(partition.chemin, partition.fstype) as point:
        if point is None:
            return Constat(SURVEILLER, t("UEFI : partition système EFI illisible"))
        # vfat ne distingue pas les majuscules : les chemins se trouvent tels quels.
        trouves = [nom for chemin, nom in _CHARGEURS if os.path.exists(os.path.join(point, chemin))]
    nommes = [nom for nom in trouves if nom != GENERIQUE]
    if nommes:
        return Constat(SAIN, t("UEFI : chargeur {liste}", liste=", ".join(nommes)))
    if trouves:
        return Constat(SAIN, t("UEFI : chargeur générique"))
    return Constat(SURVEILLER, t("UEFI : aucun chargeur connu dans la partition EFI"))


def _partition(entree: layout.Entree, partition: Partition, table: layout.Table,
               conseils: list[str]) -> EtatPartition:
    choix = filesystems.choisir(partition, entree.etendue)
    volume = filesystems.volume_a_copier(partition, choix)
    etat = Constat(SAIN, t("sain"))

    if choix.moteur == filesystems.AUCUN:
        etat = Constat(NEUTRE, t("partition étendue"))
    elif choix.moteur == filesystems.SWAP:
        etat = Constat(NEUTRE, t("swap, recréée à la copie"))
    elif choix.avertissement:
        # Hiberné, mal démonté : copié en entier tant que ce n'est pas corrigé.
        etat = Constat(SURVEILLER, choix.raison)
        conseil = (t("Faire un arrêt complet de Windows (Maj + Arrêter), puis analyser à nouveau.")
                   if (partition.fstype or "").lower() == "ntfs"
                   else t("Réparer le système de fichiers (fsck), puis analyser à nouveau."))
        if conseil not in conseils:
            conseils.append(conseil)
    elif choix.moteur == filesystems.BRUT:
        chiffree = (partition.fstype or "").lower() in ("bitlocker", "crypto_luks")
        if chiffree:
            etat = Constat(SURVEILLER if volume >= SEUIL_COPIE_INTEGRALE else NEUTRE, t("chiffrée"))
        elif volume >= SEUIL_COPIE_INTEGRALE:
            etat = Constat(SURVEILLER, choix.raison)
        else:
            etat = Constat(NEUTRE, t("rien à vérifier"))
    elif verify.controlable(partition.fstype):
        # Une copie reproduit ce défaut tel quel, sans le reprocher aux cibles.
        refus = verify.controler(partition.chemin, partition.fstype)
        if refus:
            etat = Constat(SURVEILLER, t("refusée par {controle}, sera copiée telle quelle", controle=refus))

    utilise = partition.utilise
    if utilise is None and choix.moteur == filesystems.PARTCLONE:
        utilise = filesystems.espace_utilise(partition)
    return EtatPartition(entree.numero, _genre(entree), partition, etat, choix.moteur, volume, utilise)


def _genre(entree: layout.Entree) -> str:
    type_ = entree.type.lower()
    return _TYPES_GPT.get(type_) or _TYPES_MBR.get(type_.removeprefix("0x"), "")
