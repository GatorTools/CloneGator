"""Comment CloneGator a été démarré.

Le live (§15) ouvre CloneGator d'office sur la console, et n'enregistre rien
d'un démarrage à l'autre : quelques écrans en tiennent compte, comme
« Quitter », qui y propose d'éteindre, de redémarrer ou d'ouvrir une console.
"""

from __future__ import annotations

from . import sysexec


def en_live() -> bool:
    """CloneGator tourne-t-il depuis le live ?"""
    return "boot=live" in (sysexec.lire("/proc/cmdline") or "").split()
