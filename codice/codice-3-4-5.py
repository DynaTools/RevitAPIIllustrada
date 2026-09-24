# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.4.5  |  Capítulo 3.4 - O Python do ofício
# Seção: O critério como argumento, lambda

larghezze = [0.20, 0.45, 0.10, 0.30]
print(max(larghezze))          # o critério óbvio

quota = {"lavabo": 0.85, "vaso": 0.40, "doccia": 2.10}

# o critério quem decide é você, com key=
print(max(quota, key=lambda nome: quota[nome]))
print(sorted(quota, key=lambda nome: quota[nome]))
