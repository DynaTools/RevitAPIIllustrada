# -*- coding: utf-8 -*-
"""Create Space Separation Lines from the Rooms of a linked model.

Workflow
--------
1. Pick a loaded architectural link (auto-picked when only one is loaded).
2. Every placed Room is read from the link and its boundary loops are
   extracted at the wall Finish face (the same outline you see for the
   Room), including inner loops (islands / holes).
3. Each linked level is mapped to the closest host level, comparing
   elevations in host coordinates (the link transform is applied and
   ``ProjectElevation`` is used so a Shared elevation base cannot break
   the match).
4. The user picks which host levels to process and whether to only add
   the missing lines or to replace the existing separation lines on the
   selected levels first.
5. Boundary curves are transformed into host coordinates, flattened onto
   the host level plane, filtered (short curves, duplicates within the
   run, duplicates against lines already in the model) and created as
   Space Separation Lines in a plan view of that level.

Everything runs inside a single transaction: on error or cancel nothing
is changed. Revit warnings raised while creating the lines (e.g. lines
overlapping walls) are swallowed automatically so the run is unattended.
"""

__title__ = "Rooms to\nSpace Lines"
__doc__ = (
    "Read the Rooms of a linked architectural model and recreate their "
    "boundaries as Space Separation Lines in the current model, so the "
    "Spaces always keep the Room references even when the link changes. "
    "Safe to re-run: existing lines are never duplicated."
)
__author__ = "Paulo Giavoni"

import traceback

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CurveArray,
    ElementId,
    FailureProcessingResult,
    FailureSeverity,
    FilteredElementCollector,
    IFailuresPreprocessor,
    Level,
    Plane,
    RevitLinkInstance,
    SketchPlane,
    SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions,
    Transaction,
    Transform,
    ViewPlan,
    ViewType,
    XYZ,
)
from System.Collections.Generic import List as NetList

from pyrevit import forms, revit, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "Rooms to Space Lines"

# Geometry tolerances (feet).
DEDUPE_XY = 0.01          # ~3 mm grid used to detect coincident curves
DEDUPE_Z = 0.1            # ~30 mm vertical grid for the same test
MAX_LEVEL_DIST = 3.0      # linked level farther than this from every
                          # host level -> its rooms are skipped
REPLACE_Z_BAND = 1.0      # existing lines within this distance of a
                          # selected level are deleted in Replace mode
FT_TO_M = 0.3048


class _UserCancelled(Exception):
    pass


class _SwallowWarnings(IFailuresPreprocessor):
    """Delete every transaction warning so the run needs no clicks."""

    def PreprocessFailures(self, failures_accessor):
        for msg in failures_accessor.GetFailureMessages():
            try:
                if msg.GetSeverity() == FailureSeverity.Warning:
                    failures_accessor.DeleteWarning(msg)
            except Exception:
                pass
        return FailureProcessingResult.Continue


# ============================================================
# HELPERS
# ============================================================
def _loaded_links():
    """title -> RevitLinkInstance for every loaded link in the host model."""
    out = {}
    for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_doc = lnk.GetLinkDocument()
        if link_doc is None:
            continue
        out[link_doc.Title] = lnk
    return out


def _placed_rooms(link_doc):
    """Every placed (Area > 0) Room of the linked document."""
    rooms = []
    for r in (FilteredElementCollector(link_doc)
              .OfCategory(BuiltInCategory.OST_Rooms)
              .WhereElementIsNotElementType()):
        try:
            if r.Area > 0:
                rooms.append(r)
        except Exception:
            pass
    return rooms


def _host_levels():
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    levels.sort(key=lambda lv: lv.ProjectElevation)
    return levels


def _closest_host_level(host_z, host_levels):
    """(Level, abs distance) of the host level closest to ``host_z``."""
    best, best_d = None, None
    for lv in host_levels:
        d = abs(lv.ProjectElevation - host_z)
        if best_d is None or d < best_d:
            best, best_d = lv, d
    return best, best_d


def _plan_view_for_level(level_id):
    """Best plan view to host the lines: prefer a Floor Plan of the level."""
    fallback = None
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        if v.IsTemplate:
            continue
        gl = v.GenLevel
        if gl is None or gl.Id != level_id:
            continue
        if v.ViewType == ViewType.FloorPlan:
            return v
        if fallback is None:
            fallback = v
    return fallback


def _quant_pt(pt, z):
    return (int(round(pt.X / DEDUPE_XY)),
            int(round(pt.Y / DEDUPE_XY)),
            int(round(z / DEDUPE_Z)))


def _curve_key(curve):
    """Order-independent geometric fingerprint of a bound curve.

    Endpoints plus the mid-point, quantized on a small grid: enough to
    tell straight and curved segments apart and to catch the same
    boundary contributed twice by two adjacent rooms.
    """
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    pm = curve.Evaluate(0.5, True)
    z = p0.Z
    k0, k1 = _quant_pt(p0, z), _quant_pt(p1, z)
    if k1 < k0:
        k0, k1 = k1, k0
    return (k0, k1, _quant_pt(pm, z))


def _existing_separation_lines():
    """[(element, key or None, z or None)] for every Space Separation Line."""
    found = []
    for ce in (FilteredElementCollector(doc)
               .OfCategory(BuiltInCategory.OST_MEPSpaceSeparationLines)
               .WhereElementIsNotElementType()):
        key, z = None, None
        try:
            crv = ce.GeometryCurve
            if crv is not None and crv.IsBound:
                key = _curve_key(crv)
                z = crv.GetEndPoint(0).Z
            elif crv is not None:
                z = crv.Evaluate(0.0, True).Z
        except Exception:
            pass
        found.append((ce, key, z))
    return found


def _flatten_to(curve, target_z):
    """Return the curve translated vertically onto ``target_z``."""
    dz = target_z - curve.GetEndPoint(0).Z
    if abs(dz) < 1e-9:
        return curve
    return curve.CreateTransformed(
        Transform.CreateTranslation(XYZ(0.0, 0.0, dz)))


# ============================================================
# 1. PICK THE SOURCE (LINKED) MODEL
# ============================================================
links = _loaded_links()
if not links:
    forms.alert("No loaded Revit link found in the project.",
                title=TITLE, exitscript=True)

if len(links) == 1:
    chosen = list(links.keys())[0]
else:
    chosen = forms.SelectFromList.show(
        sorted(links.keys()),
        title="Select the source model (Rooms)",
        button_name="Read Rooms",
        multiselect=False,
    )
if not chosen:
    script.exit()

link_instance = links[chosen]
link_doc = link_instance.GetLinkDocument()
link_transform = link_instance.GetTotalTransform()


# ============================================================
# 2. COLLECT ROOMS AND MAP LINKED LEVELS TO HOST LEVELS
# ============================================================
rooms = _placed_rooms(link_doc)
if not rooms:
    forms.alert("The selected link has no placed Rooms.",
                title=TITLE, exitscript=True)

host_levels = _host_levels()
if not host_levels:
    forms.alert("The current model has no Levels.",
                title=TITLE, exitscript=True)

# linked Level.Id -> (host Level or None, delta ft, linked level name)
level_map = {}
# host Level.Id -> {"level": Level, "rooms": [...]}
rooms_by_host = {}
skipped_no_level = 0
unmatched_levels = {}

for room in rooms:
    try:
        link_level = room.Level
    except Exception:
        link_level = None
    if link_level is None:
        skipped_no_level += 1
        continue

    lid = link_level.Id
    if lid not in level_map:
        host_z = link_transform.OfPoint(
            XYZ(0.0, 0.0, link_level.ProjectElevation)).Z
        host_level, dist = _closest_host_level(host_z, host_levels)
        if host_level is None or dist > MAX_LEVEL_DIST:
            level_map[lid] = (None, dist, link_level.Name)
        else:
            level_map[lid] = (host_level, dist, link_level.Name)

    host_level, dist, link_name = level_map[lid]
    if host_level is None:
        unmatched_levels[link_name] = unmatched_levels.get(link_name, 0) + 1
        continue

    slot = rooms_by_host.setdefault(
        host_level.Id, {"level": host_level, "rooms": []})
    slot["rooms"].append(room)

if not rooms_by_host:
    forms.alert(
        "No linked level could be matched to a host level "
        "(closest match farther than {:.1f} m). Check the shared "
        "coordinates / levels of the two models.".format(
            MAX_LEVEL_DIST * FT_TO_M),
        title=TITLE, exitscript=True)


# ============================================================
# 3. LET THE USER PICK THE LEVELS AND THE MODE
# ============================================================
slots = sorted(rooms_by_host.values(),
               key=lambda s: s["level"].ProjectElevation)
label_to_id = {}
labels = []
for slot in slots:
    lv = slot["level"]
    label = "{}   |   elev {:.2f} m   |   {} room(s)".format(
        lv.Name, lv.ProjectElevation * FT_TO_M, len(slot["rooms"]))
    labels.append(label)
    label_to_id[label] = lv.Id

picked = forms.SelectFromList.show(
    labels,
    title="Select the host levels to process",
    button_name="Continue",
    multiselect=True,
)
if not picked:
    script.exit()

selected_ids = set(label_to_id[p] for p in picked)
selected_slots = [s for s in slots
                  if s["level"].Id in selected_ids]
total_rooms = sum(len(s["rooms"]) for s in selected_slots)

mode = forms.alert(
    "Source link:  {}\n"
    "Levels to process:  {}\n"
    "Rooms to trace:  {}\n\n"
    "How should the existing Space Separation Lines be handled?\n\n"
    "  -  Add missing only: keeps everything already drawn and only "
    "creates the lines that do not exist yet (safe to re-run).\n"
    "  -  Replace on selected levels: deletes the Space Separation "
    "Lines found on the selected levels, then recreates all of them "
    "from the Rooms.".format(chosen, len(selected_slots), total_rooms),
    title=TITLE,
    options=["Add missing only", "Replace on selected levels", "Cancel"],
)
if not mode or mode == "Cancel":
    script.exit()
replace_mode = (mode == "Replace on selected levels")

# Plan views checked up-front so the user learns about gaps before
# anything is modified.
views_by_level = {}
levels_without_view = []
for slot in selected_slots:
    lv = slot["level"]
    view = _plan_view_for_level(lv.Id)
    if view is None:
        levels_without_view.append(lv.Name)
    else:
        views_by_level[lv.Id] = view

if levels_without_view and not forms.alert(
        "No plan view exists for these levels, so their lines cannot "
        "be created and they will be skipped:\n\n  {}\n\n"
        "Continue with the remaining levels?".format(
            "\n  ".join(levels_without_view)),
        title=TITLE, ok=False, yes=True, no=True):
    script.exit()


# ============================================================
# 4. CREATE THE LINES (single transaction, rollback on any problem)
# ============================================================
boundary_opts = SpatialElementBoundaryOptions()
boundary_opts.SpatialElementBoundaryLocation = \
    SpatialElementBoundaryLocation.Finish

existing = _existing_separation_lines()
seen_keys = set(k for (_e, k, _z) in existing if k is not None)

short_tol = doc.Application.ShortCurveTolerance

deleted = 0
created = 0
dup_skipped = 0
short_skipped = 0
failed_curves = 0
rooms_no_boundary = 0
per_level_stats = []   # (level name, rooms, created, duplicates)

t = Transaction(doc, TITLE)
fail_opts = t.GetFailureHandlingOptions()
fail_opts.SetFailuresPreprocessor(_SwallowWarnings())
t.SetFailureHandlingOptions(fail_opts)
t.Start()
try:
    # 4a. Replace mode: drop the existing lines sitting on the selected
    # levels (and forget their fingerprints so they can be recreated).
    if replace_mode:
        target_zs = [s["level"].ProjectElevation for s in selected_slots
                     if s["level"].Id in views_by_level]
        to_delete = NetList[ElementId]()
        for (elem, key, z) in existing:
            if z is None:
                continue
            if any(abs(z - tz) <= REPLACE_Z_BAND for tz in target_zs):
                to_delete.Add(elem.Id)
                if key is not None:
                    seen_keys.discard(key)
        if to_delete.Count > 0:
            deleted = to_delete.Count
            doc.Delete(to_delete)
            doc.Regenerate()

    # 4b. Trace every room boundary onto its host level.
    done = 0
    with forms.ProgressBar(title="Tracing room {value} of {max_value}",
                           cancellable=True) as pb:
        for slot in selected_slots:
            lv = slot["level"]
            view = views_by_level.get(lv.Id)
            if view is None:
                done += len(slot["rooms"])
                pb.update_progress(done, total_rooms)
                continue

            sketch_plane = SketchPlane.Create(
                doc,
                Plane.CreateByNormalAndOrigin(
                    XYZ.BasisZ, XYZ(0.0, 0.0, lv.ProjectElevation)))

            lv_created = 0
            lv_dups = 0
            for room in slot["rooms"]:
                if pb.cancelled:
                    raise _UserCancelled()

                loops = room.GetBoundarySegments(boundary_opts)
                if loops is None or loops.Count == 0:
                    rooms_no_boundary += 1
                    done += 1
                    pb.update_progress(done, total_rooms)
                    continue

                for loop in loops:
                    for seg in loop:
                        try:
                            crv = seg.GetCurve()
                            if crv is None:
                                continue
                            crv = crv.CreateTransformed(link_transform)
                            crv = _flatten_to(crv, lv.ProjectElevation)
                            if crv.Length < short_tol * 1.01:
                                short_skipped += 1
                                continue
                            key = _curve_key(crv)
                            if key in seen_keys:
                                lv_dups += 1
                                continue
                            arr = CurveArray()
                            arr.Append(crv)
                            doc.Create.NewSpaceBoundaryLines(
                                sketch_plane, arr, view)
                            seen_keys.add(key)
                            lv_created += 1
                        except _UserCancelled:
                            raise
                        except Exception:
                            failed_curves += 1

                done += 1
                pb.update_progress(done, total_rooms)

            created += lv_created
            dup_skipped += lv_dups
            per_level_stats.append(
                (lv.Name, len(slot["rooms"]), lv_created, lv_dups))

    t.Commit()

except _UserCancelled:
    t.RollBack()
    forms.alert("Cancelled by user. Nothing was changed.",
                title=TITLE, exitscript=True)
except Exception:
    t.RollBack()
    output.print_md("## {} - error (rolled back)".format(TITLE))
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
    forms.alert(
        "An error occurred and the transaction was rolled back - the "
        "model was NOT modified. See the output window for details.",
        title=TITLE, exitscript=True)


# ============================================================
# 5. REPORT
# ============================================================
output.print_md("## {}".format(TITLE))
output.print_md("**Source link:** {}".format(chosen))
output.print_md(
    "**Mode:** {}".format("Replace on selected levels"
                          if replace_mode else "Add missing only"))

if per_level_stats:
    output.print_table(
        table_data=[[name, rc, cr, dp]
                    for (name, rc, cr, dp) in per_level_stats],
        columns=["Host level", "Rooms", "Lines created", "Duplicates skipped"],
        title="Levels processed",
    )

output.print_md("- Separation lines created: **{}**".format(created))
if deleted:
    output.print_md("- Existing lines deleted (replace mode): **{}**"
                    .format(deleted))
if dup_skipped:
    output.print_md("- Curves skipped (already present): **{}**"
                    .format(dup_skipped))
if short_skipped:
    output.print_md("- Curves skipped (below the minimum length): **{}**"
                    .format(short_skipped))
if failed_curves:
    output.print_md("- Curves Revit refused to create: **{}**"
                    .format(failed_curves))
if rooms_no_boundary:
    output.print_md("- Rooms without a boundary (skipped): **{}**"
                    .format(rooms_no_boundary))
if skipped_no_level:
    output.print_md("- Rooms without a level (skipped): **{}**"
                    .format(skipped_no_level))
if unmatched_levels:
    output.print_md(
        "- Rooms on linked levels with **no matching host level**: {}"
        .format(", ".join("{} ({} room(s))".format(n, c)
                          for n, c in sorted(unmatched_levels.items()))))
if levels_without_view:
    output.print_md(
        "- Levels skipped for lack of a plan view: {}"
        .format(", ".join(levels_without_view)))

forms.alert(
    "{} Space Separation Line(s) created from \"{}\".{}".format(
        created, chosen,
        "\n{} existing line(s) replaced.".format(deleted)
        if deleted else ""),
    title=TITLE,
)
