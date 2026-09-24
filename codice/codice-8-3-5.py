# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.3.5  |  Capítulo 8.3 - A suportação
# Seção: Bônus - todas as eletrocalhas do modelo

# ============================================================
# 0. PREPARAÇÃO                          [PY]+[REVIT]+[ENG]
#    bloco autônomo: bibliotecas, documento e dados de projeto
# ============================================================
import math
from Autodesk.Revit.DB import (FilteredElementCollector,
                               BuiltInCategory, Transaction)

FT_M = 0.3048
PESI = {"FG16 4G95": 4.10, "FG16 5G16": 1.35, "FG16 3G2.5": 0.18}
PESO_PASSERELLA = 5.00
INTERASSE       = 1.50

doc = __revit__.ActiveUIDocument.Document

# ============================================================
# 1. BÔNUS, TODAS AS ELETROCALHAS                      [REVIT]
#    o collector no lugar do clique
# ============================================================
tratti = (FilteredElementCollector(doc)
          .OfCategory(BuiltInCategory.OST_CableTray)
          .WhereElementIsNotElementType())

# ============================================================
# 2. CÁLCULO E ESCRITA EM CADA TRECHO          [ENG] + [REVIT]
#    mesmas fórmulas dos passos 2--4, uma só transação
# ============================================================
tot = 0
t = Transaction(doc, "Suportação do modelo")
t.Start()
for tr in tratti:
    par_n = tr.LookupParameter("Staffe n")
    par_i = tr.LookupParameter("Staffe interasse")
    if par_n is None or par_i is None:
        print("{}: PULADO, parâmetros de suporte ausentes".format(tr.Name))
        continue
    L = tr.Location.Curve.Length * FT_M
    w_t = PESO_PASSERELLA
    for nome, peso in PESI.items():
        par = tr.LookupParameter(nome)
        w_t += peso * (par.AsInteger() if par else 0)
    n_t = int(math.ceil(L / INTERASSE)) + 1
    par_n.Set(n_t)
    par_i.Set(INTERASSE / FT_M)
    tot += n_t
    print("{}: L = {:5.2f} m  w = {:5.2f} kg/m  ->  {} suportes".format(
        tr.Name, L, w_t, n_t))
t.Commit()

# ============================================================
# 3. O TOTAL DO MODELO                                   [OUT]
# ============================================================
print("---")
print("Total de suportes no modelo: {}".format(tot))
