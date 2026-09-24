# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.2.5  |  Capítulo 4.2 - O método Spy → Replicar → Generalizar
# Seção: Um caso completo, de ponta a ponta

el = doc.GetElement(list(uidoc.Selection.GetElementIds())[0])

t = Transaction(doc, "COD - teste em um quadro")
t.Start()
el.LookupParameter("COD_LOCALE").Set("P02-EL")  # fixado!
t.Commit()
