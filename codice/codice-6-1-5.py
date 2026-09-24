# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.5  |  Capítulo 6.1 - As primitivas geométricas
# Seção: O plano - Plane

from Autodesk.Revit.DB import Plane, XYZ

FT_M = 0.3048

# Plano horizontal na cota +4.00 m (como a EC-01)
normal = XYZ(0, 0, 1)
origin = XYZ(0, 0, 4.00 / FT_M)
piano  = Plane.CreateByNormalAndOrigin(normal, origin)

# Distância com sinal de um ponto Q ao plano
# Q ligeiramente acima do plano: z = 4.05 m
Q = XYZ(32.40 / FT_M, 18.20 / FT_M, 4.05 / FT_M)
# distância com sinal = projeção de (Q - origem) sobre a normal unitária
delta_m = piano.Normal.DotProduct(Q - piano.Origin) * FT_M
print("Distância com sinal: {:.3f} m".format(delta_m))
print("Q acima do plano?", delta_m > 0)

# Plano vertical que passa pela direção u da EC-01
# n = vetor perpendicular a u no plano horizontal = (-0.5, 0.866, 0)
n_vert = XYZ(-0.5, 0.866, 0)
P_asse = XYZ(32.40 / FT_M, 18.20 / FT_M, 4.00 / FT_M)  # centro EC-01
piano_v = Plane.CreateByNormalAndOrigin(n_vert, P_asse)
print("Plano vertical criado. Normal: ({:.3f}, {:.3f}, {:.3f})".format(
    piano_v.Normal.X, piano_v.Normal.Y, piano_v.Normal.Z))
