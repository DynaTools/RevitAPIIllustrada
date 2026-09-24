# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.8  |  Capítulo 6.1 - As primitivas geométricas
# Seção: A esfera envolvente

import math
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB import XYZ

FT_M = 0.3048

ref = uidoc.Selection.PickObject(ObjectType.Element)
element = doc.GetElement(ref.ElementId)   # clique na EC-01
bb   = element.get_BoundingBox(None)
C    = bb.Min + (bb.Max - bb.Min) * 0.5   # centro
r_ft = C.DistanceTo(bb.Max)               # raio em pés (semidiagonal)
r_m  = r_ft * FT_M

# Teste rápido: o ponto Q está dentro da esfera envolvente?
Q = XYZ(35.0 / FT_M, 19.0 / FT_M, 4.0 / FT_M)
in_sfera = C.DistanceTo(Q) <= r_ft

print("Centro: ({:.2f}, {:.2f}, {:.2f}) m".format(
    C.X*FT_M, C.Y*FT_M, C.Z*FT_M))
print("Raio: {:.3f} m".format(r_m))
print("Q na esfera?", in_sfera)
