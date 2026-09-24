# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.2.6  |  Capítulo 4.2 - O método Spy → Replicar → Generalizar
# Seção: Um caso completo, de ponta a ponta

panels = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_ElectricalEquipment)\
    .WhereElementIsNotElementType()         # LEI III

t = Transaction(doc, "COD_LOCALE - quadros elétricos")
t.Start()
for q in panels:                           # R7
    level = doc.GetElement(q.LevelId)       # dominó via Id
    if not level:                           # quadro sem nível: pula
        continue
    code = level.Name[:3] + "-EL"         # P02-EL, P03-EL...
    p = q.LookupParameter("COD_LOCALE")
    if p and not p.IsReadOnly:
        p.Set(code)
t.Commit()
