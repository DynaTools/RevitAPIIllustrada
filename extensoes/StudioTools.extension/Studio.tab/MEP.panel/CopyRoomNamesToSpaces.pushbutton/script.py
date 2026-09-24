# -*- coding: utf-8 -*-
"""Copia os nomes dos ambientes de um link escolhido para os espaços do modelo.

Para cada espaço MEP (Space) do modelo atual (hospedeiro), o script acha o
ambiente (Room) do modelo vinculado escolhido que está no mesmo lugar e copia
o nome dele no parâmetro Nome do espaço.

Espaços e ambientes são casados por geometria: o ponto de locação do espaço é
transformado para o sistema de coordenadas do link e testado com
``Room.IsPointInRoom``. Uma guarda vertical (de pavimento) evita casar um espaço
com um ambiente de outro andar.
"""

__title__ = "Room Names\nto Spaces"
__doc__ = (
    u"Escolha um modelo vinculado e copie o nome de cada ambiente (Room) "
    u"para o espaço (Space) no mesmo lugar do modelo atual (por geometria)."
)
__author__ = "Paulo Giavoni"

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkInstance,
    BuiltInCategory,
    BuiltInParameter,
    XYZ,
)

from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# Guarda de mesmo pavimento (pés). Um espaço e o seu ambiente têm a mesma
# elevação de nível, e os pontos de locação ficam próximos na vertical. O
# pé-direito entre pavimentos é bem maior: a guarda evita casar andares errados.
FLOOR_TOL = 3.0


# ============================================================
# AUXILIARES
# ============================================================
def _room_name(room):
    """Devolve só o nome do ambiente (sem o número), ou string vazia."""
    p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
    if p is None:
        return ""
    val = p.AsString()
    return val.strip() if val else ""


def _loc_point(elem):
    """Ponto de locação de um elemento espacial, ou None."""
    loc = elem.Location
    if loc is None or not hasattr(loc, "Point"):
        return None
    return loc.Point


def _loaded_links():
    """título -> RevitLinkInstance de cada link carregado no hospedeiro."""
    out = {}
    for lnk in (FilteredElementCollector(doc)
                .OfClass(RevitLinkInstance)):
        link_doc = lnk.GetLinkDocument()
        if link_doc is None:
            continue
        out[link_doc.Title] = lnk
    return out


# ============================================================
# 1. ESCOLHA DO MODELO DE ORIGEM (VINCULADO)
# ============================================================
links = _loaded_links()
if not links:
    forms.alert("Nenhum link Revit carregado no projeto.",
                title="Room Names to Spaces", exitscript=True)

chosen = forms.SelectFromList.show(
    sorted(links.keys()),
    title="Selecione o modelo de origem (ambientes)",
    button_name="Copiar nomes dos ambientes",
    multiselect=False,
)
if not chosen:
    script.exit()

link_instance = links[chosen]
link_doc = link_instance.GetLinkDocument()
link_transform = link_instance.GetTotalTransform()
inv_transform = link_transform.Inverse


# ============================================================
# 2. COLETA DOS AMBIENTES (origem) E DOS ESPAÇOS (destino)
# ============================================================
rooms = []  # (ambiente, ponto_de_locação_em_coords_do_link)
for r in (FilteredElementCollector(link_doc)
          .OfCategory(BuiltInCategory.OST_Rooms)
          .WhereElementIsNotElementType()):
    # Pula ambientes não posicionados / não fechados.
    try:
        if r.Area <= 0:
            continue
    except Exception:
        continue
    pt = _loc_point(r)
    if pt is None:
        continue
    rooms.append((r, pt))

if not rooms:
    forms.alert(u"O link selecionado não tem ambientes posicionados.",
                title="Room Names to Spaces", exitscript=True)

spaces = list(
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MEPSpaces)
    .WhereElementIsNotElementType()
)
if not spaces:
    forms.alert(u"Não há espaços no modelo atual.",
                title="Room Names to Spaces", exitscript=True)


# ============================================================
# 3. CASA CADA ESPAÇO COM UM AMBIENTE E COPIA O NOME
# ============================================================
def _match_room(space_pt_host):
    """Acha o ambiente cujo volume contém o ponto de locação do espaço."""
    lp = inv_transform.OfPoint(space_pt_host)
    for (room, r_pt) in rooms:
        # Guarda de mesmo pavimento antes do teste geométrico (mais pesado).
        if abs(r_pt.Z - lp.Z) > FLOOR_TOL:
            continue
        test_pt = XYZ(lp.X, lp.Y, r_pt.Z)
        try:
            if room.IsPointInRoom(test_pt):
                return room
        except Exception:
            pass
    return None


updated = 0
unmatched = 0
empty_name = 0
unplaced = 0

with revit.Transaction(u"Copiar nomes dos ambientes para os espaços"):
    for sp in spaces:
        try:
            if sp.Area <= 0:
                unplaced += 1
                continue
        except Exception:
            unplaced += 1
            continue

        sp_pt = _loc_point(sp)
        if sp_pt is None:
            unplaced += 1
            continue

        room = _match_room(sp_pt)
        if room is None:
            unmatched += 1
            continue

        name = _room_name(room)
        if not name:
            empty_name += 1
            continue

        p = sp.get_Parameter(BuiltInParameter.ROOM_NAME)
        if p is not None and not p.IsReadOnly:
            p.Set(name)
            updated += 1
        else:
            unmatched += 1


# ============================================================
# 4. RELATÓRIO
# ============================================================
output.print_md("## Room Names to Spaces")
output.print_md("**Modelo de origem:** {}".format(chosen))
output.print_md("- Ambientes posicionados: **{}**".format(len(rooms)))
output.print_md(u"- Espaços processados: **{}**".format(len(spaces)))
output.print_md(u"- Nomes de espaço atualizados: **{}**".format(updated))
if unmatched:
    output.print_md(u"- Espaços sem ambiente casado: **{}**".format(unmatched))
if empty_name:
    output.print_md("- Ambientes casados mas sem nome (pulados): **{}**"
                    .format(empty_name))
if unplaced:
    output.print_md(u"- Espaços não posicionados (pulados): **{}**".format(unplaced))

forms.alert(
    u"{} nome(s) de espaço atualizado(s) a partir de \"{}\".".format(updated, chosen),
    title="Room Names to Spaces",
)
