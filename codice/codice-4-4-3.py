# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.4.3  |  Capítulo 4.4 - Os erros que aparecem no projeto real
# Seção: No documento, vínculos e worksharing

from Autodesk.Revit.DB import WorksharingUtils, CheckoutStatus

if el.Document.IsLinked:                 # o elemento vem de um vínculo
    print("Elemento de um vínculo, somente leitura; pulando.")

st = WorksharingUtils.GetCheckoutStatus(doc, el.Id)
if st == CheckoutStatus.OwnedByOtherUser:    # o dono é outra pessoa
    print("O elemento pertence a outro usuário; pulando.")
