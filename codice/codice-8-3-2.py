# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.3.2  |  Capítulo 8.3 - A suportação
# Seção: Passos 1--2 - leitura, cálculo e resultado

# ============================================================
# 0. RECOMEÇO                                   [PY] + [REVIT]
#    bloco autônomo: import, dados e seleção, compactados
# ============================================================
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048
PESI = {"FG16 4G95": 4.10, "FG16 5G16": 1.35, "FG16 3G2.5": 0.18}
PESO_PASSERELLA = 5.00

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
ref   = uidoc.Selection.PickObject(ObjectType.Element,
                                   "Selecione a eletrocalha")
tray  = doc.GetElement(ref.ElementId)

# ============================================================
# 1. PASSO 1, A LEITURA                        [REVIT] + [ENG]
#    comprimento da curva, de pés para metros (Lei II)
# ============================================================
L_run = tray.Location.Curve.Length * FT_M
print("Trecho: {}   L = {:.2f} m".format(tray.Name, L_run))

# ============================================================
# 2. PASSO 2, O CÁLCULO                        [ENG] + [REVIT]
#    w = eletrocalha + soma (peso x quantidade)
# ============================================================
w = PESO_PASSERELLA
for nome, peso in PESI.items():
    par = tray.LookupParameter(nome)
    if par is None:
        print("  {:>11}: PARÂMETRO AUSENTE no trecho".format(nome))
        continue
    n = par.AsInteger()
    w += peso * n
    print("  {:>11}: {:.2f} kg/m  x{}  ->  {:.2f} kg/m".format(
        nome, peso, n, peso * n))

# ============================================================
# 3. O RESULTADO                                         [OUT]
# ============================================================
print("Peso da eletrocalha: {:.2f} kg/m".format(PESO_PASSERELLA))
print("Peso por metro w: {:.2f} kg/m".format(w))
