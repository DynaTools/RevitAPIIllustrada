# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Botão pyRevit "Comprimento do circuito" (Capítulo 8.1)
# Caminho: Comprimento.extension / Comprimento.tab / Medir.panel /
#          Comprimento.pushbutton / script.py
from Autodesk.Revit.DB import LocationCurve
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, script

FT_M  = 0.3048
uidoc = revit.uidoc
doc   = revit.doc

# 1) o usuário clica em todo o percurso (como no RPS)
try:
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element, "Selecione todo o percurso, depois Concluir")
except Exception:
    script.exit()                  # o usuário apertou ESC

def parametro(elem, *nomi):
    # parâmetros de família ("Bend Radius"/"Angle"): o nome segue o
    # idioma da família carregada, por isso se tentam vários nomes
    for nome in nomi:
        p = elem.LookupParameter(nome)
        if p:
            return p
    return None

# 2) soma: trechos retos (curva) + conexões (arco = raio x ângulo)
L_ft     = 0.0
n_tratti = 0
n_curve  = 0
n_muti   = 0
for r in refs:
    elem = doc.GetElement(r.ElementId)
    loc  = elem.Location
    if isinstance(loc, LocationCurve):
        L_ft += loc.Curve.Length
        n_tratti += 1
    else:
        p_raggio = parametro(elem, "Bend Radius", "Raio de curvatura")
        p_angolo = parametro(elem, "Angle", "Ângulo")
        if p_raggio and p_angolo:
            L_ft += p_raggio.AsDouble() * p_angolo.AsDouble()
        else:
            n_muti += 1            # nunca pular em silêncio
        n_curve += 1

L_mod  = L_ft * FT_M               # comprimento modelado, em metros
L_cavo = L_mod * 1.05             # + 5% de sobra

# 3) o resultado na janela de saída do pyRevit
out = script.get_output()
out.print_md("# Comprimento do circuito")
out.print_md("Trechos retos: **{}**  -  conexões: **{}**".format(n_tratti, n_curve))
if n_muti:
    out.print_md("**ATENÇÃO**: {} conexões sem parâmetros, "
                 "não somadas.".format(n_muti))
out.print_md("Comprimento modelado (3D): **{:.2f} m**".format(L_mod))
out.print_md("Com a sobra de 5%: **{:.2f} m**".format(L_cavo))
