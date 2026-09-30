"""Vérification légère d'une cible, après copie (§11 de l'analyse).

Quelques secondes par cible, sans relire les données. Elle attrape les échecs
les plus fréquents :

  - une table qui n'est pas celle de la source (numéros, positions, types,
    GUID) ;
  - un code d'amorçage absent de la tête du disque ;
  - un système de fichiers copié mais inutilisable, que son propre outil de
    contrôle, en lecture seule, refuse.
"""

from __future__ import annotations

import logging
import os
import re

from . import layout, sysexec
from .devices import Disque
from .langue import t

_log = logging.getLogger("clonegator.verify")

# Contrôle en lecture seule, par type de système de fichiers. Absent : pas de
# contrôle, la vérification de la table reste faite.
_CONTROLES = {
    "ntfs": ["ntfsfix", "--no-action"],
    "ext2": ["e2fsck", "-n", "-f"],
    "ext3": ["e2fsck", "-n", "-f"],
    "ext4": ["e2fsck", "-n", "-f"],
    "vfat": ["fsck.fat", "-n"],
}

# Lignes de ces outils qui n'expliquent rien : bannière de version, étapes,
# bilan final, réponses aux questions de réparation, détails en retrait.
_BRUIT = re.compile(
    r"^(\S+ [\d.]+ \(.*\)|Pass \d.*|\S+: \d+(/\d+)? files.*|Leaving filesystem unchanged\.|.*\? no|\s.*|)$"
)


def verifier(
    table_source: layout.Table,
    tete_source: bytes,
    cible: Disque,
    fstypes: dict[int, str],
) -> list[str]:
    """Problèmes constatés sur la cible ; une liste vide veut dire conforme.

    `fstypes` associe à chaque numéro de partition copiée par partclone le type
    de son système de fichiers.
    """
    problemes = []

    try:
        table_cible = layout.lire(cible.chemin)
    except layout.ErreurTable as erreur:
        return [str(erreur)]
    problemes += layout.comparer(table_source, table_cible)

    try:
        fd = sysexec.ouvrir(cible.chemin)
        try:
            tete = os.pread(fd, layout.CODE_AMORCE, 0)
        finally:
            os.close(fd)
        if tete != tete_source[:layout.CODE_AMORCE]:
            problemes.append(t("code d'amorçage différent de la source"))
    except OSError as erreur:
        problemes.append(t("tête du disque illisible : {erreur}", erreur=erreur.strerror))

    chemins = {partition.numero: partition.chemin for partition in cible.partitions}
    for numero, fstype in sorted(fstypes.items()):
        chemin = chemins.get(numero)
        refus = controler(chemin, fstype) if chemin else ""
        if refus:
            problemes.append(t("partition {numero} ({fstype}) refusée par {programme}", numero=numero,
                               fstype=fstype, programme=refus))
    return problemes


def controlable(fstype: str | None) -> bool:
    return fstype in _CONTROLES


def controler(chemin: str, fstype: str | None) -> str:
    """Le contrôle en lecture seule d'un système de fichiers : chaîne vide s'il
    l'accepte (ou s'il n'y a pas de contrôle pour ce type), sinon l'outil et
    la raison de son refus, « fsck.fat : Volume label '' … is not valid. »

    La raison : la dernière erreur de l'outil, ou à défaut le premier constat
    de sa sortie."""
    controle = _CONTROLES.get(fstype)
    if controle is None:
        return ""
    resultat = sysexec.executer(controle + [chemin], delai=600)
    if resultat.ok:
        return ""
    erreurs = [ligne for ligne in resultat.erreur.splitlines() if not _BRUIT.match(ligne)]
    constats = [ligne for ligne in resultat.sortie.splitlines() if not _BRUIT.match(ligne)]
    raison = erreurs[-1] if erreurs else constats[0] if constats else ""
    return controle[0] + (f" : {raison.strip()}" if raison else "")
