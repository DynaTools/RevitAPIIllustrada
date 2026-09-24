# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.2  |  Capítulo 6.1 - As primitivas geométricas
# Seção: Os dois produtos e o ângulo

import math
from Autodesk.Revit.DB import XYZ

# Direção da EC-01 (da seção O ponto) e eixo global X
u = XYZ(0.866, 0.500, 0.0)
x = XYZ(1.0,   0.0,   0.0)

# Produto escalar -> alinhamento -> cosseno
dot   = u.DotProduct(x)
cos_t = dot / (u.GetLength() * x.GetLength())
print("u . x      = {:.3f}".format(dot))      # 0.866 = cos 30
print("cos(theta) = {:.3f}".format(cos_t))

# Ângulo: pela fórmula (arccos) e pelo método nativo -> coincidem
print("arccos  = {:.1f} graus".format(math.degrees(math.acos(cos_t))))
print("AngleTo = {:.1f} graus".format(math.degrees(u.AngleTo(x))))

# Produto vetorial -> perpendicularidade -> seno
cross = u.CrossProduct(x)
print("|u x x| = {:.3f}".format(cross.GetLength()))   # 0.500 = sin 30
