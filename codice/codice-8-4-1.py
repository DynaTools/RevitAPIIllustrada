# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.1  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: No Revit - ler o ambiente, passo e borda

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    bibliotecas e documento Revit ativo
# ============================================================
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048                      # 1 pé = 0.3048 m

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. O CLIQUE NO AMBIENTE                              [REVIT]
#    o ambiente e o seu retângulo alinhado (AABB)
# ============================================================
ref  = uidoc.Selection.PickObject(ObjectType.Element,
                                  "Selecione o ambiente")
room = doc.GetElement(ref.ElementId)
bb   = room.get_BoundingBox(None)

# ============================================================
# 2. ORIGEM E DIMENSÕES                        [REVIT] + [ENG]
#    do retângulo: origem, lados A e B, cota do forro
# ============================================================
x0 = bb.Min.X * FT_M;  A = (bb.Max.X - bb.Min.X) * FT_M
y0 = bb.Min.Y * FT_M;  B = (bb.Max.Y - bb.Min.Y) * FT_M
z  = bb.Max.Z * FT_M                       # cota do forro

# ============================================================
# 3. PASSO E BORDA                                       [ENG]
#    malha nx x ny: passo s = lado / n, borda = s/2
# ============================================================
nx, ny = 4, 3
sx = A / nx
sy = B / ny

# ============================================================
# 4. O RESULTADO                                         [OUT]
# ============================================================
print("Ambiente: {:.2f} x {:.2f} m".format(A, B))
print("Malha {}x{}  ->  passo {:.2f} x {:.2f} m".format(nx, ny, sx, sy))
print("Borda: {:.2f} x {:.2f} m".format(sx/2, sy/2))
