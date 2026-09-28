"""La disposition du clavier de la console (§9.8 de l'analyse) : F3.

Sur la console de la machine, la disposition est compilée par `ckbcomp`
(console-setup) à partir des noms XKB, puis chargée par `loadkeys` (kbd) : elle
s'applique tout de suite, à toutes les consoles. Par SSH, le clavier est celui
de l'ordinateur d'où l'on se connecte : rien à changer ici, et l'interface ne
propose pas F3.
"""

from __future__ import annotations

import logging

from . import sysexec
from .langue import t

_log = logging.getLogger("clonegator.clavier")

ANGLAIS_US = "us"

# Code enregistré dans les réglages → disposition et variante XKB. L'ordre est
# celui du menu de F3.
DISPOSITIONS = {
    ANGLAIS_US: ("us", ""),
    "ca": ("ca", ""),
    "ca-multix": ("ca", "multix"),
}


def nom(code: str) -> str:
    """Le nom affiché d'une disposition, dans la langue de l'interface."""
    return {
        ANGLAIS_US: t("Anglais (États-Unis)"),
        "ca": t("Français (Canada)"),
        "ca-multix": t("Canadien multilingue"),
    }.get(code, code)


def appliquer(code: str) -> bool:
    """Charge la disposition dans la console. False si elle n'a pas pu l'être."""
    if code not in DISPOSITIONS:
        return False
    disposition, variante = DISPOSITIONS[code]
    argv = ["ckbcomp", "-model", "pc105", "-layout", disposition]
    if variante:
        argv += ["-variant", variante]
    compilee = sysexec.executer(argv)
    if not compilee.ok:
        return False
    # /dev/tty0 : la console au premier plan. Derrière `sudo`, le terminal du
    # programme est un pseudo-terminal, où loadkeys ne trouverait pas de console.
    chargee = sysexec.executer(["loadkeys", "--quiet", "-C", "/dev/tty0"], entree=compilee.sortie)
    if chargee.ok:
        _log.info("clavier : %s", code)
    return chargee.ok
