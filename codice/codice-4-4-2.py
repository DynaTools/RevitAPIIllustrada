# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.4.2  |  Capítulo 4.4 - Os erros que aparecem no projeto real
# Seção: Nas unidades, o pé escondido

from Autodesk.Revit.DB import UnitUtils, UnitTypeId

largh_ft = p.AsDouble()                                  # PÉS (interno)
largh_mm = UnitUtils.ConvertFromInternalUnits(largh_ft, UnitTypeId.Millimeters)
