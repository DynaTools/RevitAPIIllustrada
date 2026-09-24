# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.25.2  |  Capitolo 7.25 - La distanza di sicurezza da una sorgente di rumore
# Sezione: Passi 3--4 - i ricettori e il verdetto

# PASSO 3: misura i ricettori e calcola il livello a ciascuno
# (i ricettori sono elementi del modello: finestre, punti di confine...)
ricettori = (FilteredElementCollector(doc)
             .OfCategory(BuiltInCategory.OST_Windows)
             .WhereElementIsNotElementType()
             .ToElements())

print("Ricettore        dist (m)   Lp (dB)   esito")
print("-" * 46)
violazioni = 0
for r in ricettori:
    p = r.Location.Point if r.Location else None
    if p is None:
        continue
    d = origine.DistanceTo(p) * FT_M       # distanza in metri
    livello = Lp(LW, d)
    ok = livello <= LIMITE
    if not ok:
        violazioni += 1
    print("{:<14} {:8.1f}  {:8.1f}   {}".format(
        r.Name, d, livello, "OK" if ok else "SUPERA"))

# PASSO 4: verdetto
print("-" * 46)
if violazioni == 0:
    print("ESITO: CONFORME - nessun ricettore oltre il limite")
else:
    print("ESITO: NON CONFORME - {} ricettore/i oltre {:.0f} dB(A)".format(
        violazioni, LIMITE))
