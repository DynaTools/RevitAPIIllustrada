# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.2.2  |  Capítulo 8.2 - A taxa de ocupação dos eletrodutos
# Seção: Passo 4 - a lista dos cabos lida do modelo

# ============================================================
# 0. RECOMEÇO                                   [PY] + [REVIT]
#    bloco autônomo: import, documento e clique no eletroduto
# ============================================================
import math
from Autodesk.Revit.UI.Selection import ObjectType

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

# ============================================================
# 1. O CATÁLOGO                                          [ENG]
#    seção -> diâmetro externo (mm), das fichas técnicas.
#    É um dado de catálogo: vive no código, não no modelo.
#    O nome é também o do parâmetro de projeto: a chave
#    com que o trecho declara quantos cabos passam por ele.
#    FG16R16 = cabo UNIPOLAR 0,6/1 kV (um só condutor); o
#    multipolar seria FG16OR16. Numa prumada de trafo se
#    lançam unipolares, um por fase, em paralelo se preciso.
#    Diâmetro externo MÁXIMO, tabela CEI-UNEL 35318.
# ============================================================
CATALOGO = [
    ("FG16R16 16",  11.4),
    ("FG16R16 25",  13.2),
    ("FG16R16 35",  14.6),
    ("FG16R16 50",  16.4),
    ("FG16R16 70",  17.3),
    ("FG16R16 95",  20.4),
    ("FG16R16 120", 22.4),
    ("FG16R16 150", 24.8),
    ("FG16R16 185", 27.2),
    ("FG16R16 240", 30.4),
    ("FG16R16 300", 33.0),
]

# ============================================================
# 2. PASSO 4, A LISTA                          [REVIT] + [ENG]
#    quantos cabos passam de verdade, diz o parâmetro de mesmo
#    nome; quem vale zero não entra na conta nem suja o console
# ============================================================
A_cavi   = 0.0    # soma das áreas dos cabos (mm^2)
somma_d2 = 0.0    # soma dos d^2 (servirá para o feixe)
n_cavi   = 0

for nome, d in CATALOGO:
    par = conduit.LookupParameter(nome)
    if par is None:
        continue                   # parâmetro ausente neste trecho
    q = par.AsInteger()
    if q == 0:
        continue                   # declarado, mas aqui não passa
    area = math.pi / 4.0 * d**2 * q
    A_cavi   += area
    somma_d2 += d**2 * q
    n_cavi   += q
    print("{:>15}: d={:.1f} mm  x{}  ->  {:.0f} mm2".format(
        nome, d, q, area))

# ============================================================
# 3. O RESULTADO                                         [OUT]
# ============================================================
print("---")
if n_cavi == 0:
    print("Este trecho não declara nenhum cabo.")
    print("Confira se os nomes do CATALOGO são idênticos")
    print("aos dos parâmetros de projeto, espaços incluídos.")
else:
    print("Cabos no total: {}".format(n_cavi))
    print("Área ocupada pelos cabos: {:.0f} mm2".format(A_cavi))
