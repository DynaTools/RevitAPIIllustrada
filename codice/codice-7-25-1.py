# -*- coding: utf-8 -*-
# Revit API Illustrata in Python - Paulo Giavoni
# Codice 7.25.1  |  Capitolo 7.25 - La distanza di sicurezza da una sorgente di rumore
# Sezione: Passi 1--2 - la sorgente e la distanza di sicurezza

import math
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory

FT_M = 0.3048                      # 1 piede = 0.3048 m

doc = __revit__.ActiveUIDocument.Document

# livello di pressione sonora a distanza d (m) da una sorgente puntiforme
def Lp(Lw, d):
    return Lw - 20.0 * math.log10(d) - 11.0   # campo libero sferico

# distanza di sicurezza: dove Lp scende al limite (formula invertita)
def distanza_sicurezza(Lw, limite):
    return 10.0 ** ((Lw - 11.0 - limite) / 20.0)

# PASSO 1: individua la sorgente (prima apparecchiatura meccanica)
sorgente = (FilteredElementCollector(doc)
            .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
            .WhereElementIsNotElementType()
            .FirstElement())

origine = sorgente.Location.Point  # posizione della macchina (piedi)

LW    = 85.0                       # potenza sonora della macchina (dB, da targa)
LIMITE = 55.0                      # limite diurno zona residenziale (dB(A))

# PASSO 2: la distanza di sicurezza
d_sic = distanza_sicurezza(LW, LIMITE)

print("Sorgente: {}".format(sorgente.Name))
print("Potenza sonora Lw: {:.0f} dB".format(LW))
print("Limite di immissione: {:.0f} dB(A)".format(LIMITE))
print("Distanza di sicurezza: {:.1f} m".format(d_sic))
print("Verifica Lp a {:.1f} m: {:.1f} dB".format(d_sic, Lp(LW, d_sic)))
