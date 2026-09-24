# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.6  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: A mesma música na parede, as tomadas

# ============================================================
# 0. RECOMEÇO                                            [PY]
#    mesma sessão: curve, L, N, s e h na memória
# ============================================================
from Autodesk.Revit.DB import XYZ

# ============================================================
# 1. OS PONTOS P(t_i), ERGUIDOS À ALTURA h     [ENG] + [OUT]
# ============================================================
punti = []
for i in range(N):
    t  = (i + 0.5) / N              # parâmetro normalizado t_i
    pt = curve.Evaluate(t, True)    # ponto no eixo (XYZ em pés)
    pt = XYZ(pt.X, pt.Y, pt.Z + h / FT_M)   # ergue a h (h em metros -> pés)
    punti.append(pt)
    print("tomada {}: t={:.3f}  d={:.3f} m  ({:.2f}, {:.2f}) m".format(
        i, t, t * L, pt.X * FT_M, pt.Y * FT_M))

print("---")
print("Pontos gerados: {}".format(len(punti)))
