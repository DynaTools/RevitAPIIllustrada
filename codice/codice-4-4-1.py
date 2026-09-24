# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.4.1  |  Capítulo 4.4 - Os erros que aparecem no projeto real
# Seção: No parâmetro, quatro silêncios

from Autodesk.Revit.DB import StorageType, BuiltInParameter

def set_testo(el, bip, value):
    p = el.get_Parameter(bip)            # 4) por BuiltInParameter, não por nome
    if p is None:                        # 1) não existe neste elemento
        return "ausente"
    if p.IsReadOnly:                     # 2) somente leitura
        return "bloqueado"
    if p.StorageType != StorageType.String:  # 3) tipo errado
        return "tipo incompatível"
    p.Set(value)                         # (dentro de uma Transaction)
    return "ok"

# em vez de LookupParameter("Comments"):
set_testo(el, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, "Verificado")
