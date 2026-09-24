# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.1.3  |  Capítulo 4.1 - Transações, o contrato antes de pôr a mão
# Seção: Anatomia do contrato, do Start ao RollBack

level = FilteredElementCollector(doc).OfClass(Level).FirstElement()

length = UnitUtils.ConvertToInternalUnits(6, UnitTypeId.Meters)
                                         # R3 + LEI II - 6 m -> pés
t = Transaction(doc, "Criar parede")     # LEI I
t.Start()
line  = Line.CreateBound(XYZ(0,0,0), XYZ(length,0,0))  # R3 + R4
wall = Wall.Create(doc, line, level.Id, False)     # R3 static
t.Commit()
