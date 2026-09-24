# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.2.3  |  Capítulo 4.2 - O método Spy → Replicar → Generalizar
# Seção: Generalizar, substituir o específico pela variável

# DEPOIS (Generalizar): todos os elementos, valor em variável
value = "Verificado"                        # o fixado virou input
targets = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()         # a seleção virou pergunta

t = Transaction(doc, "Preencher Comentários - paredes")
t.Start()
for el in targets:                            # o "um" virou o for
    p = el.LookupParameter("Comentários")
    if p and not p.IsReadOnly:              # a borda que o bloco exige
        p.Set(value)
t.Commit()
