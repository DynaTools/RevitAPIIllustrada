# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.7  |  Capítulo 6.1 - As primitivas geométricas
# Seção: O bounding box orientado (OBB) - Transform

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB import XYZ

FT_M = 0.3048

# O OBB pede uma FamilyInstance (um quadro, uma bomba): a EC-01,
# que é uma MEPCurve, não tem GetTransform. Clique numa instância.
ref = uidoc.Selection.PickObject(ObjectType.Element)
fi  = doc.GetElement(ref.ElementId)       # uma FamilyInstance
tf  = fi.GetTransform()

# Origem e eixos locais em coordenadas globais
origin = tf.Origin
u_hat  = tf.BasisX                        # eixo longitudinal (normalizado)
v_hat  = tf.BasisY                        # eixo transversal
w_hat  = tf.BasisZ                        # eixo vertical

print("Origem: ({:.3f}, {:.3f}, {:.3f}) m".format(
    origin.X*FT_M, origin.Y*FT_M, origin.Z*FT_M))
print("u: ({:.3f}, {:.3f}, {:.3f})".format(u_hat.X, u_hat.Y, u_hat.Z))
print("v: ({:.3f}, {:.3f}, {:.3f})".format(v_hat.X, v_hat.Y, v_hat.Z))
print("w: ({:.3f}, {:.3f}, {:.3f})".format(w_hat.X, w_hat.Y, w_hat.Z))
