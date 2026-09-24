# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 2.3.9  |  Capítulo 2.3 - RevitPythonShell, o playground
# Seção: Decidir com if e else, a bifurcação

larghezza = 0.25

if larghezza > 0.3:
    print("muito espessa")
elif larghezza > 0.2:
    print("espessa")
else:
    print("fina")
