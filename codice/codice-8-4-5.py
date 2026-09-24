# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.5  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: A mesma música na parede, as tomadas

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
# ============================================================
import math
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048                       # 1 pé = 0.3048 m

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. CLIQUE NA PAREDE E LEIA O SEU EIXO              [REVIT]
# ============================================================
ref   = uidoc.Selection.PickObject(ObjectType.Element, "Selecione a parede")
wall  = doc.GetElement(ref.ElementId)
curve = wall.Location.Curve         # eixo da parede (centerline)
L     = curve.Length * FT_M         # comprimento do eixo em metros

# ============================================================
# 2. NÚMERO DE TOMADAS E PARÂMETROS t_i        [ENG] + [OUT]
# ============================================================
passo_max = 1.50                    # passo máximo (m)
h         = 0.30                    # altura de montagem (m)

N = int(math.ceil(L / passo_max))   # número de intervalos (e de tomadas)
s = L / N                           # passo real (m)

print("Comprimento da parede:{:.2f} m".format(L))
print("Passo máximo: {:.2f} m  ->  N = {} tomadas".format(passo_max, N))
print("Passo real s = L/N: {:.2f} m".format(s))
print("Margem nas bordas (s/2): {:.3f} m".format(s / 2.0))
