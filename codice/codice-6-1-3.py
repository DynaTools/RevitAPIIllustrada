# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.3  |  Capítulo 6.1 - As primitivas geométricas
# Seção: Os dois produtos e o ângulo

import math
from Autodesk.Revit.DB import XYZ

# Tubo de esgoto: 5,00 m na horizontal, 0,10 m de desnível
P0 = XYZ(0.0, 0.0, 0.00)
P1 = XYZ(5.0, 0.0, 0.10)
u  = (P1 - P0).Normalize()

# u.Z é o seno do ângulo com o plano horizontal
alpha = math.degrees(math.asin(u.Z))
print("Declividade: {:.1f} graus".format(alpha))
print("Declividade: {:.1f} %".format(100.0 * math.tan(math.radians(alpha))))
