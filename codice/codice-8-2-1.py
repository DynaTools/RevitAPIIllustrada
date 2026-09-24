# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.2.1  |  Capítulo 8.2 - A taxa de ocupação dos eletrodutos
# Seção: Passos 2--3 - pegar o eletroduto e ler o seu diâmetro

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    bibliotecas, conversão e documento Revit ativo
# ============================================================
import math
from Autodesk.Revit.DB import BuiltInParameter
from Autodesk.Revit.UI.Selection import ObjectType

FT_MM = 304.8                      # 1 pé = 304.8 mm

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# O RPS oferece __window__, a janela do shell. Tirá-la
# do caminho deixa o clique chegar ao modelo mesmo
# quando o shell roda em modo modal.
finestra = globals().get("__window__")

# ============================================================
# 1. PASSO 2, O CLIQUE                                 [REVIT]
#    aperte Run: o shell sai da frente, você escolhe o eletroduto
#    no modelo, e a janela volta com o resultado.
#    A Marca (Mark) diz qual trecho é, se estiver preenchida
# ============================================================
if finestra:
    finestra.Hide()

ref     = uidoc.Selection.PickObject(ObjectType.Element,
                                     "Selecione o eletroduto")
conduit = doc.GetElement(ref.ElementId)

if finestra:
    finestra.Show()

p_marca = conduit.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
marca   = p_marca.AsString() if p_marca is not None else None
tratto  = marca if marca else "id {}".format(conduit.Id)

# ============================================================
# 2. PASSO 3, O DIÂMETRO                       [REVIT] + [ENG]
#    diâmetro interno (a API devolve pés -> mm)
# ============================================================
De = conduit.get_Parameter(
    BuiltInParameter.RBS_CONDUIT_INNER_DIAM_PARAM).AsDouble() * FT_MM

A_tubo = math.pi / 4.0 * De**2     # área interna em mm^2

# ============================================================
# 3. O RESULTADO                                         [OUT]
# ============================================================
print("Eletroduto {}".format(tratto))
print("Diâmetro interno De: {:.1f} mm".format(De))
print("Área interna do tubo: {:.0f} mm2".format(A_tubo))
