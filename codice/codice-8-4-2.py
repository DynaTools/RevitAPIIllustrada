# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.2  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: No Revit - a fórmula do centro gera os pontos

# ============================================================
# 0. RECOMEÇO                                   [PY] + [REVIT]
#    bloco autônomo: relê o ambiente, refaz passo e borda
# ============================================================
from Autodesk.Revit.DB import XYZ
from Autodesk.Revit.UI.Selection import ObjectType

FT_M  = 0.3048
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

ref = uidoc.Selection.PickObject(ObjectType.Element,
                                 "Selecione o ambiente")
bb  = doc.GetElement(ref.ElementId).get_BoundingBox(None)

x0 = bb.Min.X * FT_M;  A = (bb.Max.X - bb.Min.X) * FT_M
y0 = bb.Min.Y * FT_M;  B = (bb.Max.Y - bb.Min.Y) * FT_M
z  = bb.Max.Z * FT_M                       # cota do forro

nx, ny = 4, 3
sx = A / nx;  sy = B / ny

# ============================================================
# 1. A FÓRMULA DO CENTRO                          [PY] + [ENG]
#    x = x0 + (i + 1/2)*s: o laço duplo gera a malha
# ============================================================
punti = []
for i in range(nx):
    for j in range(ny):
        x = x0 + (i + 0.5) * sx        # centro da célula ao longo de x
        y = y0 + (j + 0.5) * sy        # centro da célula ao longo de y
        punti.append(XYZ(x / FT_M, y / FT_M, z / FT_M))   # XYZ em pés

# ============================================================
# 2. O RESULTADO                                         [OUT]
# ============================================================
print("Pontos gerados: {}".format(len(punti)))
for p in punti[:4]:
    print("  ({:.2f}, {:.2f}) m".format(p.X * FT_M, p.Y * FT_M))
print("  ...")
