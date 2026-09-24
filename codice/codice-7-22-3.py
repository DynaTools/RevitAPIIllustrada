# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.22.3  |  Capitolo 7.22 - Il conteggio degli sprinkler su una griglia
# Sezione: Lo stesso conteggio - le lampade di emergenza

import math

L = 30.0                           # lunghezza corridoio (m)
PASSO_MAX = 6.0                    # passo massimo fra lampade (m)

intervalli = int(math.ceil(L / PASSO_MAX))
n_lampade  = intervalli + 1        # nodi = intervalli + 1 (estremi inclusi)
passo_reale = L / intervalli

print("Corridoio: {:.1f} m  (passo max {:.1f} m)".format(L, PASSO_MAX))
print("Lampade di emergenza: {}".format(n_lampade))
print("Passo reale: {:.2f} m".format(passo_reale))
