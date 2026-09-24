# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.1  |  Capítulo 6.1 - As primitivas geométricas
# Seção: O ponto - XYZ

from Autodesk.Revit.DB import XYZ

FT_M = 0.3048         # o Revit usa pés; 1 pé = 0.3048 m

# Extremidades do eixo da eletrocalha EC-01
P0 = XYZ(27.204 / FT_M, 15.200 / FT_M, 4.00 / FT_M)
P1 = XYZ(37.596 / FT_M, 21.200 / FT_M, 4.00 / FT_M)

# Vetor direção e comprimento
v = P1 - P0
print("Vetor: ({:.3f}, {:.3f}, {:.3f}) ft".format(v.X, v.Y, v.Z))
print("Distância: {:.3f} m".format(P0.DistanceTo(P1) * FT_M))

# Vetor unitário (a direção sem o comprimento)
u = v.Normalize()
print("Direção: ({:.3f}, {:.3f}, {:.3f})".format(u.X, u.Y, u.Z))
