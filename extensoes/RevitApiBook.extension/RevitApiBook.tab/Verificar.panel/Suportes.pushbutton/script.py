# -*- coding: utf-8 -*-
"""Suportes — verificação da suportação de uma eletrocalha.

Clique na eletrocalha  ->  janela dos cabos  ->  mesma conta dos Passos 1-4
(peso por metro, carga no suporte, número de suportes)  ->  a eletrocalha
fica VERDE se conforme, VERMELHA se não, e uma linha de resumo com o id
clicável aparece na janela de saída do pyRevit.

Faixas:  [PY] Python puro  [REVIT] Revit API  [ENG] dados e fórmulas  [OUT] console
"""

import os
import math

from pyrevit import revit, script, forms
from pyrevit import DB

from System.Windows.Controls import DockPanel, Dock, TextBlock, TextBox
from System.Windows import Thickness, HorizontalAlignment, VerticalAlignment

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException


# ======================================================================
#  print  cap-7-1-cod6a
#  1. CATÁLOGO E DADOS DE PROJETO ............................... [ENG]
# ======================================================================
PESO_PASSERELLA = 5.00       # kg/m  peso próprio (ficha técnica do perfil)
INTERASSE       = 1.50       # m     espaçamento de projeto
CAMPATA_MAX     = 2.00       # m     vão máximo da eletrocalha (catálogo)
PORTATA_N       = 1500.0     # N     capacidade do suporte 41/600 (CEI EN 61537)
G               = 9.81       # m/s^2 aceleração da gravidade

PORTATA_KG = PORTATA_N / G   # ~152.9 kg equivalentes

# O catálogo não é pedido ao usuário: vem junto com o script. Dez formações
# FG16OR16 com o peso por metro (kg/m, das fichas técnicas) e uma quantidade
# inicial. As três primeiras reproduzem a EC-01 do capítulo (6 / 10 / 24).
CATALOGO = [
    #  nome                peso   quantidade inicial
    (u"FG16OR16 4G95",     4.10,  6),
    (u"FG16OR16 5G16",     1.35,  10),
    (u"FG16OR16 3G2.5",    0.18,  24),
    (u"FG16OR16 4G70",     3.30,  0),
    (u"FG16OR16 4G50",     2.55,  0),
    (u"FG16OR16 4G25",     1.55,  0),
    (u"FG16OR16 5G10",     0.90,  0),
    (u"FG16OR16 5G6",      0.55,  0),
    (u"FG16OR16 5G2.5",    0.28,  0),
    (u"FG16OR16 3G4",      0.30,  0),
]


# ======================================================================
#  print  cap-7-1-cod6b
#  2. A JANELA DOS CABOS ........................................ [PY]
# ======================================================================
class SuportesWindow(forms.WPFWindow):
    """Preenche a casca XAML: uma linha (nome + caixa) para cada cabo."""

    def __init__(self, xaml, catalogo):
        forms.WPFWindow.__init__(self, xaml)
        self.caselle = {}
        self.quantita = None                       # None até apertar Verificar
        for nome, _peso, default in catalogo:
            riga = DockPanel(Margin=Thickness(0, 0, 0, 6))
            casella = TextBox(Width=56, Text=str(default),
                              HorizontalContentAlignment=HorizontalAlignment.Right)
            DockPanel.SetDock(casella, Dock.Right)  # a caixa à direita
            etichetta = TextBlock(Text=nome, VerticalAlignment=VerticalAlignment.Center)
            riga.Children.Add(casella)
            riga.Children.Add(etichetta)            # o rótulo ocupa o resto
            self.righe.Children.Add(riga)
            self.caselle[nome] = casella

    def verifica_click(self, sender, args):
        # recolhe as quantidades digitadas e fecha a janela
        self.quantita = {}
        for nome, casella in self.caselle.items():
            try:
                self.quantita[nome] = int(casella.Text)
            except ValueError:
                self.quantita[nome] = 0
        self.Close()


# ======================================================================
#  3. FUNÇÕES DE APOIO REVIT .................................... [REVIT]
# ======================================================================
def in_metri(lung_ft):
    """Converte um comprimento dos pés internos para metros (Lei II)."""
    try:
        return DB.UnitUtils.ConvertFromInternalUnits(lung_ft, DB.UnitTypeId.Meters)
    except Exception:
        return lung_ft * 0.3048


def id_riempimento_pieno(doc):
    """Id do padrão de preenchimento 'sólido', para pintar a superfície."""
    for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        if fp.GetFillPattern().IsSolidFill:
            return fp.Id
    return DB.ElementId.InvalidElementId


def colora(vista, elemento, colore):
    """Pinta superfície e bordas do elemento na vista ativa (override)."""
    ogs = DB.OverrideGraphicSettings()
    solido = id_riempimento_pieno(vista.Document)
    ogs.SetProjectionLineColor(colore)
    ogs.SetSurfaceForegroundPatternColor(colore)
    ogs.SetCutForegroundPatternColor(colore)
    if solido != DB.ElementId.InvalidElementId:
        ogs.SetSurfaceForegroundPatternVisible(True)
        ogs.SetSurfaceForegroundPatternId(solido)
        ogs.SetCutForegroundPatternVisible(True)
        ogs.SetCutForegroundPatternId(solido)
    vista.SetElementOverrides(elemento.Id, ogs)


# ======================================================================
#  print  cap-7-1-cod6c
#  4. O FLUXO: CLIQUE, CÁLCULO, COR ............. [REVIT] / [ENG] / [OUT]
# ======================================================================
doc = revit.doc
uidoc = revit.uidoc
out = script.get_output()

VERDE = DB.Color(46, 164, 79)
ROSSO = DB.Color(200, 44, 44)

# 4.1  clique na eletrocalha e leitura do comprimento .......... [REVIT]
try:
    rif = uidoc.Selection.PickObject(ObjectType.Element, "Selecione a eletrocalha")
except OperationCanceledException:
    script.exit()

tratto = doc.GetElement(rif.ElementId)
curva = getattr(tratto.Location, "Curve", None)
if curva is None:
    forms.alert("O elemento selecionado não tem comprimento (Location.Curve).",
                title="Suportes", exitscript=True)
L = in_metri(curva.Length)

# 4.2  a janela dos cabos ...................................... [PY]
XAML = os.path.join(os.path.dirname(__file__), "SuportesWindow.xaml")
finestra = SuportesWindow(XAML, CATALOGO)
finestra.ShowDialog()
if finestra.quantita is None:
    script.exit()                                   # fechada sem Verificar

# 4.3  a mesma conta dos Passos 1-4 ........................... [ENG]
pesi = dict((nome, peso) for nome, peso, _ in CATALOGO)
peso_cavi = sum(pesi[nome] * finestra.quantita.get(nome, 0) for nome in pesi)
w = PESO_PASSERELLA + peso_cavi                     # kg/m
F = w * INTERASSE                                   # kg no suporte interno
i_mensola = PORTATA_KG / w                          # m, limite do braço
i_max = min(i_mensola, CAMPATA_MAX)                 # m, limite do sistema
campate = int(math.ceil(L / INTERASSE))
N = campate + 1                                     # N = ceil(L/i) + 1

conforme = (F <= PORTATA_KG) and (INTERASSE <= i_max)

# 4.4  o resultado VISTO: pinta a eletrocalha no modelo ....... [REVIT]
colore = VERDE if conforme else ROSSO
with revit.Transaction("Suportes"):
    colora(doc.ActiveView, tratto, colore)

# 4.5  resumo com id clicável (linkify) ....................... [OUT]
esito = "CONFORME" if conforme else "NÃO CONFORME"
out.print_md("# Suportes &mdash; {0}".format(esito))
out.print_md("Eletrocalha: {0}".format(out.linkify(tratto.Id)))
out.print_md("- Comprimento  L = **{0:.2f} m**".format(L))
out.print_md("- Peso por metro  w = **{:.2f} kg/m**  (eletrocalha {:.2f} + cabos {:.2f})".format(w, PESO_PASSERELLA, peso_cavi))
out.print_md("- Carga no suporte  F = w x i = **{:.1f} kg**   (máx {:.1f} kg)".format(F, PORTATA_KG))
out.print_md("- Espaçamento máx  i_max = min({:.2f}; {:.2f}) = **{:.2f} m**".format(i_mensola, CAMPATA_MAX, i_max))
out.print_md("- Suportes  N = ceil({:.2f} / {:.2f}) + 1 = **{}**".format(L, INTERASSE, N))
