# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.3.6  |  Capítulo 8.3 - A suportação
# Seção: No pyRevit - o botão "Staffaggio"
#
# Clique na eletrocalha -> janela dos cabos -> mesma
# conta dos Passos 1-4 -> a eletrocalha fica VERDE se
# conforme, VERMELHA se não, com um resumo clicável
# na janela de saída do pyRevit.
#
# NB. Versão diagramada para o livro (linhas curtas): o
# código completo, pronto para instalar, está no .zip.

import os
import math

from pyrevit import revit, script, forms
from pyrevit import DB
from System.Windows.Controls import (
    DockPanel, Dock, TextBlock, TextBox)
from System.Windows import (
    Thickness, HorizontalAlignment, VerticalAlignment)
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import (
    OperationCanceledException)

# ==========================================================
#  1. CATÁLOGO E DADOS DE PROJETO                     [ENG]
# ==========================================================
PESO_PASSERELLA = 5.00    # kg/m, peso próprio do perfil
INTERASSE       = 1.50    # m, espaçamento de projeto
CAMPATA_MAX     = 2.00    # m, vão máximo
PORTATA_N       = 1500.0  # N, 41/600 (CEI EN 61537)
G               = 9.81    # m/s^2

PORTATA_KG = PORTATA_N / G         # ~152.9 kg eq.

# dez formações, peso por metro (kg/m) e quantidade
# inicial; as três primeiras são a EC-01 (6 / 10 / 24)
CATALOGO = [
    # nome              peso   quantidade
    (u"FG16OR16 4G95",  4.10,  6),
    (u"FG16OR16 5G16",  1.35,  10),
    (u"FG16OR16 3G2.5", 0.18,  24),
    (u"FG16OR16 4G70",  3.30,  0),
    (u"FG16OR16 4G50",  2.55,  0),
    (u"FG16OR16 4G25",  1.55,  0),
    (u"FG16OR16 5G10",  0.90,  0),
    (u"FG16OR16 5G6",   0.55,  0),
    (u"FG16OR16 5G2.5", 0.28,  0),
    (u"FG16OR16 3G4",   0.30,  0),
]

# ==========================================================
#  2. A JANELA DOS CABOS                              [PY]
# ==========================================================
class StaffaggioWindow(forms.WPFWindow):
    # preenche a casca XAML: uma linha por cabo

    def __init__(self, xaml, catalogo):
        forms.WPFWindow.__init__(self, xaml)
        self.caselle = {}
        self.quantita = None      # None até Verifica
        for nome, _peso, default in catalogo:
            riga = DockPanel(
                Margin=Thickness(0, 0, 0, 6))
            casella = TextBox(
                Width=56, Text=str(default),
                HorizontalContentAlignment=
                HorizontalAlignment.Right)
            DockPanel.SetDock(casella, Dock.Right)
            etichetta = TextBlock(
                Text=nome,
                VerticalAlignment=
                VerticalAlignment.Center)
            riga.Children.Add(casella)
            riga.Children.Add(etichetta)
            self.righe.Children.Add(riga)
            self.caselle[nome] = casella

    def verifica_click(self, sender, args):
        # recolhe as quantidades e fecha a janela
        self.quantita = {}
        for nome, casella in self.caselle.items():
            try:
                self.quantita[nome] = int(casella.Text)
            except ValueError:
                self.quantita[nome] = 0
        self.Close()

# ==========================================================
#  3. FUNÇÕES DE APOIO REVIT                         [REVIT]
# ==========================================================
def in_metri(lung_ft):
    # dos pés internos aos metros (Lei II)
    try:
        return DB.UnitUtils.ConvertFromInternalUnits(
            lung_ft, DB.UnitTypeId.Meters)
    except Exception:
        return lung_ft * 0.3048


def id_riempimento_pieno(doc):
    # id do padrão de preenchimento "sólido"
    coll = DB.FilteredElementCollector(doc)
    for fp in coll.OfClass(DB.FillPatternElement):
        if fp.GetFillPattern().IsSolidFill:
            return fp.Id
    return DB.ElementId.InvalidElementId


def colora(vista, elemento, colore):
    # pinta superfície e bordas na vista ativa
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

# ==========================================================
#  4. O FLUXO: CLIQUE, CÁLCULO, COR       [REVIT/ENG/OUT]
# ==========================================================
doc   = revit.doc
uidoc = revit.uidoc
out   = script.get_output()

VERDE = DB.Color(46, 164, 79)
ROSSO = DB.Color(200, 44, 44)

# 4.1  clique na eletrocalha e comprimento    [REVIT]
try:
    rif = uidoc.Selection.PickObject(
        ObjectType.Element, "Selecione a eletrocalha")
except OperationCanceledException:
    script.exit()

tratto = doc.GetElement(rif.ElementId)
curva  = getattr(tratto.Location, "Curve", None)
if curva is None:
    forms.alert("A seleção não tem um comprimento.",
                title="Staffaggio", exitscript=True)
L = in_metri(curva.Length)

# 4.2  a janela dos cabos                     [PY]
qui  = os.path.dirname(__file__)
XAML = os.path.join(qui, "StaffaggioWindow.xaml")
finestra = StaffaggioWindow(XAML, CATALOGO)
finestra.ShowDialog()
if finestra.quantita is None:
    script.exit()             # fechada sem Verifica

# 4.3  a mesma conta dos Passos 1-4           [ENG]
pesi = dict((n, p) for n, p, _ in CATALOGO)
q    = finestra.quantita
peso_cavi = sum(pesi[n] * q.get(n, 0) for n in pesi)
w = PESO_PASSERELLA + peso_cavi          # kg/m
F = w * INTERASSE                        # kg, o suporte
i_mensola = PORTATA_KG / w               # m, o braço
i_max = min(i_mensola, CAMPATA_MAX)      # m, o sistema
N = int(math.ceil(L / INTERASSE)) + 1
conforme = (F <= PORTATA_KG) and (INTERASSE <= i_max)

# 4.4  o resultado VISTO: pinta a eletrocalha [REVIT]
colore = VERDE if conforme else ROSSO
with revit.Transaction("Staffaggio"):
    colora(doc.ActiveView, tratto, colore)

# 4.5  resumo com id clicável (linkify)       [OUT]
esito = "CONFORME" if conforme else "NÃO CONFORME"
out.print_md("# Staffaggio &mdash; {0}".format(esito))
out.print_md(
    "Eletrocalha: {0}".format(out.linkify(tratto.Id)))
out.print_md("- Comprimento  L = **{0:.2f} m**".format(L))
out.print_md(
    "- Peso por metro  w = **{0:.2f} kg/m**  "
    "(eletrocalha {1:.2f} + cabos {2:.2f})"
    .format(w, PESO_PASSERELLA, peso_cavi))
out.print_md(
    "- Carga no suporte  F = w x i = **{0:.1f} kg**   "
    "(capacidade {1:.1f} kg)".format(F, PORTATA_KG))
out.print_md(
    "- Espaçamento máx  i_max = min({0:.2f}; {1:.2f}) "
    "= **{2:.2f} m**"
    .format(i_mensola, CAMPATA_MAX, i_max))
out.print_md(
    "- Suportes  N = ceil({0:.2f} / {1:.2f}) + 1 = **{2}**"
    .format(L, INTERASSE, N))
