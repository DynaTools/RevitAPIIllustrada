# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.3.1  |  Capítulo 7.3 - A WBS, o modelo classificado
# Seção: Passo 1 - os parâmetros compartilhados, criados pela API

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    seis parâmetros de texto, de instância, nas categorias MEP
# ============================================================
import os
from Autodesk.Revit.DB import (BuiltInCategory, Transaction,
    ExternalDefinitionCreationOptions, SpecTypeId, GroupTypeId)

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
app   = doc.Application

PARAMETRI = ["WBS_s01", "WBS_s02", "WBS_s03",
             "WBS_t01", "WBS_t02", "WBS_CODICE"]
CATEGORIE = [BuiltInCategory.OST_Conduit,
             BuiltInCategory.OST_ConduitFitting,
             BuiltInCategory.OST_CableTray,
             BuiltInCategory.OST_CableTrayFitting,
             BuiltInCategory.OST_ElectricalEquipment,
             BuiltInCategory.OST_ElectricalFixtures,
             BuiltInCategory.OST_LightingFixtures,
             BuiltInCategory.OST_DataDevices,
             BuiltInCategory.OST_FireAlarmDevices,
             BuiltInCategory.OST_DuctCurves,
             BuiltInCategory.OST_PipeCurves]

# ============================================================
# 1. O ARQUIVO DE PARÂMETROS COMPARTILHADOS           [REVIT]
#    se não existe, nasce aqui, com o cabeçalho mínimo
# ============================================================
percorso = os.path.join(os.path.expanduser("~"), "Documents",
                        "wbs_condivisi.txt")
if not os.path.exists(percorso):
    with open(percorso, "w", encoding="utf-16") as f:
        f.write("# This is a Revit shared parameter file.\n"
                "*META\tVERSION\tMINVERSION\n"
                "META\t2\t1\n"
                "*GROUP\tID\tNAME\n"
                "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\t"
                "GROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n")
app.SharedParametersFilename = percorso
sfile = app.OpenSharedParameterFile()

gruppo = sfile.Groups.get_Item("WBS")
if gruppo is None:
    gruppo = sfile.Groups.Create("WBS")

# ============================================================
# 2. DEFINIÇÃO E VÍNCULO, EM TRANSAÇÃO        [REVIT] + [OUT]
#    a definição vive no arquivo; o vínculo (instância, nas
#    nossas categorias) vive no modelo
# ============================================================
cats = app.Create.NewCategorySet()
for bic in CATEGORIE:
    cats.Insert(doc.Settings.Categories.get_Item(bic))
legame = app.Create.NewInstanceBinding(cats)

creati, legati = 0, 0
t = Transaction(doc, "Parâmetros WBS")
t.Start()
for nome in PARAMETRI:
    defn = gruppo.Definitions.get_Item(nome)
    if defn is None:
        opzioni = ExternalDefinitionCreationOptions(
            nome, SpecTypeId.String.Text)
        defn = gruppo.Definitions.Create(opzioni)
        creati += 1
    if not doc.ParameterBindings.Insert(defn, legame, GroupTypeId.Data):
        doc.ParameterBindings.ReInsert(defn, legame, GroupTypeId.Data)
    legati += 1
t.Commit()

print("Arquivo de compartilhados: {}".format(percorso))
print("Definições criadas: {}".format(creati))
print("Parâmetros vinculados (instância, {} categorias): {}".format(
    len(CATEGORIE), legati))
