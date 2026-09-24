# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.22.2  |  Capitolo 7.22 - Il conteggio degli sprinkler su una griglia
# Sezione: Passi 3--4 - verifica, conteggio e posa

# PASSO 3: i due vincoli della norma
AREA_MAX = 12.0                    # area massima per testa (m^2)
area_testa = sx * sy               # area coperta da una testa
ok_passo = (sx <= PASSO_MAX) and (sy <= PASSO_MAX)
ok_area  = area_testa <= AREA_MAX
conforme = ok_passo and ok_area

# PASSO 4: genera i centri delle celle (formula del centro, come L-2L)
punti = []
for i in range(nx):
    for j in range(ny):
        x = x0 + (i + 0.5) * sx        # centro cella lungo x
        y = y0 + (j + 0.5) * sy        # centro cella lungo y
        punti.append(XYZ(x / FT_M, y / FT_M, z / FT_M))   # XYZ in piedi

print("Teste sprinkler: {}".format(len(punti)))
print("Area per testa: {:.1f} m2  (max {:.0f})".format(area_testa, AREA_MAX))
print("Passo: {:.2f} m  (max {:.1f})".format(sx, PASSO_MAX))
print("---")
print("ESITO: {}".format("CONFORME" if conforme else "NON CONFORME"))
