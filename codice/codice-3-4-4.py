# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.4.4  |  Capítulo 3.4 - O Python do ofício
# Seção: A esteira numa linha, a comprehension

larghezze = [0.20, 0.45, 0.10, 0.30]

spessi = [w for w in larghezze if w > 0.25]      # filtrar
centimetri = [w * 100 for w in larghezze]        # transformar

print(spessi)
print(centimetri)
