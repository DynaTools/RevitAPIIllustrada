# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.3.1  |  Capítulo 8.3 - A suportação
# Seção: Passos 1--2 - preparação, dados de projeto e seleção

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    bibliotecas e documento Revit ativo
# ============================================================
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048                      # 1 pé = 0.3048 m

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. DADOS DE PROJETO                                    [ENG]
#    pesos por metro das fichas técnicas (kg/m)
# ============================================================
PESI = {
    "FG16 4G95":  4.10,
    "FG16 5G16":  1.35,
    "FG16 3G2.5": 0.18,
}
PESO_PASSERELLA = 5.00             # kg/m, catálogo (450 x 100)

# ============================================================
# 2. PASSO 1, O CLIQUE                         [REVIT] + [OUT]
#    o usuário seleciona o trecho no modelo
# ============================================================
ref  = uidoc.Selection.PickObject(ObjectType.Element,
                                  "Selecione a eletrocalha")
tray = doc.GetElement(ref.ElementId)
print("Selecionado: {}".format(tray.Name))
