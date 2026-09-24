# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.4.2  |  Capítulo 3.4 - O Python do ofício
# Seção: A receita que você escreve, def

def in_metri(piedi):
    return piedi * 0.3048     # a conversão da Lei II

print(in_metri(10))
print("{:.2f} m".format(in_metri(32.8)))
