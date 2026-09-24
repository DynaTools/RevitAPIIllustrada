# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.4  |  Capítulo 6.1 - As primitivas geométricas
# Seção: Reta, segmento e raio - Line

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB import XYZ

FT_M = 0.3048

ref = uidoc.Selection.PickObject(ObjectType.Element)
element = doc.GetElement(ref.ElementId)   # clique na EC-01
# Eixo do elemento a partir da LocationCurve
curve = element.Location.Curve
P0    = curve.GetEndPoint(0)           # início (XYZ em pés)
P1    = curve.GetEndPoint(1)           # fim
L_ft  = P0.DistanceTo(P1)
u     = (P1 - P0).Normalize()         # direção unitária

# Centro geométrico: P(t = L/2)
C = P0 + u * (L_ft / 2.0)

# Ponto no terceiro metro: P(t = 3 m)
t = 3.0 / FT_M                        # t em pés
Pt = P0 + u * t

print("Centro: ({:.3f}, {:.3f}, {:.3f}) m".format(
    C.X*FT_M, C.Y*FT_M, C.Z*FT_M))
print("P(3 m): ({:.3f}, {:.3f}, {:.3f}) m".format(
    Pt.X*FT_M, Pt.Y*FT_M, Pt.Z*FT_M))
