# -*- coding: utf-8 -*-
"""Copy Room names from a selected linked model into the host model Spaces.

For every MEP Space in the current (host) model, the script finds the Room
(in the linked model the user picks) that sits at the same location and copies
its Name into the Space's Name parameter.

Spaces and Rooms are matched by geometry: the Space location point is
transformed into the link coordinate system and tested with
``Room.IsPointInRoom``. A vertical (floor) guard avoids matching a Space to a
Room sitting on a different storey.
"""

__title__ = "Room Names\nto Spaces"
__doc__ = (
    "Pick a linked model and copy every Room Name into the Space that sits "
    "at the same location in the current model (matched by geometry)."
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

# Same-storey guard (feet). A Space and its Room share the level elevation, so
# their location points are vertically close. Floor-to-floor heights are well
# above this value, so the guard stops cross-storey false matches.
FLOOR_TOL = 3.0


# ============================================================
# HELPERS
# ============================================================
def _room_name(room):
    """Return the Room Name only (without the number), or empty string."""
    p = room.get_Parameter(BuiltInParameter.ROOM_NAME)
    if p is None:
        return ""
    val = p.AsString()
    return val.strip() if val else ""


def _loc_point(elem):
    """Location point of a spatial element, or None."""
    loc = elem.Location
    if loc is None or not hasattr(loc, "Point"):
        return None
    return loc.Point


def _loaded_links():
    """title -> RevitLinkInstance for every loaded link in the host model."""
    out = {}
    for lnk in (FilteredElementCollector(doc)
                .OfClass(RevitLinkInstance)):
        link_doc = lnk.GetLinkDocument()
        if link_doc is None:
            continue
        out[link_doc.Title] = lnk
    return out


# ============================================================
# 1. PICK THE SOURCE (LINKED) MODEL
# ============================================================
links = _loaded_links()
if not links:
    forms.alert("No loaded Revit link found in the project.",
                title="Room Names to Spaces", exitscript=True)

chosen = forms.SelectFromList.show(
    sorted(links.keys()),
    title="Select the source model (Rooms)",
    button_name="Copy Room Names",
    multiselect=False,
)
if not chosen:
    script.exit()

link_instance = links[chosen]
link_doc = link_instance.GetLinkDocument()
link_transform = link_instance.GetTotalTransform()
inv_transform = link_transform.Inverse


# ============================================================
# 2. COLLECT ROOMS (source) AND SPACES (target)
# ============================================================
rooms = []  # (room, location_point_in_link_coords)
for r in (FilteredElementCollector(link_doc)
          .OfCategory(BuiltInCategory.OST_Rooms)
          .WhereElementIsNotElementType()):
    # Skip unplaced / unenclosed rooms.
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
    forms.alert("The selected link has no placed Rooms.",
                title="Room Names to Spaces", exitscript=True)

spaces = list(
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_MEPSpaces)
    .WhereElementIsNotElementType()
)
if not spaces:
    forms.alert("There are no Spaces in the current model.",
                title="Room Names to Spaces", exitscript=True)


# ============================================================
# 3. MATCH EACH SPACE TO A ROOM AND COPY THE NAME
# ============================================================
def _match_room(space_pt_host):
    """Find the Room whose volume contains the Space location point."""
    lp = inv_transform.OfPoint(space_pt_host)
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


updated = 0
unmatched = 0
empty_name = 0
unplaced = 0

with revit.Transaction("Copy Room Names to Spaces"):
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
# 4. REPORT
# ============================================================
output.print_md("## Room Names to Spaces")
output.print_md("**Source model:** {}".format(chosen))
output.print_md("- Rooms found (placed): **{}**".format(len(rooms)))
output.print_md("- Spaces processed: **{}**".format(len(spaces)))
output.print_md("- Space names updated: **{}**".format(updated))
if unmatched:
    output.print_md("- Spaces with no matching Room: **{}**".format(unmatched))
if empty_name:
    output.print_md("- Matched Rooms with empty name (skipped): **{}**"
                    .format(empty_name))
if unplaced:
    output.print_md("- Unplaced Spaces (skipped): **{}**".format(unplaced))

forms.alert(
    "{} Space name(s) updated from \"{}\".".format(updated, chosen),
    title="Room Names to Spaces",
)
