"""Le secteur d'amorçage de secours NTFS écrit sur la cible (filesystems.secours_ntfs).

Un maître dont le secours manque ou est périmé ne doit pas donner des cibles
que ntfsfix refuse : la cible reçoit une copie du secteur d'amorçage, ce qu'un
NTFS sain porte à cet endroit.

    python3 -m unittest -v tests.test_secours_ntfs
"""

from __future__ import annotations

import os
import tempfile
import unittest

from clonegator import filesystems

OCTETS = 512
SECTEURS = 64  # le volume ; le secours est au secteur 64, juste après


def amorce() -> bytes:
    secteur = bytearray(OCTETS)
    secteur[3:11] = b"NTFS    "
    secteur[0x0B:0x0D] = OCTETS.to_bytes(2, "little")
    secteur[0x28:0x30] = SECTEURS.to_bytes(8, "little")
    secteur[510:512] = b"\x55\xaa"
    return bytes(secteur)


class SecoursNtfs(unittest.TestCase):
    def partition(self, secours: bytes) -> str:
        fichier = tempfile.NamedTemporaryFile(delete=False)
        fichier.write(amorce() + bytes(OCTETS * (SECTEURS - 1)) + secours)
        fichier.close()
        self.addCleanup(os.unlink, fichier.name)
        return fichier.name

    def test_un_secours_sain_est_recopie(self):
        position, contenu = filesystems.secours_ntfs(self.partition(amorce()))
        self.assertEqual(position, SECTEURS * OCTETS)
        self.assertEqual(contenu, amorce())

    def test_un_secours_absent_est_recree_d_apres_l_amorce(self):
        position, contenu = filesystems.secours_ntfs(self.partition(bytes(OCTETS)))
        self.assertEqual(position, SECTEURS * OCTETS)
        self.assertEqual(contenu, amorce())

    def test_un_secours_perime_est_remplace(self):
        perime = bytearray(amorce())
        perime[0x28] ^= 0xFF  # un ancien nombre de secteurs
        _, contenu = filesystems.secours_ntfs(self.partition(bytes(perime)))
        self.assertEqual(contenu, amorce())

    def test_pas_de_place_apres_le_volume(self):
        fichier = tempfile.NamedTemporaryFile(delete=False)
        fichier.write(amorce() + bytes(OCTETS * 8))  # partition trop courte
        fichier.close()
        self.addCleanup(os.unlink, fichier.name)
        self.assertIsNone(filesystems.secours_ntfs(fichier.name))


if __name__ == "__main__":
    unittest.main()
