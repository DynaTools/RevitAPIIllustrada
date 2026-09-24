# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.2.3  |  Capítulo 8.2 - A taxa de ocupação dos eletrodutos
# Seção: Passo 5 - calcular e verificar

# ============================================================
# 0. RECOMEÇO                              [PY]+[REVIT]+[ENG]
#    bloco autônomo: recria De, A_tubo e as áreas dos cabos
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
finestra = globals().get("__window__")   # o shell do RPS, se houver

if finestra:
    finestra.Hide()                      # ... sai do caminho
ref     = uidoc.Selection.PickObject(ObjectType.Element,
                                     "Selecione o eletroduto")
conduit = doc.GetElement(ref.ElementId)
if finestra:
    finestra.Show()                      # ... e volta com o resultado

De      = conduit.get_Parameter(
    BuiltInParameter.RBS_CONDUIT_INNER_DIAM_PARAM).AsDouble() * FT_MM
A_tubo  = math.pi / 4.0 * De**2

A_cavi = somma_d2 = 0.0
for nome, d in CATALOGO:
    par = conduit.LookupParameter(nome)
    q   = par.AsInteger() if par is not None else 0
    A_cavi   += math.pi / 4.0 * d**2 * q
    somma_d2 += d**2 * q

if somma_d2 == 0:                    # nenhum cabo declarado
    raise Exception("Este trecho não declara nenhum cabo; "
                    "preencha antes os parâmetros (Passo 1).")

# ============================================================
# 1. PASSO 5, OCUPAÇÃO E VERIFICAÇÃO                     [ENG]
#    Os limites são DOIS, e não coincidem.
#    - a norma CEI 64-8:   De >= 1,3 x Dt
#    - a boa prática:      K <= 40 %
#    Como K = Dt^2 / De^2, a primeira equivale a K <= 1/1,69,
#    ou seja, 59,2 %. Só o coeficiente 1,3 deixa, portanto,
#    passar tubos mais que meio cheios: a prática é mais severa.
# ============================================================
LIMITE_PRASSI = 0.40               # boa prática: 40 % de ocupação

K = A_cavi / A_tubo                # taxa de ocupação (0..1)

Dt     = math.sqrt(somma_d2)       # diâmetro do feixe (mm)
De_min = 1.3 * Dt                  # diâmetro mínimo exigido
norma  = De >= De_min              # a prescrição
prassi = K <= LIMITE_PRASSI        # a margem do ofício

# ============================================================
# 2. O DESFECHO                                          [OUT]
# ============================================================
print("Ocupação: {:.1f} %  (boa prática: máx {:.0f} %)".format(
    K * 100, LIMITE_PRASSI * 100))
print("Diâmetro do feixe Dt: {:.1f} mm".format(Dt))
print("Diâmetro mínimo do tubo (1.3 x Dt): {:.1f} mm".format(De_min))
print("Diâmetro real do tubo De: {:.1f} mm".format(De))
print("---")
if not norma:
    esito = "NÃO CONFORME"
    print("RESULTADO: NÃO CONFORME - o tubo é estreito demais,")
    print("faltam {:.1f} mm de diâmetro".format(De_min - De))
elif not prassi:
    esito = "NO LIMITE"
    print("RESULTADO: NO LIMITE - a norma passa (margem {:.1f} mm),".format(
        De - De_min))
    print("mas a ocupação supera a boa prática de {:.0f} %".format(
        LIMITE_PRASSI * 100))
else:
    esito = "CONFORME"
    print("RESULTADO: CONFORME (margem {:.1f} mm)".format(De - De_min))
