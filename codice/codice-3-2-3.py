# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.2.3  |  Capítulo 3.2 - O primeiro script
# Seção: Dissecando, linha por linha

total = 0
walls = FilteredElementCollector(doc)\
    .OfClass(Wall)\
    .WhereElementIsNotElementType()      # LEI III

for w in walls:                        # R7
    curve  = w.Location.Curve            # R1 - dominó
    total += curve.Length                # R1 - em pés! (LEI II)

metri = UnitUtils.ConvertFromInternalUnits(total, UnitTypeId.Meters)
print(round(metri, 2), "m")
