# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.23.1  |  Capitolo 7.23 - Il baricentro di un insieme di elementi
# Sezione: Passi 1--3 - leggere le utenze e mediare

from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory,
    XYZ)

FT_M = 0.3048                      # 1 piede = 0.3048 m

doc = __revit__.ActiveUIDocument.Document

# media pesata di una lista di (posizione XYZ, peso): G = somma(w*P)/somma(w)
def baricentro(coppie):
    sw = 0.0
    sx = 0.0
    sy = 0.0
    for P, w in coppie:
        sw += w
        sx += w * P.X           # contributo pesato sulla x
        sy += w * P.Y           # contributo pesato sulla y
    return XYZ(sx / sw, sy / sw, 0.0)

# PASSO 1-2: raccogli le utenze e leggi posizione + peso (carico kW)
# (qui le quattro utenze dell'esempio, gia' in metri, col carico come peso)
utenze = [
    (XYZ(0.0, 0.0, 0.0), 2.0),     # P1
    (XYZ(8.0, 0.0, 0.0), 1.0),     # P2
    (XYZ(8.0, 6.0, 0.0), 3.0),     # P3 (la piu' carica)
    (XYZ(0.0, 6.0, 0.0), 2.0),     # P4
]

# PASSO 3: baricentro semplice (pesi tutti = 1) e pesato (pesi = carico)
G_semplice = baricentro([(P, 1.0) for P, w in utenze])
G_pesato   = baricentro(utenze)

W = sum(w for P, w in utenze)
print("Utenze: {}   carico totale: {:.0f} kW".format(len(utenze), W))
print("Baricentro semplice: ({:.2f}, {:.2f}) m".format(
    G_semplice.X, G_semplice.Y))
print("Baricentro pesato:   ({:.2f}, {:.2f}) m".format(
    G_pesato.X, G_pesato.Y))
