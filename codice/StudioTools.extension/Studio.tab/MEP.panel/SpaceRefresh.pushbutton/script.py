#! python3
# -*- coding: utf-8 -*-
"""Refresh all MEP Spaces in the model.

Workflow
--------
1. Capture the Space tag type currently used in the model (so we can re-tag
   with the same family/type). If no Space tag is loaded, spaces are recreated
   untagged.
2. Capture the (level, phase) pairs that currently have spaces, so we recreate
   them with the same scope. If there are NO spaces yet, fall back to every
   level using the active view's phase.
3. Delete every Space (their tags are removed automatically).
4. Enable "Room Bounding" on every linked Revit model, so the new spaces pick
   up the boundaries coming from the linked architecture.
5. Recreate the spaces in all enclosed regions (NewSpaces2) per level/phase.
6. Re-tag each new space (in a plan view of its level) with the captured tag
   type. If none exists, spaces stay untagged.
7. Copy the Room name from the loaded links into each new Space, matched by
   geometry (same logic as the "Room Names to Spaces" button, but scanning
   every loaded link automatically instead of asking which one).

Runs on CPython (no pyrevit dependency) using TaskDialog only.
"""

__title__ = "Space\nRefresh"
__doc__ = (
    "Delete all Spaces, enable Room Bounding on links, recreate the Spaces, "
    "re-tag them with the Space tag already loaded in the model (untagged "
    "if none) and copy the Room names from the loaded links into the new "
    "Spaces."
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

# Same-storey guard (feet) for the room-name matching. A Space and its Room
# share the level elevation, so their location points are vertically close.
# Floor-to-floor heights are well above this, stopping cross-storey matches.
FLOOR_TOL = 3.0


# ============================================================
# HELPERS
# ============================================================
class _ScriptExit(Exception):
    pass


def _id_int(eid):
    """Numeric value of an ElementId on any Revit version.

    ``ElementId.IntegerValue`` was removed in Revit 2026 and ``Value``
    only exists from Revit 2024 on, so both spellings must be tried.
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
    """Return the ElementId of the Space tag type to reuse, or None.

    Prefers the type already used by existing Space tags ("a tag que tiver no
    modelo"); otherwise the first loaded Space tag type.
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
    """Set the link type's Room Bounding parameter to 1. Returns True if set."""
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
    """Return the Room Name only (without the number), or empty string."""
    p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
    if p is None:
        return ""
    val = p.AsString()
    return val.strip() if val else ""


def _collect_link_rooms(document):
    """Placed Rooms of every loaded link, grouped per link.

    Returns [(inverse_transform, [(room, room_pt_link_coords), ...]), ...]
    so a space point is transformed once per link, not once per room.
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
            # Skip unplaced / unenclosed rooms.
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
    """Room (from any loaded link) whose volume contains the space point."""
    for (inv, rooms) in link_rooms:
        lp = inv.OfPoint(space_pt_host)
        for (room, r_pt) in rooms:
            # Same-storey guard before the (heavier) geometric test.
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
    """Best plan view to place tags on: same level, prefer matching phase."""
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
# MAIN
# ============================================================
def main():
    existing = _spaces(doc)
    fallback_phase = _active_phase_id(doc)

    # 1. Tag type to reuse.
    tag_type_id = _pick_tag_type(doc)
    tag_label = (_type_label(doc.GetElement(tag_type_id))
                 if tag_type_id else "(sem tag - nenhuma carregada)")

    # 2. (level, phase) scope.
    scope = {}   # (lvl_int, ph_int) -> (levelId, phaseId)
    for s in existing:
        lvl_id = s.LevelId
        if lvl_id is None or lvl_id == ElementId.InvalidElementId:
            continue
        ph_id = _space_phase_id(s, fallback_phase)
        scope[(_id_int(lvl_id), _id_int(ph_id))] = (lvl_id, ph_id)

    scope_note = "niveis/fases dos spaces atuais"
    if not scope:
        # No spaces yet: fall back to every level, active phase.
        for lv in (FilteredElementCollector(doc).OfClass(Level)):
            scope[(_id_int(lv.Id), _id_int(fallback_phase))] = (
                lv.Id, fallback_phase)
        scope_note = "TODOS os niveis (nenhum space existente)"

    if fallback_phase == ElementId.InvalidElementId:
        _alert("Nao encontrei uma fase valida para criar os spaces.",
               exit_after=True)

    link_types = list(
        FilteredElementCollector(doc).OfClass(RevitLinkType))

    # Rooms of the loaded links (source of the space names).
    link_rooms = _collect_link_rooms(doc)
    n_rooms = sum(len(rs) for (_inv, rs) in link_rooms)

    if not _confirm(
            "Esta acao vai:\n\n"
            "  - APAGAR {0} space(s) existente(s)\n"
            "  - Habilitar Room Bounding em {1} link(s)\n"
            "  - Recriar spaces em {2} ({3} combinacao(oes) nivel/fase)\n"
            "  - Re-taguear com: {4}\n"
            "  - Copiar os nomes de {5} room(s) dos links\n\n"
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
        # 3. Delete every space.
        if existing:
            ids = NetList[ElementId]()
            for s in existing:
                ids.Add(s.Id)
            deleted = ids.Count
            doc.Delete(ids)

        # 4. Enable room bounding on links, then regenerate.
        for lt in link_types:
            if _enable_room_bounding(lt):
                bounded += 1
        doc.Regenerate()

        # 5. Activate the tag type once (if any).
        if tag_type_id:
            sym = doc.GetElement(tag_type_id)
            try:
                if sym is not None and not sym.IsActive:
                    sym.Activate()
                    doc.Regenerate()
            except Exception:
                pass

        # 6. Recreate spaces per level/phase, then tag them.
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

        # 7. Copy the Room names from the links into the new spaces.
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
        _alert("Erro durante o refresh (nada foi alterado):\n\n%s" % ex,
               exit_after=True)

    msg = ("Concluido.\n\n"
           "Spaces apagados: {0}\n"
           "Links com Room Bounding habilitado: {1}\n"
           "Spaces recriados: {2}\n"
           "Tags colocadas: {3}\n"
           "Nomes de room copiados: {4}".format(
               deleted, bounded, created, tagged, named))
    if skipped_levels:
        msg += ("\n\nObs.: {0} nivel(is) sem vista de planta para colocar "
                "tags (spaces criados, mas sem tag).".format(skipped_levels))
    if not tag_type_id:
        msg += "\n\nObs.: nenhum tipo de tag de Space no modelo - sem tags."
    if not link_rooms:
        msg += ("\n\nObs.: nenhum room encontrado nos links carregados - "
                "nomes nao copiados.")
    elif unnamed:
        msg += ("\n\nObs.: {0} space(s) sem room correspondente (ou room "
                "sem nome) - mantiveram o nome padrao.".format(unnamed))
    _alert(msg)


try:
    main()
except _ScriptExit:
    pass
