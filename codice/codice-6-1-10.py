# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.10  |  Capítulo 6.1 - As primitivas geométricas
# Seção: O triângulo e as malhas - face.Triangulate()

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB import Options, Solid
import math

FT_M = 0.3048

ref = uidoc.Selection.PickObject(ObjectType.Element)
element = doc.GetElement(ref.ElementId)   # clique na EC-01
opt  = Options()
geom = element.get_Geometry(opt)
n_tri    = 0
area_m2  = 0.0

for g in geom:
    if not isinstance(g, Solid): continue
    for face in g.Faces:
        mesh = face.Triangulate()
        for i in range(mesh.NumTriangles):
            t  = mesh.get_Triangle(i)
            P1, P2, P3 = (t.get_Vertex(j) for j in range(3))
            a = P2 - P1;  b = P3 - P1
            # produto vetorial: n = a x b
            cx = a.Y*b.Z - a.Z*b.Y
            cy = a.Z*b.X - a.X*b.Z
            cz = a.X*b.Y - a.Y*b.X
            area_m2 += 0.5 * math.sqrt(cx*cx + cy*cy + cz*cz) * FT_M**2
            n_tri += 1

print("Triângulos: {}   Área total: {:.2f} m2".format(n_tri, area_m2))
