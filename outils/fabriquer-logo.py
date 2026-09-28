#!/usr/bin/env python3
"""Tire du logo GatorTools la grille de l'écran d'accueil (clonegator/ui/logo.txt).

    ./outils/fabriquer-logo.py logo-gatortools.png

Chaque caractère de la grille est une case d'écran : « v » vert (l'alligator,
« Gator »), « b » blanc (l'engrenage, la clé, « Tools »), espace pour le fond.
Une case de console est deux fois plus haute que large : la grille fait deux
fois plus de colonnes que de lignes, à proportions égales. Elle est fine
(340 colonnes) ; CloneGator la réduit à la taille de l'écran au lancement.

Le PNG est lu avec la bibliothèque standard : RGB ou RGBA 8 bits, non entrelacé.
"""

import struct
import sys
import zlib

COLONNES = 340
SEUIL = 0.5  # part d'une case qui doit être de la couleur pour qu'elle le soit


def lire_png(chemin):
    donnees = open(chemin, "rb").read()
    position, idat = 8, b""
    while position < len(donnees):
        longueur, genre = struct.unpack(">I4s", donnees[position:position + 8])
        bloc = donnees[position + 8:position + 8 + longueur]
        position += 12 + longueur
        if genre == b"IHDR":
            largeur, hauteur, profondeur, couleur, _, _, entrelace = struct.unpack(">IIBBBBB", bloc)
            assert profondeur == 8 and couleur in (2, 6) and entrelace == 0, "PNG non pris en charge"
        elif genre == b"IDAT":
            idat += bloc
    brut = zlib.decompress(idat)
    pas = 3 if couleur == 2 else 4
    ligne_octets = largeur * pas
    lignes, precedente, i = [], bytearray(ligne_octets), 0
    for _ in range(hauteur):
        filtre = brut[i]
        ligne = bytearray(brut[i + 1:i + 1 + ligne_octets])
        i += 1 + ligne_octets
        for x in range(ligne_octets):
            a = ligne[x - pas] if x >= pas else 0
            b = precedente[x]
            c = precedente[x - pas] if x >= pas else 0
            if filtre == 1:
                ligne[x] = (ligne[x] + a) & 255
            elif filtre == 2:
                ligne[x] = (ligne[x] + b) & 255
            elif filtre == 3:
                ligne[x] = (ligne[x] + (a + b) // 2) & 255
            elif filtre == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                ligne[x] = (ligne[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        lignes.append(ligne)
        precedente = ligne

    def pixel(x, y):
        r, g, b = lignes[y][x * pas:x * pas + 3]
        if pas == 4:  # composé sur blanc
            alpha = lignes[y][x * pas + 3]
            r, g, b = ((v * alpha + 255 * (255 - alpha)) // 255 for v in (r, g, b))
        return r, g, b

    return largeur, hauteur, pixel


def main(chemin):
    largeur, hauteur, pixel = lire_png(chemin)

    def genre(x, y):
        r, g, b = pixel(x, y)
        if g > r + 40 and g > b + 20:
            return "v"
        if max(r, g, b) < 110:
            return "b"
        return " "

    # Le cadre du dessin : tout ce qui n'est pas du fond.
    xs, ys = [], []
    for y in range(0, hauteur, 2):
        for x in range(0, largeur, 2):
            if genre(x, y) != " ":
                xs.append(x)
                ys.append(y)
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1

    rangees = round(COLONNES * (y1 - y0) / (x1 - x0) / 2)
    fx, fy = (x1 - x0) / COLONNES, (y1 - y0) / rangees
    for r in range(rangees):
        ligne = []
        for c in range(COLONNES):
            compte = {"v": 0, "b": 0, " ": 0}
            for y in range(int(y0 + r * fy), max(int(y0 + (r + 1) * fy), int(y0 + r * fy) + 1)):
                for x in range(int(x0 + c * fx), max(int(x0 + (c + 1) * fx), int(x0 + c * fx) + 1)):
                    compte[genre(x, y)] += 1
            total = sum(compte.values())
            ligne.append("v" if compte["v"] > total * SEUIL else "b" if compte["b"] > total * SEUIL else " ")
        print("".join(ligne).rstrip())


if __name__ == "__main__":
    main(sys.argv[1])
