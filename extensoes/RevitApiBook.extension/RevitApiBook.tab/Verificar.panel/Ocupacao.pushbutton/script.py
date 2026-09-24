# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Botão pyRevit "Ocupação" (Capítulo 8.2)
# Caminho: RevitApiBook.extension / RevitApiBook.tab /
#          Verificar.panel / Ocupacao.pushbutton / script.py
import math

from Autodesk.Revit.DB import (BuiltInParameter, Color,
                               FilteredElementCollector, FillPatternElement,
                               OverrideGraphicSettings, Transaction)
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, script

FT_MM = 304.8                      # 1 pé = 304.8 mm
LIMITE_PRASSI = 0.40               # boa prática: 40 % de ocupação

# catálogo: seção -> diâmetro externo máximo (mm),
# tabela CEI-UNEL 35318, cabos FG16R16 0,6/1 kV unipolares
CATALOGO = [("FG16R16 16", 11.4), ("FG16R16 25", 13.2),
            ("FG16R16 35", 14.6), ("FG16R16 50", 16.4),
            ("FG16R16 70", 17.3), ("FG16R16 95", 20.4),
            ("FG16R16 120", 22.4), ("FG16R16 150", 24.8),
            ("FG16R16 185", 27.2), ("FG16R16 240", 30.4),
            ("FG16R16 300", 33.0)]

COLORI = {"CONFORME":     (Color(0, 150, 60),  "verde"),
          "NO LIMITE":    (Color(235, 160, 0), "amarelo"),
          "NÃO CONFORME": (Color(200, 30, 30), "vermelho")}

uidoc = revit.uidoc
doc = revit.doc
out = script.get_output()

# 1) o clique no eletroduto
try:
    ref = uidoc.Selection.PickObject(ObjectType.Element,
                                     "Selecione o eletroduto")
except Exception:
    script.exit()                  # o usuário apertou ESC

conduit = doc.GetElement(ref.ElementId)

p_int = conduit.get_Parameter(BuiltInParameter.RBS_CONDUIT_INNER_DIAM_PARAM)
if p_int is None:
    out.print_md("# Taxa de ocupação do eletroduto")
    out.print_md("O elemento escolhido **não é um eletroduto**: "
                 "não tem diâmetro interno.")
    script.exit()

De = p_int.AsDouble() * FT_MM
A_tubo = math.pi / 4.0 * De ** 2

# 2) a lista dos cabos, lida dos parâmetros de projeto
righe = []
A_cavi = 0.0
somma_d2 = 0.0
n_cavi = 0
for nome, d in CATALOGO:
    par = conduit.LookupParameter(nome)
    q = par.AsInteger() if par is not None else 0
    if q == 0:
        continue                   # ausente, ou declarado mas não passa
    A_cavi += math.pi / 4.0 * d ** 2 * q
    somma_d2 += d ** 2 * q
    n_cavi += q
    righe.append("| {} | {:.1f} | {} |".format(nome, d, q))

if n_cavi == 0:
    out.print_md("# Taxa de ocupação do eletroduto")
    out.print_md("Este trecho **não declara nenhum cabo**. "
                 "Preencha as quantidades na paleta Propriedades, "
                 "depois clique de novo no botão.")
    script.exit()

# 3) o cálculo e os dois limites
#    K = Dt^2 / De^2, então De >= 1,3 Dt equivale a K <= 59,2 %:
#    sozinha, a norma é mais permissiva que a boa prática
K = A_cavi / A_tubo
Dt = math.sqrt(somma_d2)
De_min = 1.3 * Dt
norma = De >= De_min
prassi = K <= LIMITE_PRASSI

if not norma:
    esito = "NÃO CONFORME"
elif not prassi:
    esito = "NO LIMITE"
else:
    esito = "CONFORME"

colore, nome_colore = COLORI[esito]

# 4) o resultado no modelo (Lei I: em Transaction)
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

t = Transaction(doc, "Taxa de ocupação do eletroduto")
t.Start()
doc.ActiveView.SetElementOverrides(conduit.Id, ogs)
t.Commit()

# 5) o relatório na janela de saída
out.print_md("# Taxa de ocupação do eletroduto")
out.print_md("\n".join(["| cabo | d (mm) | q |", "|---|---:|---:|"] + righe))
out.print_md("Diâmetro interno **De = {:.1f} mm**, "
             "área do tubo **{:.0f} mm2**".format(De, A_tubo))
out.print_md("Área ocupada **{:.0f} mm2** por **{}** cabos".format(
    A_cavi, n_cavi))
out.print_md("Ocupação **{:.1f} %** (boa prática: máx {:.0f} %)".format(
    K * 100, LIMITE_PRASSI * 100))
out.print_md("Feixe **Dt = {:.1f} mm**, mínimo CEI 64-8 "
             "**1,3 x Dt = {:.1f} mm**".format(Dt, De_min))
out.print_md("## {}".format(esito))
if not norma:
    out.print_md("O tubo é estreito demais: faltam "
                 "**{:.1f} mm** de diâmetro.".format(De_min - De))
elif not prassi:
    out.print_md("A norma passa com **{:.1f} mm** de margem, mas a "
                 "ocupação supera os {:.0f} % da boa prática.".format(
                     De - De_min, LIMITE_PRASSI * 100))
else:
    out.print_md("Margem sobre o mínimo da norma: **{:.1f} mm**.".format(
        De - De_min))
out.print_md("O eletroduto foi colorido de **{}** "
             "na vista ativa.".format(nome_colore))
