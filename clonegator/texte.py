"""Mises en forme partagées par l'interface et les sous-commandes, dans la
langue de l'interface : « 480,1 Go » en français, « 480.1 GB » en anglais."""

from __future__ import annotations

from .langue import ANGLAIS, actuelle, t


def _nombre(valeur: float) -> str:
    texte = f"{valeur:.1f}"
    return texte if actuelle() == ANGLAIS else texte.replace(".", ",")


def taille(octets: int | None) -> str:
    """Taille en unités décimales, comme les fabricants et `lsblk --bytes`."""
    if octets is None:
        return "?"
    anglais = actuelle() == ANGLAIS
    if octets < 1000:
        return f"{octets} {'B' if anglais else 'o'}"
    unites = ("kB", "MB", "GB", "TB", "PB") if anglais else ("ko", "Mo", "Go", "To", "Po")
    valeur = float(octets)
    for unite in unites:
        valeur /= 1000.0
        if valeur < 1000.0:
            return f"{_nombre(valeur)} {unite}"
    return f"{_nombre(valeur)} {'EB' if anglais else 'Eo'}"


def duree(secondes: float) -> str:
    """« 45 s », « 2 min 10 s », « 1 h 05 »."""
    secondes = int(round(secondes))
    if secondes < 60:
        return f"{secondes} s"
    minutes, secondes = divmod(secondes, 60)
    if minutes < 60:
        return f"{minutes} min {secondes:02d} s" if minutes < 10 else f"{minutes} min"
    heures, minutes = divmod(minutes, 60)
    return f"{heures} h {minutes:02d}"


def debit(octets_par_seconde: float) -> str:
    return f"{octets_par_seconde / 1e6:.0f} {'MB/s' if actuelle() == ANGLAIS else 'Mo/s'}"


def contenu(disque) -> str:
    """« GPT, 5 partitions : vfat, ntfs », de quoi reconnaître un disque d'un coup d'œil."""
    if not disque.table and not disque.partitions:
        return t("vierge ou sans table de partitions")
    morceaux = [(disque.table or t("table inconnue")).upper()]
    nombre = len(disque.partitions)
    types = []
    for partition in disque.partitions:
        if partition.fstype and partition.fstype not in types:
            types.append(partition.fstype)
    partitions = t("{n} partitions", n=nombre) if nombre > 1 else t("{n} partition", n=nombre)
    if types:
        partitions += " : " + ", ".join(types)
    morceaux.append(partitions)

    numeros = [p.numero for p in disque.partitions]
    if numeros and numeros != list(range(1, nombre + 1)):
        # Cas que `clonesrv` ne savait pas traiter : on le rend visible.
        morceaux.append(t("numéros {liste}", liste=", ".join(map(str, numeros))))
    if disque.utilise is not None:
        morceaux.append(t("{taille} utilisés", taille=taille(disque.utilise)))
    return ", ".join(morceaux)
