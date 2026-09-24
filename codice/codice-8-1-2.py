# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.1.2  |  Capítulo 8.1 - O comprimento do circuito
# Seção: Passo 3 - o comprimento 3D contra o da planta

# ============================================================
# 0. RECOMEÇO                                   [PY] + [REVIT]
#    bloco autônomo: clique de novo o percurso inteiro
# ============================================================
import math
from Autodesk.Revit.DB import LocationCurve
from Autodesk.Revit.UI.Selection import ObjectType

FT_M  = 0.3048
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
refs  = uidoc.Selection.PickObjects(ObjectType.Element,
                                    "Selecione todo o percurso, então Concluir")

# ============================================================
# 1. PASSO 3, 3D CONTRA PLANTA                           [ENG]
#    só os trechos retos: 3D real e sombra na planta (x,y)
# ============================================================
L3d_ft = 0.0
Lpl_ft = 0.0

for r in refs:
    elem_id = r.ElementId
    elem    = doc.GetElement(elem_id)
    loc     = elem.Location

    if isinstance(loc, LocationCurve):
        curva = loc.Curve
        p0    = curva.GetEndPoint(0)      # ponto inicial
        p1    = curva.GetEndPoint(1)      # ponto final

        dx = p1.X - p0.X                  # diferença em x
        dy = p1.Y - p0.Y                  # diferença em y

        L3d_ft += curva.Length                   # 3D real
        Lpl_ft += math.sqrt(dx * dx + dy * dy)   # sombra na planta

L3d = L3d_ft * FT_M
Lpl = Lpl_ft * FT_M

# ============================================================
# 2. O DESFECHO                                          [OUT]
# ============================================================
print("Comprimento em planta: {:.2f} m".format(Lpl))
print("Comprimento 3D (real): {:.2f} m".format(L3d))
print("Subidas e descidas:    {:.2f} m".format(L3d - Lpl))
