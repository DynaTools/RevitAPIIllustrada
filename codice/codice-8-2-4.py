# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.2.4  |  Capítulo 8.2 - A taxa de ocupação dos eletrodutos
# Seção: O veredito escrito no modelo

# ============================================================
# 0. RECOMEÇO                              [PY]+[REVIT]+[ENG]
#    bloco autônomo: refaz o clique e recalcula o resultado em
#    forma compacta (o pi/4 se simplifica na razão)
# ============================================================
import math
from Autodesk.Revit.DB import BuiltInParameter
from Autodesk.Revit.UI.Selection import ObjectType

FT_MM    = 304.8
CATALOGO = [("FG16R16 16",  11.4), ("FG16R16 25",  13.2),
            ("FG16R16 35",  14.6), ("FG16R16 50",  16.4),
            ("FG16R16 70",  17.3), ("FG16R16 95",  20.4),
            ("FG16R16 120", 22.4), ("FG16R16 150", 24.8),
            ("FG16R16 185", 27.2), ("FG16R16 240", 30.4),
            ("FG16R16 300", 33.0)]

uidoc    = __revit__.ActiveUIDocument
doc      = uidoc.Document
finestra = globals().get("__window__")

if finestra:
    finestra.Hide()
ref     = uidoc.Selection.PickObject(ObjectType.Element,
                                     "Selecione o eletroduto")
conduit = doc.GetElement(ref.ElementId)
if finestra:
    finestra.Show()

De = conduit.get_Parameter(
    BuiltInParameter.RBS_CONDUIT_INNER_DIAM_PARAM).AsDouble() * FT_MM

somma_d2 = 0.0
for nome, d in CATALOGO:
    par = conduit.LookupParameter(nome)
    q   = par.AsInteger() if par is not None else 0
    somma_d2 += d**2 * q

if somma_d2 == 0:                    # nenhum cabo declarado
    raise Exception("Este trecho não declara nenhum cabo; "
                    "preencha antes os parâmetros (Passo 1).")

K      = somma_d2 / De**2          # o pi/4 se simplifica
norma  = De >= 1.3 * math.sqrt(somma_d2)
prassi = K <= 0.40

esito = "CONFORME" if (norma and prassi) else (
    "NO LIMITE" if norma else "NÃO CONFORME")

# ============================================================
# 1. A COR NO MODELO                           [REVIT] + [OUT]
#    Lei I: toda modificação vive numa Transaction.
#    Uma cor por resultado, assim a verificação se vê na vista
#    sem voltar a reler o console.
#      verde    = passa norma e prática
#      amarelo  = a norma passa, a prática não
#      vermelho = fora da norma
# ============================================================
from Autodesk.Revit.DB import (Transaction, OverrideGraphicSettings,
                               Color, FilteredElementCollector,
                               FillPatternElement)

COLORI = {"CONFORME":     (Color(0, 150, 60),   "VERDE"),
          "NO LIMITE":    (Color(235, 160, 0),  "AMARELO"),
          "NÃO CONFORME": (Color(200, 30, 30),  "VERMELHO")}

colore, nome_colore = COLORI[esito]

# o hachurado sólido se procura por propriedade, não por nome:
# assim o script vale em qualquer idioma do Revit
pieno = None
for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if fp.GetFillPattern().IsSolidFill:
        pieno = fp
        break

ogs = OverrideGraphicSettings()
ogs.SetProjectionLineColor(colore)
if pieno is not None:
    ogs.SetSurfaceForegroundPatternId(pieno.Id)
    ogs.SetSurfaceForegroundPatternColor(colore)
    ogs.SetSurfaceForegroundPatternVisible(True)

t = Transaction(doc, "Colorir o resultado da ocupação")
t.Start()
doc.ActiveView.SetElementOverrides(conduit.Id, ogs)
t.Commit()

print("Resultado: {}".format(esito))
print("Eletroduto colorido na vista: {}.".format(nome_colore))
