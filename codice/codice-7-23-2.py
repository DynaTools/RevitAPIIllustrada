# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.23.2  |  Capitolo 7.23 - Il baricentro di un insieme di elementi
# Sezione: Passo 4 - posizione e carico dal modello reale

# PASSO 4: posizione e peso letti dagli elementi reali del modello
def posizione(el):
    loc = el.Location
    if hasattr(loc, "Point"):              # LocationPoint (prese, apparecchi)
        return loc.Point
    k = loc.Curve                          # LocationCurve (tubi, passerelle)
    return k.Evaluate(0.5, True)           # punto medio della curva

def peso(el, nome_param, default=1.0):
    p = el.LookupParameter(nome_param)     # es. "Carico apparente" (kW), o portata
    return p.AsDouble() if p else default

# raccolgo le utenze (qui: apparecchi elettrici) e costruisco le coppie
elementi = (FilteredElementCollector(doc)
            .OfCategory(BuiltInCategory.OST_ElectricalFixtures)
            .WhereElementIsNotElementType()
            .ToElements())

coppie = [(posizione(e), peso(e, "Carico apparente")) for e in elementi]
G = baricentro(coppie)                     # in piedi -> converto in metri

print("Utenze trovate: {}".format(len(coppie)))
print("Baricentro pesato: ({:.2f}, {:.2f}) m".format(G.X*FT_M, G.Y*FT_M))
