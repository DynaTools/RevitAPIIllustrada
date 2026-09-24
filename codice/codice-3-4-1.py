# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.4.1  |  Capítulo 3.4 - O Python do ofício
# Seção: A etiqueta com janelinhas, format

n = 42
larghezza = 0.4572

print("paredes encontradas -> " + str(n))     # concatenar cansa
print("paredes encontradas -> {}".format(n))  # a janelinha
print("{} paredes, a mais espessa {:.2f} m".format(n, larghezza))
