"""Analyser un disque (§18).

Le verdict se teste sans matériel ; l'analyse complète, sur de petits disques
en boucle créés pour l'occasion (root exigé, ignoré sinon).

    python3 -m unittest -v tests.test_analyse
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from clonegator import analyse, devices, langue, sysexec
from clonegator.analyse import NEUTRE, PROBLEME, SAIN, SURVEILLER, Constat

langue.choisir(langue.FRANCAIS)  # les textes attendus sont écrits en français


def rapport(*etats: str, conseils=(), vierge=False) -> analyse.Analyse:
    disque = SimpleNamespace(table=None if vierge else "gpt", partitions=[] if vierge else [object()])
    a = analyse.Analyse(disque, Constat(SAIN, ""), Constat(SAIN, ""), Constat(SAIN, ""))
    a.partitions = [SimpleNamespace(etat=Constat(etat, ""), volume=0) for etat in etats]
    a.conseils = list(conseils)
    return a


class Verdict(unittest.TestCase):
    def test_tout_sain(self):
        self.assertEqual(rapport(SAIN, NEUTRE).verdict.niveau, SAIN)

    def test_un_probleme_l_emporte(self):
        self.assertEqual(rapport(SAIN, SURVEILLER, PROBLEME, conseils=["x"]).verdict.niveau, PROBLEME)

    def test_un_conseil_demande_de_corriger_avant(self):
        verdict = rapport(SURVEILLER, conseils=["arrêter Windows"]).verdict
        self.assertEqual(verdict.niveau, SURVEILLER)
        self.assertIn("corriger", verdict.texte)

    def test_disque_vierge(self):
        self.assertIn("vierge", rapport(vierge=True).verdict.texte)


def _executer(*argv, entree=None):
    resultat = sysexec.executer(list(argv), entree=entree, delai=120)
    if not resultat.ok:
        raise RuntimeError(f"{' '.join(argv)} : {resultat.erreur}")
    return resultat.sortie.strip()


@unittest.skipUnless(os.geteuid() == 0, "exige root")
class SurDesDisquesDeTest(unittest.TestCase):
    """De vrais systèmes de fichiers, sur des périphériques en boucle."""

    def disque(self, table: str | None, preparer=None) -> devices.Disque:
        image = tempfile.NamedTemporaryFile(delete=False, dir="/var/tmp", suffix=".img")
        image.truncate(256 * 1024 * 1024)
        image.close()
        self.addCleanup(os.unlink, image.name)
        if table:
            _executer("sfdisk", "-q", image.name, entree=table)
        boucle = _executer("losetup", "-fP", "--show", image.name)
        self.addCleanup(_executer, "losetup", "-d", boucle)
        if preparer:
            preparer(boucle)
        _executer("udevadm", "settle")
        return devices.decrire(boucle)

    def test_disque_vierge(self):
        a = analyse.analyser(self.disque(None))
        self.assertEqual(a.verdict.niveau, NEUTRE)

    def test_ntfs_au_secours_efface_est_a_surveiller(self):
        def preparer(boucle):
            _executer("mkntfs", "-q", "-f", f"{boucle}p1")
            fd = os.open(f"{boucle}p1", os.O_RDWR)
            amorce = os.pread(fd, 512, 0)
            position = int.from_bytes(amorce[0x28:0x30], "little") * 512
            os.pwrite(fd, bytes(512), position)
            os.close(fd)

        a = analyse.analyser(self.disque("label: gpt\n,,EBD0A0A2-B9E5-4433-87C0-68B6B72699C7\n", preparer))
        self.assertEqual(a.partitions[0].etat.niveau, SURVEILLER)
        self.assertIn("ntfsfix", a.partitions[0].etat.texte)
        self.assertEqual(a.verdict.niveau, SURVEILLER)

    def test_ext4_sain_sur_mbr_sans_code_d_amorcage(self):
        a = analyse.analyser(self.disque("label: dos\n,,83\n",
                                         lambda boucle: _executer("mkfs.ext4", "-q", f"{boucle}p1")))
        self.assertEqual(a.partitions[0].etat.niveau, SAIN)
        self.assertEqual(a.demarrage.niveau, SURVEILLER)
        self.assertEqual(a.verdict.niveau, SURVEILLER)
        self.assertFalse(sysexec.executer(["blockdev", "--getro", a.disque.chemin]).sortie.strip() == "1")


if __name__ == "__main__":
    unittest.main()
