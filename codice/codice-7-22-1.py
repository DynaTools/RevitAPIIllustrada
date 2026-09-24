# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.22.1  |  Capitolo 7.22 - Il conteggio degli sprinkler su una griglia
# Sezione: Passi 1--2 - il locale e la sua griglia

import math
from Autodesk.Revit.DB import XYZ
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048                      # 1 piede = 0.3048 m

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# PASSO 1: clicca il locale e leggi il suo bounding box (AABB)
ref    = uidoc.Selection.PickObject(ObjectType.Element, "Seleziona il locale")
locale = doc.GetElement(ref.ElementId)
bb     = locale.get_BoundingBox(None)

x0 = bb.Min.X * FT_M;  Lx = (bb.Max.X - bb.Min.X) * FT_M
y0 = bb.Min.Y * FT_M;  Ly = (bb.Max.Y - bb.Min.Y) * FT_M
z  = bb.Max.Z * FT_M                       # quota soffitto

# PASSO 2: la griglia col tetto sul passo massimo (UNI EN 12845)
PASSO_MAX = 4.0                    # passo massimo fra teste (m)
nx = int(math.ceil(Lx / PASSO_MAX))
ny = int(math.ceil(Ly / PASSO_MAX))
sx = Lx / nx                       # passo reale lungo x
sy = Ly / ny                       # passo reale lungo y

print("Locale: {:.2f} x {:.2f} m".format(Lx, Ly))
print("Griglia {}x{}  ->  teste {}".format(nx, ny, nx * ny))
print("Passo reale: {:.2f} x {:.2f} m".format(sx, sy))
