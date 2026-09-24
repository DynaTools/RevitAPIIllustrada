# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Pulsante pyRevit "Lunghezza circuito" (Capitolo 7.1)
# Percorso: Lunghezza.extension / Lunghezza.tab / Misura.panel /
#           Lunghezza.pushbutton / script.py
from Autodesk.Revit.DB import LocationCurve
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit, script

FT_M  = 0.3048
uidoc = revit.uidoc
doc   = revit.doc

# 1) l'utente clicca tutto il percorso (come nell'RPS)
try:
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element, "Seleziona tutto il percorso, poi Finish")
except Exception:
    script.exit()                  # l'utente ha premuto ESC

# 2) somma: tratti dritti (curva) + raccordi (arco = raggio x angolo)
L_ft     = 0.0
n_tratti = 0
n_curve  = 0
for r in refs:
    elem = doc.GetElement(r.ElementId)
    loc  = elem.Location
    if isinstance(loc, LocationCurve):
        L_ft += loc.Curve.Length
        n_tratti += 1
    else:
        p_raggio = elem.LookupParameter("Bend Radius")
        p_angolo = elem.LookupParameter("Angle")
        if p_raggio and p_angolo:
            L_ft += p_raggio.AsDouble() * p_angolo.AsDouble()
        n_curve += 1

L_mod  = L_ft * FT_M               # lunghezza modellata, in metri
L_cavo = L_mod * 1.05             # + 5% di sfrido

# 3) l'esito nella finestra di output di pyRevit
out = script.get_output()
out.print_md("# Lunghezza del circuito")
out.print_md("Tratti dritti: **{}**  -  raccordi: **{}**".format(n_tratti, n_curve))
out.print_md("Lunghezza modellata (3D): **{:.2f} m**".format(L_mod))
out.print_md("Con lo sfrido del 5%: **{:.2f} m**".format(L_cavo))
