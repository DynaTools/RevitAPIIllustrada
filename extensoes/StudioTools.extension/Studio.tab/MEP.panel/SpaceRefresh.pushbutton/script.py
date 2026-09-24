#! python3
# -*- coding: utf-8 -*-
"""Refaz (refresh) todos os espaços MEP (Spaces) do modelo.

Fluxo
-----
1. Captura o tipo de tag de espaço usado hoje no modelo (para re-taguear com a
   mesma família/tipo). Se nenhuma tag de espaço estiver carregada, os espaços
   são recriados sem tag.
2. Captura os pares (nível, fase) que hoje têm espaços, para recriá-los com o
   mesmo escopo. Se ainda NÃO houver espaços, usa todos os níveis com a fase
   da vista ativa.
3. Apaga todos os espaços (as tags deles são removidas automaticamente).
4. Habilita o "Room Bounding" em todos os modelos Revit vinculados, para que os
   novos espaços peguem os limites vindos da arquitetura vinculada.
5. Recria os espaços em todas as regiões fechadas (NewSpaces2) por nível/fase.
6. Re-tagueia cada espaço novo (numa vista de planta do seu nível) com o tipo
   de tag capturado. Se não houver nenhum, os espaços ficam sem tag.
7. Copia o nome do ambiente (Room) dos links carregados para cada espaço novo,
   casando por geometria (mesma lógica do botão "Room Names to Spaces", mas
   varrendo sozinho todos os links carregados em vez de perguntar qual).

Roda em CPython (sem dependência do pyrevit) e usa só TaskDialog.
"""

__title__ = "Space\nRefresh"
__doc__ = (
    "Apaga todos os espaços, habilita o Room Bounding nos links, recria os "
    "espaços, re-tagueia com a tag de espaço já carregada no modelo (sem tag "
    "se não houver) e copia os nomes dos ambientes dos links carregados para "
    "os novos espaços."
)
__author__ = "Paulo Giavoni"

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    RevitLinkInstance,
    RevitLinkType,
    Level,
    Phase,
    UV,
    XYZ,
    ViewPlan,
    Transaction,
)
from Autodesk.Revit.DB.Mechanical import Space, SpaceTag
from Autodesk.Revit.UI import (
    TaskDialog, TaskDialogCommonButtons, TaskDialogResult,
)

from System.Collections.Generic import List as NetList

uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc = uidoc.Document

# Guarda de mesmo pavimento (pés) para casar os nomes. Um espaço e o seu
# ambiente têm a mesma elevação de nível, e os pontos de locação ficam próximos
# na vertical. O pé-direito entre pavimentos é bem maior: não casa andares.
FLOOR_TOL = 3.0


# ============================================================
# AUXILIARES
# ============================================================
class _ScriptExit(Exception):
    pass


def _id_int(eid):
    """Valor numérico de um ElementId em qualquer versão do Revit.

    ``ElementId.IntegerValue`` foi removido no Revit 2026 e ``Value``
    só existe a partir do Revit 2024, então é preciso tentar as duas formas.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _alert(msg, title="Space Refresh", exit_after=False):
    TaskDialog.Show(title, msg)
    if exit_after:
        raise _ScriptExit()


def _confirm(msg, title="Space Refresh"):
    td = TaskDialog(title)
    td.MainInstruction = title
    td.MainContent = msg
    td.CommonButtons = (TaskDialogCommonButtons.Yes |
                        TaskDialogCommonButtons.No)
    td.DefaultButton = TaskDialogResult.No
    return td.Show() == TaskDialogResult.Yes


def _spaces(document):
    return list(
        FilteredElementCollector(document)
        .OfCategory(BuiltInCategory.OST_MEPSpaces)
        .WhereElementIsNotElementType()
    )


def _space_tags(document):
    return list(
        FilteredElementCollector(document)
        .OfCategory(BuiltInCategory.OST_MEPSpaceTags)
        .WhereElementIsNotElementType()
    )


def _space_tag_types(document):
    return list(
        FilteredElementCollector(document)
        .OfCategory(BuiltInCategory.OST_MEPSpaceTags)
        .WhereElementIsElementType()
    )


def _type_label(symbol):
    try:
        fam = symbol.Family.Name
    except Exception:
        fam = ""
    try:
        name = symbol.Name
    except Exception:
        name = str(symbol.Id)
    return ("%s : %s" % (fam, name)) if fam else name


def _pick_tag_type(document):
    """Devolve o ElementId do tipo de tag de espaço a reutilizar, ou None.

    Prefere o tipo já usado pelas tags de espaço existentes ("a tag que tiver
    no modelo"); senão, o primeiro tipo de tag de espaço carregado.
    """
    counts = {}
    for t in _space_tags(document):
        tid = t.GetTypeId()
        if tid and tid != ElementId.InvalidElementId:
            key = _id_int(tid)
            cnt, _eid = counts.get(key, (0, tid))
            counts[key] = (cnt + 1, tid)
    if counts:
        best = max(counts.values(), key=lambda x: x[0])
        return best[1]
    types = _space_tag_types(document)
    if types:
        return types[0].Id
    return None


def _space_phase_id(space, fallback_phase_id):
    p = space.get_Parameter(BuiltInParameter.ROOM_PHASE)
    if p is not None:
        pid = p.AsElementId()
        if pid and pid != ElementId.InvalidElementId:
            return pid
    return fallback_phase_id


def _active_phase_id(document):
    view = uidoc.ActiveView
    if view is not None:
        p = view.get_Parameter(BuiltInParameter.VIEW_PHASE)
        if p is not None:
            pid = p.AsElementId()
            if pid and pid != ElementId.InvalidElementId:
                return pid
    phases = document.Phases
    if phases.Size > 0:
        return phases.get_Item(phases.Size - 1).Id
    return ElementId.InvalidElementId


def _enable_room_bounding(link_type):
    """Põe em 1 o Room Bounding do tipo de link. Devolve True se mudou."""
    p = link_type.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
    if p is None:
        for pp in link_type.Parameters:
            try:
                if pp.Definition.BuiltInParameter == \
                        BuiltInParameter.WALL_ATTR_ROOM_BOUNDING:
                    p = pp
                    break
            except Exception:
                pass
    if p is None or p.IsReadOnly:
        return False
    try:
        if p.AsInteger() != 1:
            p.Set(1)
            return True
    except Exception:
        return False
    return False


def _room_name(room):
    """Devolve só o nome do ambiente (sem o número), ou string vazia."""
    p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
    if p is None:
        return ""
    val = p.AsString()
    return val.strip() if val else ""


def _collect_link_rooms(document):
    """Ambientes posicionados de cada link carregado, agrupados por link.

    Devolve [(inverse_transform, [(room, room_pt_link_coords), ...]), ...]
    para transformar o ponto do espaço uma vez por link, e não por ambiente.
    """
    out = []
    for lnk in (FilteredElementCollector(document)
                .OfClass(RevitLinkInstance)):
        link_doc = lnk.GetLinkDocument()
        if link_doc is None:
            continue
        rooms = []
        for r in (FilteredElementCollector(link_doc)
                  .OfCategory(BuiltInCategory.OST_Rooms)
                  .WhereElementIsNotElementType()):
            # Pula ambientes não posicionados / não fechados.
            try:
                if r.Area <= 0:
                    continue
            except Exception:
                continue
            loc = r.Location
            if loc is None or not hasattr(loc, "Point"):
                continue
            rooms.append((r, loc.Point))
        if rooms:
            out.append((lnk.GetTotalTransform().Inverse, rooms))
    return out


def _match_room(space_pt_host, link_rooms):
    """Ambiente (de qualquer link) cujo volume contém o ponto do espaço."""
    for (inv, rooms) in link_rooms:
        lp = inv.OfPoint(space_pt_host)
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


def _plan_view_for_level(document, level_id, phase_id):
    """Vista de planta ideal para as tags: mesmo nível e, se der, mesma fase."""
    fallback = None
    for v in (FilteredElementCollector(document).OfClass(ViewPlan)):
        if v.IsTemplate:
            continue
        gl = v.GenLevel
        if gl is None or gl.Id != level_id:
            continue
        if fallback is None:
            fallback = v
        vp = v.get_Parameter(BuiltInParameter.VIEW_PHASE)
        if vp is not None and vp.AsElementId() == phase_id:
            return v
    return fallback


# ============================================================
# PRINCIPAL
# ============================================================
def main():
    existing = _spaces(doc)
    fallback_phase = _active_phase_id(doc)

    # 1. Tipo de tag a reutilizar.
    tag_type_id = _pick_tag_type(doc)
    tag_label = (_type_label(doc.GetElement(tag_type_id))
                 if tag_type_id else "(sem tag - nenhuma carregada)")

    # 2. Escopo (nível, fase).
    scope = {}   # (lvl_int, ph_int) -> (levelId, phaseId)
    for s in existing:
        lvl_id = s.LevelId
        if lvl_id is None or lvl_id == ElementId.InvalidElementId:
            continue
        ph_id = _space_phase_id(s, fallback_phase)
        scope[(_id_int(lvl_id), _id_int(ph_id))] = (lvl_id, ph_id)

    scope_note = "níveis/fases dos espaços atuais"
    if not scope:
        # Ainda sem espaços: usa todos os níveis, com a fase ativa.
        for lv in (FilteredElementCollector(doc).OfClass(Level)):
            scope[(_id_int(lv.Id), _id_int(fallback_phase))] = (
                lv.Id, fallback_phase)
        scope_note = "TODOS os níveis (nenhum espaço existente)"

    if fallback_phase == ElementId.InvalidElementId:
        _alert("Não encontrei uma fase válida para criar os espaços.",
               exit_after=True)

    link_types = list(
        FilteredElementCollector(doc).OfClass(RevitLinkType))

    # Ambientes dos links carregados (origem dos nomes dos espaços).
    link_rooms = _collect_link_rooms(doc)
    n_rooms = sum(len(rs) for (_inv, rs) in link_rooms)

    if not _confirm(
            "Esta ação vai:\n\n"
            "  - APAGAR {0} espaço(s) existente(s)\n"
            "  - Habilitar Room Bounding em {1} link(s)\n"
            "  - Recriar espaços em {2} ({3} combinação(ões) nível/fase)\n"
            "  - Re-taguear com: {4}\n"
            "  - Copiar os nomes de {5} ambiente(s) dos links\n\n"
            "Deseja continuar?".format(
                len(existing), len(link_types), scope_note,
                len(scope), tag_label, n_rooms)):
        raise _ScriptExit()

    deleted = 0
    bounded = 0
    created = 0
    tagged = 0
    named = 0
    unnamed = 0
    skipped_levels = 0

    t = Transaction(doc, "Space Refresh")
    t.Start()
    try:
        # 3. Apaga todos os espaços.
        if existing:
            ids = NetList[ElementId]()
            for s in existing:
                ids.Add(s.Id)
            deleted = ids.Count
            doc.Delete(ids)

        # 4. Habilita o Room Bounding nos links e regenera.
        for lt in link_types:
            if _enable_room_bounding(lt):
                bounded += 1
        doc.Regenerate()

        # 5. Ativa o tipo de tag uma vez (se houver).
        if tag_type_id:
            sym = doc.GetElement(tag_type_id)
            try:
                if sym is not None and not sym.IsActive:
                    sym.Activate()
                    doc.Regenerate()
            except Exception:
                pass

        # 6. Recria os espaços por nível/fase e aplica as tags.
        for (lvl_id, ph_id) in scope.values():
            level = doc.GetElement(lvl_id)
            phase = doc.GetElement(ph_id)
            if level is None or phase is None:
                continue
            try:
                new_ids = doc.Create.NewSpaces2(level, phase)
            except Exception:
                new_ids = None
            if not new_ids:
                continue

            new_space_ids = list(new_ids)
            created += len(new_space_ids)

            if not tag_type_id:
                continue
            view = _plan_view_for_level(doc, lvl_id, ph_id)
            if view is None:
                skipped_levels += 1
                continue

            doc.Regenerate()
            for sid in new_space_ids:
                space = doc.GetElement(sid)
                if not isinstance(space, Space):
                    continue
                loc = space.Location
                if loc is None or not hasattr(loc, "Point"):
                    continue
                pt = loc.Point
                try:
                    tag = doc.Create.NewSpaceTag(space, UV(pt.X, pt.Y), view)
                    if tag is not None and tag.GetTypeId() != tag_type_id:
                        tag.ChangeTypeId(tag_type_id)
                    tagged += 1
                except Exception:
                    pass

        # 7. Copia os nomes dos ambientes dos links para os novos espaços.
        if link_rooms:
            doc.Regenerate()
            for sp in _spaces(doc):
                try:
                    if sp.Area <= 0:
                        continue
                except Exception:
                    continue
                loc = sp.Location
                if loc is None or not hasattr(loc, "Point"):
                    continue
                room = _match_room(loc.Point, link_rooms)
                name = _room_name(room) if room is not None else ""
                if not name:
                    unnamed += 1
                    continue
                p = sp.get_Parameter(BuiltInParameter.ROOM_NAME)
                if p is not None and not p.IsReadOnly:
                    p.Set(name)
                    named += 1
                else:
                    unnamed += 1

        t.Commit()
    except Exception as ex:
        t.RollBack()
        _alert("Erro durante a atualização (nada foi alterado):\n\n%s" % ex,
               exit_after=True)

    msg = ("Concluído.\n\n"
           "Espaços apagados: {0}\n"
           "Links com Room Bounding habilitado: {1}\n"
           "Espaços recriados: {2}\n"
           "Tags colocadas: {3}\n"
           "Nomes de ambiente copiados: {4}".format(
               deleted, bounded, created, tagged, named))
    if skipped_levels:
        msg += ("\n\nObs.: {0} nível(is) sem vista de planta para colocar "
                "tags (espaços criados, mas sem tag).".format(skipped_levels))
    if not tag_type_id:
        msg += "\n\nObs.: nenhum tipo de tag de espaço no modelo - sem tags."
    if not link_rooms:
        msg += ("\n\nObs.: nenhum ambiente encontrado nos links carregados - "
                "nomes não copiados.")
    elif unnamed:
        msg += ("\n\nObs.: {0} espaço(s) sem ambiente correspondente (ou "
                "ambiente sem nome) - nome padrão mantido.".format(unnamed))
    _alert(msg)


try:
    main()
except _ScriptExit:
    pass
