# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.2.2  |  Capítulo 4.2 - O método Spy → Replicar → Generalizar
# Seção: Generalizar, substituir o específico pela variável

# ANTES (Replicar): um elemento, valor fixado
target = uidoc.Selection.GetElementIds()
el = doc.GetElement(list(target)[0])

t = Transaction(doc, "Replicar - teste")
t.Start()
el.LookupParameter("Commenti").Set("TESTE-REPLICAR")
t.Commit()
