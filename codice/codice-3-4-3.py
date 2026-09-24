# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.4.3  |  Capítulo 3.4 - O Python do ofício
# Seção: O fichário de bolso, o dicionário

quota = {"lavabo": 0.85, "vaso": 0.40, "doccia": 2.10}

print(quota["doccia"])        # busca-se pela chave, não pela posição

quota["bidet"] = 0.40         # uma ficha nova, na hora

for nome in quota:
    print(nome, "->", quota[nome])
