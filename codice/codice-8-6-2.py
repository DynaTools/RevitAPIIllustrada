# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.6.2  |  Capítulo 8.6 - A cobertura Wi-Fi
# Seção: Passo 2 - o veredito no modelo

# ============================================================
# 0. RECOMEÇO                                            [PY]
#    mesma sessão: a lista risultati está na memória,
#    com o probe, o nível em dBm e o veredito
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector,
    BuiltInParameter, Transaction, OverrideGraphicSettings,
    Color, FillPatternElement)

COLORI = {"verde":    Color(0, 150, 0),
          "amarelo":  Color(235, 170, 0),
          "vermelho": Color(200, 30, 30)}

# ============================================================
# 1. O VEREDITO NO MODELO                     [REVIT] + [OUT]
#    o probe se colore na vista ativa e os dBm vão para
#    os Comentários, legíveis em qualquer tabela
# ============================================================
riempimento = None
for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if fp.GetFillPattern().IsSolidFill:
        riempimento = fp.Id
        break

vista = doc.ActiveView
t = Transaction(doc, "Sinal Wi-Fi nos probes")
t.Start()
for pr, rssi, verdetto in risultati:
    col = COLORI[verdetto]
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(col)
    if riempimento is not None:
        ogs.SetSurfaceForegroundPatternId(riempimento)
        ogs.SetSurfaceForegroundPatternColor(col)
    vista.SetElementOverrides(pr.Id, ogs)
    par = pr.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if par is not None:
        par.Set("Wi-Fi {:.0f} dBm ({})".format(rssi, verdetto))
t.Commit()

print("Probes coloridos e comentados: {}".format(len(risultati)))
