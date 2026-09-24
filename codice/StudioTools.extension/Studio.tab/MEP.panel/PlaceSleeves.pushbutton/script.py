# -*- coding: utf-8 -*-
"""Detect MEP penetrations through walls/floors, place DirectShape sleeves."""

__title__ = "Place\nSleeves"
__doc__ = (
    "Detects where pipes, ducts, and conduits pass through walls and floors, "
    "then creates DirectShape sleeves at each penetration.\n"
    "No external family required. Uses workset TEMP-Workset."
)
__author__ = "Paulo Giavoni"

import clr
import math
import os
import tempfile

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FilteredWorksetCollector,
    WorksetKind,
    BuiltInCategory,
    BuiltInParameter,
    ElementIntersectsElementFilter,
    ElementIntersectsSolidFilter,
    SolidCurveIntersectionOptions,
    SolidCurveIntersectionMode,
    SolidUtils,
    Options,
    Solid,
    GeometryInstance,
    GeometryObject,
    Line,
    XYZ,
    Transform,
    RevitLinkInstance,
    LocationCurve,
    ConnectorProfileType,
    ElementId,
    DirectShape,
    CurveLoop,
    GeometryCreationUtilities,
    Workset,
    Level,
    ExternalDefinitionCreationOptions,
)
from pyrevit import revit, forms, script
from System.Collections.Generic import List as NetList

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows import Visibility
from System.Windows.Markup import XamlReader

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
logger = script.get_logger()


def _id_int(eid):
    """Numeric value of an ElementId on any Revit version.

    ``ElementId.IntegerValue`` was removed in Revit 2026 and ``Value``
    only exists from Revit 2024 on, so both spellings must be tried.
    (WorksetId keeps ``IntegerValue`` on every version — do not use
    this helper for WorksetId.)
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


FEET_TO_MM = 304.8
MM_TO_FEET = 1.0 / 304.8
MERGE_GAP_MM = 50.0
MERGE_GAP_FEET = MERGE_GAP_MM * MM_TO_FEET
MERGE_DIRECTION_DOT_TOLERANCE = math.cos(math.radians(5.0))

# Every sleeve name starts with this prefix; used to detect sleeves that
# already exist in the model so re-runs do not stack duplicates.
SLEEVE_NAME_PREFIX = "Sleeve "

# Standard catalogue opening sizes (mm) used to snap sleeve dimensions up.
STANDARD_SIZES_MM = [
    50, 75, 100, 125, 150, 200, 250, 300,
    350, 400, 450, 500, 600, 700, 800,
]

# A penetration whose internal length exceeds (host thickness * this ratio)
# is treated as a grazing/parallel run and skipped when the filter is on.
GRAZING_RATIO = 4.0

# A penetration shorter than this is treated as a surface clip (MEP centerline
# barely touching the host face) and is always skipped — it is not a real
# through-penetration regardless of any UI setting.
MIN_PENETRATION_MM = 20.0

# Default status written to every new sleeve for the coordination workflow.
DEFAULT_STATUS = "Novo"

# Human-readable MEP service labels keyed by BuiltInCategory int value.
MEP_SERVICE_LABELS = {
    int(BuiltInCategory.OST_PipeCurves): "Tubulacao",
    int(BuiltInCategory.OST_FlexPipeCurves): "Tubo Flex",
    int(BuiltInCategory.OST_DuctCurves): "Duto",
    int(BuiltInCategory.OST_FlexDuctCurves): "Duto Flex",
    int(BuiltInCategory.OST_Conduit): "Eletroduto",
    int(BuiltInCategory.OST_CableTray): "Eletrocalha",
}

# Shared parameters created/bound to Generic Model (DirectShape sleeves).
# Order matters: F1 = opening size, F2 = mark, F3 = bottom offset to level.
ARI_PARAM_GROUP = "SLEEVES"
ARI_PARAM_DIM = "ARI-F1"
ARI_PARAM_MARK = "ARI-F2"
ARI_PARAM_COTA = "ARI-F3"
ARI_PARAM_NAMES = [ARI_PARAM_DIM, ARI_PARAM_MARK, ARI_PARAM_COTA]

# ============================================================
# MEP categories to scan
# ============================================================
MEP_CATS = [
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_FlexPipeCurves,
]

HOST_CATS = {
    "Walls": BuiltInCategory.OST_Walls,
    "Floors": BuiltInCategory.OST_Floors,
    "Structural Columns": BuiltInCategory.OST_StructuralColumns,
    "Structural Framing": BuiltInCategory.OST_StructuralFraming,
    "Structural Foundations": BuiltInCategory.OST_StructuralFoundation,
    "Roofs": BuiltInCategory.OST_Roofs,
    "Ceilings": BuiltInCategory.OST_Ceilings,
}

TEMP_WORKSET_NAME = "TEMP-Workset"


# ============================================================
# WORKSET HELPER
# ============================================================

def get_user_worksets(document):
    """Return dict of {name: workset_id} for all user worksets."""
    if not document.IsWorkshared:
        return {}
    result = {}
    for ws in FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset):
        result[ws.Name] = ws.Id
    return result


def get_or_create_workset(document, workset_name):
    """Get existing workset by name or create it. Returns WorksetId."""
    if not document.IsWorkshared:
        return None
    for ws in FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset):
        if ws.Name == workset_name:
            return ws.Id
    new_ws = Workset.Create(document, workset_name)
    return new_ws.Id


# ============================================================
# GEOMETRY HELPERS
# ============================================================

def get_solid(element):
    """Extract the largest Solid from an element."""
    opt = Options()
    opt.ComputeReferences = True
    geom = element.get_Geometry(opt)
    if geom is None:
        return None
    best = None
    best_vol = 0
    for g in geom:
        if isinstance(g, Solid) and g.Volume > best_vol:
            best = g
            best_vol = g.Volume
        elif isinstance(g, GeometryInstance):
            for gi in g.GetInstanceGeometry():
                if isinstance(gi, Solid) and gi.Volume > best_vol:
                    best = gi
                    best_vol = gi.Volume
    return best


def get_mep_curve(element):
    """Get the LocationCurve from an MEP element."""
    loc = element.Location
    if isinstance(loc, LocationCurve):
        return loc.Curve
    return None


def get_mep_direction(curve):
    """Get normalized direction vector of an MEP curve."""
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    d = XYZ(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z)
    length = d.GetLength()
    if length < 1e-9:
        return None
    return d.Normalize()


def get_mep_dimensions(element):
    """Get shape, dimensions and cross-section orientation from connectors."""
    try:
        cm = element.ConnectorManager
        if cm is None:
            return None
        for conn in cm.Connectors:
            if conn.Shape == ConnectorProfileType.Round:
                return {"shape": "round", "diameter": conn.Radius * 2.0}
            elif conn.Shape == ConnectorProfileType.Rectangular:
                orientation = None
                try:
                    cs = conn.CoordinateSystem
                    if cs is not None:
                        # BasisX = width direction in connector space
                        orientation = cs.BasisX
                except Exception:
                    pass
                return {
                    "shape": "rectangular",
                    "width": conn.Width,
                    "height": conn.Height,
                    "orientation": orientation,
                }
    except Exception:
        pass
    for bip in [
        BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
        BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
    ]:
        try:
            p = element.get_Parameter(bip)
            if p and p.HasValue and p.AsDouble() > 0:
                return {"shape": "round", "diameter": p.AsDouble()}
        except Exception:
            pass
    for w_bip, h_bip in [
        (BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
         BuiltInParameter.RBS_CURVE_HEIGHT_PARAM),
    ]:
        try:
            pw = element.get_Parameter(w_bip)
            ph = element.get_Parameter(h_bip)
            if pw and ph and pw.HasValue and ph.HasValue:
                return {
                    "shape": "rectangular",
                    "width": pw.AsDouble(),
                    "height": ph.AsDouble(),
                }
        except Exception:
            pass
    return None


def get_insulation_thickness(element):
    """Get insulation thickness if present."""
    try:
        p = element.get_Parameter(
            BuiltInParameter.RBS_REFERENCE_INSULATION_THICKNESS
        )
        if p and p.HasValue:
            return p.AsDouble()
    except Exception:
        pass
    return 0.0


def get_penetration(host_solid, mep_curve):
    """Get entry, exit, center, length and direction of penetration."""
    opts = SolidCurveIntersectionOptions()
    opts.ResultType = SolidCurveIntersectionMode.CurveSegmentsInside
    result = host_solid.IntersectWithCurve(mep_curve, opts)
    if result.SegmentCount == 0:
        return None
    seg = result.GetCurveSegment(0)
    entry = seg.GetEndPoint(0)
    exit_pt = seg.GetEndPoint(1)

    # If an MEP curve endpoint lies on the intersection boundary, the element
    # terminates inside the host (e.g. a stub connecting to embedded equipment)
    # rather than passing through it — not a real through-penetration.
    _ep_tol = 10.0 * MM_TO_FEET  # 10 mm
    _p0 = mep_curve.GetEndPoint(0)
    _p1 = mep_curve.GetEndPoint(1)
    if (min(entry.DistanceTo(_p0), entry.DistanceTo(_p1)) < _ep_tol or
            min(exit_pt.DistanceTo(_p0), exit_pt.DistanceTo(_p1)) < _ep_tol):
        return None

    center = XYZ(
        (entry.X + exit_pt.X) / 2.0,
        (entry.Y + exit_pt.Y) / 2.0,
        (entry.Z + exit_pt.Z) / 2.0,
    )
    length = entry.DistanceTo(exit_pt)
    if length > 1e-9:
        pen_dir = XYZ(
            (exit_pt.X - entry.X) / length,
            (exit_pt.Y - entry.Y) / length,
            (exit_pt.Z - entry.Z) / length,
        )
    else:
        pen_dir = None
    return {
        "entry": entry,
        "exit": exit_pt,
        "center": center,
        "length": length,
        "direction": pen_dir,
    }


# ============================================================
# CLASH DETECTION
# ============================================================

def _make_id_list(element_ids):
    """Create a .NET List<ElementId> from a Python iterable."""
    net_ids = NetList[ElementId]()
    for eid in element_ids:
        net_ids.Add(eid)
    return net_ids


# ---- Caches (reset per run) ----
_solid_cache = {}
_host_cache = {}   # {(doc_hash, bic_int): [(element, bb_min, bb_max), ...]}
_dims_cache = {}   # {element_id_int: sleeve_size_dict}


def _reset_caches():
    """Clear all per-run caches."""
    global _solid_cache, _host_cache, _dims_cache
    _solid_cache = {}
    _host_cache = {}
    _dims_cache = {}


def _get_solid_cached(element):
    """get_solid with per-run memoization."""
    eid = _id_int(element.Id)
    if eid not in _solid_cache:
        _solid_cache[eid] = get_solid(element)
    return _solid_cache[eid]


def _get_sleeve_size_cached(mep_element, clearance_mm, shape_mode,
                            snap_standard=False):
    """compute_sleeve_size with per-run memoization."""
    eid = _id_int(mep_element.Id)
    if eid not in _dims_cache:
        _dims_cache[eid] = compute_sleeve_size(
            mep_element, clearance_mm, shape_mode, snap_standard
        )
    return _dims_cache[eid]

def _preload_hosts(target_doc, host_bic):
    """Collect all hosts of a category once, cache with bounding boxes."""
    key = (id(target_doc), int(host_bic))
    if key in _host_cache:
        return _host_cache[key]
    elements = list(
        FilteredElementCollector(target_doc)
        .OfCategory(host_bic)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    cached = []
    for el in elements:
        bb = el.get_BoundingBox(None)
        if bb is not None:
            cached.append((el, bb.Min, bb.Max))
    _host_cache[key] = cached
    return cached


def _bb_overlaps(a_min, a_max, b_min, b_max, tol):
    """Fast AABB overlap test."""
    return (
        a_min.X - tol <= b_max.X and a_max.X + tol >= b_min.X
        and a_min.Y - tol <= b_max.Y and a_max.Y + tol >= b_min.Y
        and a_min.Z - tol <= b_max.Z and a_max.Z + tol >= b_min.Z
    )


def _bb_overlaps_transformed(a_min, a_max, b_min, b_max, inv_xf, tol):
    """AABB overlap after transforming a into link space."""
    mn = inv_xf.OfPoint(a_min)
    mx = inv_xf.OfPoint(a_max)
    t_min = XYZ(min(mn.X, mx.X), min(mn.Y, mx.Y), min(mn.Z, mx.Z))
    t_max = XYZ(max(mn.X, mx.X), max(mn.Y, mx.Y), max(mn.Z, mx.Z))
    return _bb_overlaps(t_min, t_max, b_min, b_max, tol)


def find_clashing_hosts(mep_element, host_bic, target_doc, link_xform=None):
    """Find host elements that intersect an MEP element (cached)."""
    bb = mep_element.get_BoundingBox(None)
    if bb is None:
        return []

    tol = 0.5
    all_hosts = _preload_hosts(target_doc, host_bic)
    if not all_hosts:
        return []

    # Fast Python-side bounding box pre-filter
    if link_xform and not link_xform.AlmostEqual(Transform.Identity):
        inv = link_xform.Inverse
        candidates = [
            h for h, h_min, h_max in all_hosts
            if _bb_overlaps_transformed(
                bb.Min, bb.Max, h_min, h_max, inv, tol
            )
        ]
    else:
        candidates = [
            h for h, h_min, h_max in all_hosts
            if _bb_overlaps(bb.Min, bb.Max, h_min, h_max, tol)
        ]

    if not candidates:
        return []

    # Precise geometric intersection only on survivors
    if link_xform and not link_xform.AlmostEqual(Transform.Identity):
        mep_solid = _get_solid_cached(mep_element)
        if mep_solid is None:
            return candidates
        try:
            transformed = SolidUtils.CreateTransformed(
                mep_solid, link_xform.Inverse
            )
            filt = ElementIntersectsSolidFilter(transformed)
            ids = _make_id_list([c.Id for c in candidates])
            return list(
                FilteredElementCollector(target_doc, ids)
                .WherePasses(filt)
                .ToElements()
            )
        except Exception as ex:
            logger.debug("Link solid filter error: {}".format(ex))
            return candidates
    else:
        try:
            filt = ElementIntersectsElementFilter(mep_element)
            ids = _make_id_list([c.Id for c in candidates])
            return list(
                FilteredElementCollector(target_doc, ids)
                .WherePasses(filt)
                .ToElements()
            )
        except Exception as ex:
            logger.debug("Element filter error: {}".format(ex))
            return candidates


# ============================================================
# DIRECTSHAPE SLEEVE CREATION
# ============================================================

def _get_perpendicular(direction):
    """Get a vector perpendicular to direction."""
    if abs(direction.Z) < 0.9:
        ref = XYZ(0, 0, 1)
    else:
        ref = XYZ(1, 0, 0)
    perp = direction.CrossProduct(ref)
    return perp.Normalize()


def create_cylinder_solid(center, direction, radius, length):
    """Create a cylinder solid centered at point, along direction."""
    half = length / 2.0
    start = XYZ(
        center.X - direction.X * half,
        center.Y - direction.Y * half,
        center.Z - direction.Z * half,
    )

    perp1 = _get_perpendicular(direction)
    perp2 = direction.CrossProduct(perp1).Normalize()

    n_seg = 24
    step = 2.0 * math.pi / n_seg
    points = []
    for i in range(n_seg):
        a = i * step
        cos_a = math.cos(a)
        sin_a = math.sin(a)
        pt = XYZ(
            start.X + radius * (cos_a * perp1.X + sin_a * perp2.X),
            start.Y + radius * (cos_a * perp1.Y + sin_a * perp2.Y),
            start.Z + radius * (cos_a * perp1.Z + sin_a * perp2.Z),
        )
        points.append(pt)

    profile = CurveLoop()
    for i in range(n_seg):
        profile.Append(Line.CreateBound(points[i], points[(i + 1) % n_seg]))

    profiles = NetList[CurveLoop]()
    profiles.Add(profile)

    return GeometryCreationUtilities.CreateExtrusionGeometry(
        profiles, direction, length
    )


def create_box_solid(center, direction, width, height, length,
                     orientation=None):
    """Create a rectangular box solid centered at point, along direction.

    orientation: optional XYZ vector defining the 'width' axis of the
    cross-section.  When provided the box aligns with the real MEP
    element orientation instead of an arbitrary perpendicular.
    """
    half_len = length / 2.0
    half_w = width / 2.0
    half_h = height / 2.0

    start = XYZ(
        center.X - direction.X * half_len,
        center.Y - direction.Y * half_len,
        center.Z - direction.Z * half_len,
    )

    if orientation is not None:
        # Remove any component along the extrusion direction so the
        # orientation lives entirely in the cross-section plane.
        dot = orientation.DotProduct(direction)
        proj = XYZ(
            orientation.X - dot * direction.X,
            orientation.Y - dot * direction.Y,
            orientation.Z - dot * direction.Z,
        )
        if proj.GetLength() > 1e-9:
            perp1 = proj.Normalize()
        else:
            perp1 = _get_perpendicular(direction)
    else:
        perp1 = _get_perpendicular(direction)
    perp2 = direction.CrossProduct(perp1).Normalize()

    corners = [
        XYZ(
            start.X + half_w * perp1.X + half_h * perp2.X,
            start.Y + half_w * perp1.Y + half_h * perp2.Y,
            start.Z + half_w * perp1.Z + half_h * perp2.Z,
        ),
        XYZ(
            start.X - half_w * perp1.X + half_h * perp2.X,
            start.Y - half_w * perp1.Y + half_h * perp2.Y,
            start.Z - half_w * perp1.Z + half_h * perp2.Z,
        ),
        XYZ(
            start.X - half_w * perp1.X - half_h * perp2.X,
            start.Y - half_w * perp1.Y - half_h * perp2.Y,
            start.Z - half_w * perp1.Z - half_h * perp2.Z,
        ),
        XYZ(
            start.X + half_w * perp1.X - half_h * perp2.X,
            start.Y + half_w * perp1.Y - half_h * perp2.Y,
            start.Z + half_w * perp1.Z - half_h * perp2.Z,
        ),
    ]

    profile = CurveLoop()
    for i in range(4):
        profile.Append(Line.CreateBound(corners[i], corners[(i + 1) % 4]))

    profiles = NetList[CurveLoop]()
    profiles.Add(profile)

    return GeometryCreationUtilities.CreateExtrusionGeometry(
        profiles, direction, length
    )


def _snap_up_feet(value_feet):
    """Round a dimension (feet) up to the next standard catalogue size."""
    value_mm = value_feet * FEET_TO_MM
    for size_mm in STANDARD_SIZES_MM:
        if size_mm >= value_mm - 0.5:
            return size_mm * MM_TO_FEET
    # Larger than the catalogue: round up to the next 50 mm increment.
    next_mm = math.ceil(value_mm / 50.0) * 50.0
    return next_mm * MM_TO_FEET


def snap_sleeve_size(sleeve_size):
    """Return a copy of sleeve_size snapped up to standard sizes."""
    snapped = dict(sleeve_size)
    if snapped["shape"] == "round":
        snapped["diameter"] = _snap_up_feet(snapped["diameter"])
    else:
        snapped["width"] = _snap_up_feet(snapped["width"])
        snapped["height"] = _snap_up_feet(snapped["height"])
    return snapped


def compute_sleeve_size(mep_element, clearance_mm, shape_mode="both",
                        snap_standard=False):
    """Compute sleeve dimensions from MEP element.

    shape_mode: 'round', 'rectangular', or 'both' (auto from MEP geometry).
    snap_standard: round the result up to a standard catalogue size.
    """
    dims = get_mep_dimensions(mep_element)
    insulation = get_insulation_thickness(mep_element)
    clearance_ft = clearance_mm * MM_TO_FEET

    if dims is None:
        default_d = 100.0 * MM_TO_FEET + 2 * clearance_ft
        result = {"shape": "round", "diameter": default_d}
        return snap_sleeve_size(result) if snap_standard else result

    if dims["shape"] == "round":
        sleeve_d = dims["diameter"] + 2 * insulation + 2 * clearance_ft
        if shape_mode == "rectangular":
            # Force rectangular: use diameter as both width and height
            result = {"shape": "rectangular",
                      "width": sleeve_d, "height": sleeve_d}
        else:
            result = {"shape": "round", "diameter": sleeve_d}
    else:
        sleeve_w = dims["width"] + 2 * insulation + 2 * clearance_ft
        sleeve_h = dims["height"] + 2 * insulation + 2 * clearance_ft
        orientation = dims.get("orientation")
        if shape_mode == "round":
            # Force round: use the larger dimension as diameter
            sleeve_d = max(sleeve_w, sleeve_h)
            result = {"shape": "round", "diameter": sleeve_d}
        else:
            result = {"shape": "rectangular",
                      "width": sleeve_w, "height": sleeve_h}
            if orientation is not None:
                result["orientation"] = orientation

    if snap_standard:
        orientation = result.get("orientation")
        result = snap_sleeve_size(result)
        if orientation is not None:
            result["orientation"] = orientation
    return result


def _format_mm(feet_val):
    """Convert feet to mm and return formatted string."""
    return "{:.0f}".format(feet_val * FEET_TO_MM)


def _build_sleeve_name(sleeve_size, sleeve_length):
    """Build a descriptive name with dimensions in mm."""
    length_mm = _format_mm(sleeve_length)
    if sleeve_size["shape"] == "round":
        d_mm = _format_mm(sleeve_size["diameter"])
        return "Sleeve Round D{}mm L{}mm".format(d_mm, length_mm)
    else:
        w_mm = _format_mm(sleeve_size["width"])
        h_mm = _format_mm(sleeve_size["height"])
        return "Sleeve Rect {}x{}mm L{}mm".format(w_mm, h_mm, length_mm)


def collect_existing_sleeve_points(document):
    """Return bbox centers of sleeves already present in the model.

    Used to seed the duplicate filter so running the tool again does not
    stack a new sleeve on top of an existing one.
    """
    points = []
    try:
        collector = (
            FilteredElementCollector(document)
            .OfClass(DirectShape)
            .OfCategory(BuiltInCategory.OST_GenericModel)
        )
    except Exception:
        return points
    for el in collector:
        try:
            name = el.Name or ""
        except Exception:
            name = ""
        if not name.startswith(SLEEVE_NAME_PREFIX):
            continue
        try:
            bb = el.get_BoundingBox(None)
        except Exception:
            bb = None
        if bb is None:
            continue
        points.append(XYZ(
            (bb.Min.X + bb.Max.X) / 2.0,
            (bb.Min.Y + bb.Max.Y) / 2.0,
            (bb.Min.Z + bb.Max.Z) / 2.0,
        ))
    return points


def host_thickness_feet(host):
    """Approximate host thickness as the smallest bounding-box dimension."""
    try:
        bb = host.get_BoundingBox(None)
        if bb is None:
            return 0.0
        return min(
            bb.Max.X - bb.Min.X,
            bb.Max.Y - bb.Min.Y,
            bb.Max.Z - bb.Min.Z,
        )
    except Exception:
        return 0.0


def _host_type_name(host):
    """Return the host's family/type name when available."""
    try:
        type_el = host.Document.GetElement(host.GetTypeId())
        if type_el is not None and type_el.Name:
            return type_el.Name
    except Exception:
        pass
    return "?"


def _level_name(element):
    """Best-effort level name for an MEP/host element."""
    try:
        lid = element.LevelId
        if lid is not None and _id_int(lid) > 0:
            lvl = element.Document.GetElement(lid)
            if lvl is not None:
                return lvl.Name
    except Exception:
        pass
    for bip_name in (
        "RBS_START_LEVEL_PARAM",
        "FAMILY_LEVEL_PARAM",
        "SCHEDULE_LEVEL_PARAM",
    ):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is None:
            continue
        try:
            p = element.get_Parameter(bip)
            if p and p.HasValue:
                lvl = element.Document.GetElement(p.AsElementId())
                if lvl is not None:
                    return lvl.Name
        except Exception:
            pass
    return "?"


def _mep_system_name(mep_element):
    """Return the MEP system/type name when available."""
    for bip_name in (
        "RBS_PIPING_SYSTEM_TYPE_PARAM",
        "RBS_DUCT_SYSTEM_TYPE_PARAM",
        "RBS_SYSTEM_NAME_PARAM",
    ):
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is None:
            continue
        try:
            p = mep_element.get_Parameter(bip)
            if p and p.HasValue:
                val = p.AsValueString() or p.AsString()
                if val:
                    return val
        except Exception:
            pass
    return ""


def _mep_service_label(mep_element):
    """Return a Portuguese service label based on the MEP category."""
    try:
        cat_int = _id_int(mep_element.Category.Id)
        return MEP_SERVICE_LABELS.get(cat_int, "MEP")
    except Exception:
        return "MEP"


def _mep_nominal_label(mep_element):
    """Return a nominal size label, e.g. 'DN100' or '300x200'."""
    dims = get_mep_dimensions(mep_element)
    if dims is None:
        return "?"
    if dims["shape"] == "round":
        return "DN{:.0f}".format(dims["diameter"] * FEET_TO_MM)
    return "{:.0f}x{:.0f}".format(
        dims["width"] * FEET_TO_MM, dims["height"] * FEET_TO_MM
    )


def get_mep_nominal_mm(mep_element):
    """Largest nominal cross-section dimension in mm (None if unknown)."""
    dims = get_mep_dimensions(mep_element)
    if dims is None:
        return None
    if dims["shape"] == "round":
        return dims["diameter"] * FEET_TO_MM
    return max(dims["width"], dims["height"]) * FEET_TO_MM


def _sleeve_opening_label(sleeve_size):
    """Return the opening label, e.g. 'D150' or '300x200'."""
    if sleeve_size["shape"] == "round":
        return "D{:.0f}".format(sleeve_size["diameter"] * FEET_TO_MM)
    return "{:.0f}x{:.0f}".format(
        sleeve_size["width"] * FEET_TO_MM,
        sleeve_size["height"] * FEET_TO_MM,
    )


# ============================================================
# SLEEVES SHARED PARAMETERS (organized columns for the schedule)
# ============================================================

def _foro_dimension_label(sleeve_size):
    """Opening size as a structural engineer reads it, in mm.

    Round  -> 'Oe150 mm' (diameter symbol)
    Rect   -> '375x125 mm' (multiplication sign)
    """
    if sleeve_size["shape"] == "round":
        return u"\u00d8{:.0f} mm".format(sleeve_size["diameter"] * FEET_TO_MM)
    return u"{:.0f}\u00d7{:.0f} mm".format(
        sleeve_size["width"] * FEET_TO_MM,
        sleeve_size["height"] * FEET_TO_MM,
    )


def collect_levels_sorted(document):
    """Return [(project_elevation_ft, name), ...] ascending."""
    levels = list(
        FilteredElementCollector(document)
        .OfClass(Level)
        .ToElements()
    )
    pairs = []
    for lvl in levels:
        try:
            pairs.append((lvl.ProjectElevation, lvl.Name))
        except Exception:
            pass
    pairs.sort(key=lambda p: p[0])
    return pairs


def _nearest_level_below(levels_sorted, z_ft):
    """Return the (elev, name) of the closest level at or below z."""
    chosen = None
    for elev, name in levels_sorted:
        if elev <= z_ft + 1e-6:
            chosen = (elev, name)
        else:
            break
    if chosen is None and levels_sorted:
        chosen = levels_sorted[0]
    return chosen


def cota_fundo_label(directshape, levels_sorted):
    """Bottom-of-opening offset relative to the reference level, in mm."""
    try:
        bb = directshape.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        return ""
    bottom_z = bb.Min.Z
    lvl = _nearest_level_below(levels_sorted, bottom_z)
    if lvl is None:
        return u"{:+.0f} mm".format(bottom_z * FEET_TO_MM)
    elev, name = lvl
    delta_mm = (bottom_z - elev) * FEET_TO_MM
    return u"{:+.0f} mm ({})".format(delta_mm, name)


def _text_param_spec():
    """Return the 'Text' parameter type for the running Revit version."""
    try:
        from Autodesk.Revit.DB import SpecTypeId
        return SpecTypeId.String.Text
    except Exception:
        from Autodesk.Revit.DB import ParameterType
        return ParameterType.Text


def _data_param_group():
    """Return the 'Data' parameter group for the running Revit version.

    Revit 2024+ replaced BuiltInParameterGroup with GroupTypeId; older
    versions only have BuiltInParameterGroup. Returns None if neither is
    available (caller falls back to the 2-argument Insert).
    """
    try:
        from Autodesk.Revit.DB import GroupTypeId
        return GroupTypeId.Data
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import BuiltInParameterGroup
        return BuiltInParameterGroup.PG_DATA
    except Exception:
        return None


def ensure_ari_params(document):
    """Create (if missing) and bind ARI-F* text params to Generic Model.

    Returns True when the parameters are available on the category.
    Must be called inside a transaction (parameter binding insert).
    """
    app = document.Application

    # Ensure a shared parameter file exists (use a temp one if none set).
    path = app.SharedParametersFilename
    if not path or not os.path.exists(path):
        tmp = os.path.join(
            tempfile.gettempdir(), "sleeves_shared_params.txt"
        )
        if not os.path.exists(tmp):
            handle = open(tmp, "w")
            handle.close()
        app.SharedParametersFilename = tmp

    sp_file = app.OpenSharedParameterFile()
    if sp_file is None:
        return False

    # Get or create the SLEEVES group.
    group = None
    for grp in sp_file.Groups:
        if grp.Name == ARI_PARAM_GROUP:
            group = grp
            break
    if group is None:
        group = sp_file.Groups.Create(ARI_PARAM_GROUP)

    spec = _text_param_spec()
    definitions = {}
    for name in ARI_PARAM_NAMES:
        ext_def = None
        for existing in group.Definitions:
            if existing.Name == name:
                ext_def = existing
                break
        if ext_def is None:
            opt = ExternalDefinitionCreationOptions(name, spec)
            ext_def = group.Definitions.Create(opt)
        definitions[name] = ext_def

    # Bind each definition to the Generic Model category (instance).
    gm_cat = document.Settings.Categories.get_Item(
        BuiltInCategory.OST_GenericModel
    )
    cat_set = app.Create.NewCategorySet()
    cat_set.Insert(gm_cat)
    binding = app.Create.NewInstanceBinding(cat_set)

    bindings_map = document.ParameterBindings
    param_group = _data_param_group()
    for name, ext_def in definitions.items():
        if bindings_map.Contains(ext_def):
            continue
        inserted = False
        if param_group is not None:
            try:
                bindings_map.Insert(ext_def, binding, param_group)
                inserted = True
            except Exception:
                inserted = False
        if not inserted:
            try:
                bindings_map.Insert(ext_def, binding)
            except Exception as ex:
                logger.debug("ARI bind error {}: {}".format(name, ex))
    return True


def set_ari_params(directshape, dimension, mark, cota):
    """Write the three organized values onto a sleeve DirectShape."""
    values = {
        ARI_PARAM_DIM: dimension,
        ARI_PARAM_MARK: mark,
        ARI_PARAM_COTA: cota,
    }
    for name, value in values.items():
        if value is None:
            continue
        try:
            p = directshape.LookupParameter(name)
            if p is not None and not p.IsReadOnly:
                p.Set(value)
        except Exception:
            pass


def set_ari_cota(directshape, levels_sorted):
    """Set only ARI-F3 (bottom-of-opening offset).

    Requires the document to have been regenerated so the DirectShape
    bounding box is available.
    """
    try:
        cota = cota_fundo_label(directshape, levels_sorted)
    except Exception:
        cota = ""
    if not cota:
        return
    try:
        p = directshape.LookupParameter(ARI_PARAM_COTA)
        if p is not None and not p.IsReadOnly:
            p.Set(cota)
    except Exception:
        pass


def place_directshape_sleeve(document, center, mep_direction, sleeve_size,
                             sleeve_length, workset_id=None,
                             comments=None, mark=None):
    """Create a DirectShape sleeve at the penetration point."""
    if sleeve_size["shape"] == "round":
        radius = sleeve_size["diameter"] / 2.0
        solid = create_cylinder_solid(
            center, mep_direction, radius, sleeve_length
        )
    else:
        solid = create_box_solid(
            center, mep_direction,
            sleeve_size["width"], sleeve_size["height"],
            sleeve_length,
            sleeve_size.get("orientation"),
        )

    cat_id = ElementId(BuiltInCategory.OST_GenericModel)
    ds = DirectShape.CreateElement(document, cat_id)

    geom_list = NetList[GeometryObject]()
    geom_list.Add(solid)
    ds.SetShape(geom_list)

    name = _build_sleeve_name(sleeve_size, sleeve_length)
    ds.SetName(name)

    # Coordination data lives only in the ARI-F* parameters; native Comments
    # and Mark are left untouched to avoid duplicated information.

    # Assign workset
    if workset_id is not None:
        wp = ds.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if wp and not wp.IsReadOnly:
            wp.Set(workset_id.IntegerValue)

    return ds


def is_duplicate(point, existing_points, tolerance=0.1):
    """Check if a sleeve already exists near this point."""
    for ep in existing_points:
        if point.DistanceTo(ep) < tolerance:
            return True
    return False


class SpatialHashGrid(object):
    """Spatial hash for fast nearby-point lookups."""

    def __init__(self, cell_size=0.5):
        self._cell = cell_size
        self._grid = {}
        self._points = []

    def _key(self, pt):
        return (
            int(math.floor(pt.X / self._cell)),
            int(math.floor(pt.Y / self._cell)),
            int(math.floor(pt.Z / self._cell)),
        )

    def add(self, pt):
        k = self._key(pt)
        self._grid.setdefault(k, []).append(pt)
        self._points.append(pt)

    def has_nearby(self, pt, tolerance):
        cx, cy, cz = self._key(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    bucket = self._grid.get((cx + dx, cy + dy, cz + dz))
                    if bucket:
                        for ep in bucket:
                            if pt.DistanceTo(ep) < tolerance:
                                return True
        return False

    def all_points(self):
        return self._points


def _canonicalize_direction(direction):
    """Normalize direction and keep a stable sign for grouping."""
    norm = direction.Normalize()
    for comp in (norm.X, norm.Y, norm.Z):
        if abs(comp) > 1e-9:
            if comp < 0:
                return XYZ(-norm.X, -norm.Y, -norm.Z)
            break
    return norm


def _make_host_key(source_tag, host_id):
    """Create a stable grouping key for a host element."""
    return "{}:{}".format(source_tag, _id_int(host_id))


def _project_point(point, axis_u, axis_v, axis_w):
    """Project a point to a local orthonormal basis."""
    return (
        point.DotProduct(axis_u),
        point.DotProduct(axis_v),
        point.DotProduct(axis_w),
    )


def _point_from_basis(u, v, w, axis_u, axis_v, axis_w):
    """Build a point from coordinates in a local orthonormal basis."""
    return XYZ(
        axis_u.X * u + axis_v.X * v + axis_w.X * w,
        axis_u.Y * u + axis_v.Y * v + axis_w.Y * w,
        axis_u.Z * u + axis_v.Z * v + axis_w.Z * w,
    )


def _get_sleeve_half_extents(sleeve_size):
    """Return half extents on the local cross-section axes."""
    if sleeve_size["shape"] == "round":
        radius = sleeve_size["diameter"] / 2.0
        return radius, radius
    return sleeve_size["width"] / 2.0, sleeve_size["height"] / 2.0


def _build_sleeve_record(directshape, center, direction, sleeve_size,
                         sleeve_length, host_key, workset_id=None,
                         host_desc="", level="?", mark=""):
    """Store metadata required for post-processing merge."""
    return {
        "ds_id": directshape.Id,
        "center": center,
        "direction": _canonicalize_direction(direction),
        "size": dict(sleeve_size),
        "length": sleeve_length,
        "host_key": host_key,
        "workset_id": workset_id,
        "host_desc": host_desc,
        "level": level,
        "mark": mark,
    }


def _get_sleeve_envelope(record, axis_u, axis_v, axis_w):
    """Return sleeve extents in a local basis."""
    center_u, center_v, center_w = _project_point(
        record["center"], axis_u, axis_v, axis_w
    )
    half_u, half_v = _get_sleeve_half_extents(record["size"])
    half_w = record["length"] / 2.0
    return {
        "u_min": center_u - half_u,
        "u_max": center_u + half_u,
        "v_min": center_v - half_v,
        "v_max": center_v + half_v,
        "w_min": center_w - half_w,
        "w_max": center_w + half_w,
    }


def _interval_gap(min_a, max_a, min_b, max_b):
    """Return separation between 1D intervals."""
    if max_a < min_b:
        return min_b - max_a
    if max_b < min_a:
        return min_a - max_b
    return 0.0


def _get_oriented_axes(direction, record_a, record_b=None):
    """Build an orthonormal basis using real orientation when available."""
    axis_w = direction
    orientation = record_a["size"].get("orientation")
    if orientation is None and record_b is not None:
        orientation = record_b["size"].get("orientation")
    if orientation is not None:
        dot = orientation.DotProduct(axis_w)
        proj = XYZ(
            orientation.X - dot * axis_w.X,
            orientation.Y - dot * axis_w.Y,
            orientation.Z - dot * axis_w.Z,
        )
        if proj.GetLength() > 1e-9:
            axis_u = proj.Normalize()
        else:
            axis_u = _get_perpendicular(axis_w)
    else:
        axis_u = _get_perpendicular(axis_w)
    axis_v = axis_w.CrossProduct(axis_u).Normalize()
    return axis_u, axis_v, axis_w


def _can_merge_records(record_a, record_b, gap_tolerance):
    """Check if two sleeves should be consolidated."""
    if record_a["host_key"] != record_b["host_key"]:
        return False

    direction_a = record_a["direction"]
    direction_b = record_b["direction"]
    if abs(direction_a.DotProduct(direction_b)) < MERGE_DIRECTION_DOT_TOLERANCE:
        return False

    axis_u, axis_v, axis_w = _get_oriented_axes(
        direction_a, record_a, record_b
    )

    env_a = _get_sleeve_envelope(record_a, axis_u, axis_v, axis_w)
    env_b = _get_sleeve_envelope(record_b, axis_u, axis_v, axis_w)

    gap_u = _interval_gap(
        env_a["u_min"], env_a["u_max"], env_b["u_min"], env_b["u_max"]
    )
    gap_v = _interval_gap(
        env_a["v_min"], env_a["v_max"], env_b["v_min"], env_b["v_max"]
    )
    gap_w = _interval_gap(
        env_a["w_min"], env_a["w_max"], env_b["w_min"], env_b["w_max"]
    )

    planar_gap = math.sqrt(gap_u * gap_u + gap_v * gap_v)
    return planar_gap <= gap_tolerance and gap_w <= gap_tolerance


def _get_merge_groups(records, gap_tolerance):
    """Build connected groups of sleeves that can be merged."""
    groups = []
    visited = set()

    for start_idx in range(len(records)):
        if start_idx in visited:
            continue

        stack = [start_idx]
        component = []

        while stack:
            current_idx = stack.pop()
            if current_idx in visited:
                continue

            visited.add(current_idx)
            component.append(records[current_idx])

            for other_idx in range(len(records)):
                if other_idx in visited:
                    continue
                if _can_merge_records(
                    records[current_idx], records[other_idx], gap_tolerance
                ):
                    stack.append(other_idx)

        if len(component) > 1:
            groups.append(component)

    return groups


def _build_merged_sleeve(group):
    """Create a merged sleeve envelope for a compatible group."""
    if len(group) < 2:
        return None

    axis_w = group[0]["direction"]

    # Try to recover real cross-section orientation from any record
    orientation = None
    for record in group:
        ori = record["size"].get("orientation")
        if ori is not None:
            orientation = ori
            break

    if orientation is not None:
        dot = orientation.DotProduct(axis_w)
        proj = XYZ(
            orientation.X - dot * axis_w.X,
            orientation.Y - dot * axis_w.Y,
            orientation.Z - dot * axis_w.Z,
        )
        if proj.GetLength() > 1e-9:
            axis_u = proj.Normalize()
        else:
            axis_u = _get_perpendicular(axis_w)
    else:
        axis_u = _get_perpendicular(axis_w)
    axis_v = axis_w.CrossProduct(axis_u).Normalize()

    u_min = float("inf")
    u_max = float("-inf")
    v_min = float("inf")
    v_max = float("-inf")
    w_min = float("inf")
    w_max = float("-inf")
    workset_id = None

    for record in group:
        env = _get_sleeve_envelope(record, axis_u, axis_v, axis_w)
        u_min = min(u_min, env["u_min"])
        u_max = max(u_max, env["u_max"])
        v_min = min(v_min, env["v_min"])
        v_max = max(v_max, env["v_max"])
        w_min = min(w_min, env["w_min"])
        w_max = max(w_max, env["w_max"])
        if workset_id is None and record["workset_id"] is not None:
            workset_id = record["workset_id"]

    width = u_max - u_min
    height = v_max - v_min
    length = w_max - w_min

    if width <= 1e-9 or height <= 1e-9 or length <= 1e-9:
        return None

    center = _point_from_basis(
        (u_min + u_max) / 2.0,
        (v_min + v_max) / 2.0,
        (w_min + w_max) / 2.0,
        axis_u,
        axis_v,
        axis_w,
    )

    merged_size = {
        "shape": "rectangular",
        "width": width,
        "height": height,
    }
    if orientation is not None:
        merged_size["orientation"] = orientation

    # Reuse the first available mark from the group for the merged sleeve.
    mark = ""
    for record in group:
        if not mark and record.get("mark"):
            mark = record["mark"]
            break
    merged_mark = (mark + "-M") if mark else ""

    return {
        "center": center,
        "direction": axis_w,
        "size": merged_size,
        "length": length,
        "workset_id": workset_id,
        "mark": merged_mark,
    }


def merge_created_sleeves(document, sleeve_records, gap_tolerance,
                          levels_sorted=None):
    """Merge nearby sleeves created during the current execution."""
    result = {
        "groups_merged": 0,
        "sleeves_removed": 0,
        "sleeves_created": 0,
        "failed_groups": 0,
    }

    if len(sleeve_records) < 2:
        return result

    if levels_sorted is None:
        levels_sorted = []

    records_by_host = {}
    for record in sleeve_records:
        records_by_host.setdefault(record["host_key"], []).append(record)

    merge_groups = []
    for host_records in records_by_host.values():
        if len(host_records) < 2:
            continue
        merge_groups.extend(_get_merge_groups(host_records, gap_tolerance))

    if not merge_groups:
        return result

    total_groups = len(merge_groups)
    new_sleeves = []  # merged DirectShapes pending the bottom-offset (ARI-F3)
    with revit.Transaction("Merge Nearby Sleeves"):
        for group_idx, group in enumerate(merge_groups):
            if group_idx % 10 == 0 or group_idx + 1 == total_groups:
                output.update_progress(group_idx + 1, total_groups)
            merged = _build_merged_sleeve(group)
            if merged is None:
                result["failed_groups"] += 1
                continue

            existing_ids = [
                record["ds_id"] for record in group
                if document.GetElement(record["ds_id"]) is not None
            ]
            if len(existing_ids) < 2:
                continue

            try:
                new_ds = place_directshape_sleeve(
                    document,
                    merged["center"],
                    merged["direction"],
                    merged["size"],
                    merged["length"],
                    merged["workset_id"],
                    None,
                    merged.get("mark"),
                )
                if new_ds is None:
                    result["failed_groups"] += 1
                    continue

                set_ari_params(
                    new_ds,
                    _foro_dimension_label(merged["size"]),
                    merged.get("mark"),
                    None,
                )

                for ds_id in existing_ids:
                    if document.GetElement(ds_id) is not None:
                        document.Delete(ds_id)

                new_sleeves.append(new_ds)
                result["groups_merged"] += 1
                result["sleeves_removed"] += len(existing_ids)
                result["sleeves_created"] += 1
            except Exception as ex:
                output.print_md("**Merge error** {} sleeves: {}".format(
                    len(existing_ids), ex))
                result["failed_groups"] += 1

        # Single regenerate for the whole batch, then write the bottom-of-
        # opening offset (ARI-F3) for every merged sleeve. Doing this once
        # instead of once per group avoids minutes of UI freeze on big models.
        if new_sleeves:
            try:
                document.Regenerate()
                for nds in new_sleeves:
                    set_ari_cota(nds, levels_sorted)
            except Exception:
                pass

    return result


# ============================================================
# COLLECT DATA
# ============================================================

def get_link_instances(target_doc):
    """Get all loaded Revit link instances."""
    links = list(
        FilteredElementCollector(target_doc)
        .OfClass(RevitLinkInstance)
        .ToElements()
    )
    result = {}
    for lnk in links:
        ld = lnk.GetLinkDocument()
        if ld:
            result[ld.Title] = lnk
    return result


# ============================================================
# XAML UI
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Place Sleeves"
    Width="580" SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Host Elements -->
    <GroupBox Grid.Row="0" Header="Host Elements" Margin="0,0,0,8">
      <StackPanel Margin="8">
        <CheckBox x:Name="chk_walls" Content="Walls"
                  IsChecked="True" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_floors" Content="Floors"
                  IsChecked="True" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_str_columns" Content="Structural Columns"
                  IsChecked="True" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_str_framing" Content="Structural Framing (Beams)"
                  IsChecked="True" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_str_foundations" Content="Structural Foundations"
                  IsChecked="False" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_roofs" Content="Roofs"
                  IsChecked="False" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_ceilings" Content="Ceilings"
                  IsChecked="False"/>
      </StackPanel>
    </GroupBox>

    <!-- Linked Models -->
    <GroupBox Grid.Row="1" Header="Linked Models (select for clash)" Margin="0,0,0,8">
      <StackPanel Margin="8">
        <ListBox x:Name="lst_links" Height="90"
                 SelectionMode="Multiple"
                 BorderThickness="1" BorderBrush="#CCC"/>
        <TextBlock x:Name="txt_no_links"
                   Text="No linked models loaded"
                   Foreground="#999" FontStyle="Italic"
                   Margin="0,4,0,0"/>
      </StackPanel>
    </GroupBox>

    <!-- MEP Categories -->
    <GroupBox Grid.Row="2"
              Header="MEP Categories (uncheck to skip a category entirely)"
              Margin="0,0,0,8">
      <Grid Margin="8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TextBlock Grid.Row="0" Grid.Column="1"
                   Text="Min &#216;/side (mm)" FontWeight="Bold"
                   Foreground="#666" FontSize="11"
                   HorizontalAlignment="Right" Margin="8,0,0,4"/>

        <CheckBox Grid.Row="1" Grid.Column="0" x:Name="chk_pipes"
                  Content="Pipes" IsChecked="True"
                  VerticalAlignment="Center" Margin="0,2,0,2"/>
        <TextBox Grid.Row="1" Grid.Column="1" x:Name="txt_min_pipes"
                 Text="50" Width="70" Height="24" Margin="8,2,0,2"
                 VerticalContentAlignment="Center"/>

        <CheckBox Grid.Row="2" Grid.Column="0" x:Name="chk_ducts"
                  Content="Ducts" IsChecked="True"
                  VerticalAlignment="Center" Margin="0,2,0,2"/>
        <TextBox Grid.Row="2" Grid.Column="1" x:Name="txt_min_ducts"
                 Text="50" Width="70" Height="24" Margin="8,2,0,2"
                 VerticalContentAlignment="Center"/>

        <CheckBox Grid.Row="3" Grid.Column="0" x:Name="chk_conduits"
                  Content="Conduits" IsChecked="True"
                  VerticalAlignment="Center" Margin="0,2,0,2"/>
        <TextBox Grid.Row="3" Grid.Column="1" x:Name="txt_min_conduits"
                 Text="50" Width="70" Height="24" Margin="8,2,0,2"
                 VerticalContentAlignment="Center"/>

        <CheckBox Grid.Row="4" Grid.Column="0" x:Name="chk_cable_trays"
                  Content="Cable Trays" IsChecked="True"
                  VerticalAlignment="Center" Margin="0,2,0,2"/>
        <TextBox Grid.Row="4" Grid.Column="1" x:Name="txt_min_cable_trays"
                 Text="50" Width="70" Height="24" Margin="8,2,0,2"
                 VerticalContentAlignment="Center"/>
      </Grid>
    </GroupBox>

    <!-- Sleeve Shape -->
    <GroupBox Grid.Row="3" Header="Sleeve Shape" Margin="0,0,0,8">
      <StackPanel Margin="8" Orientation="Horizontal">
        <RadioButton x:Name="rb_both" Content="Both (auto)"
                     IsChecked="True" Margin="0,0,16,0"/>
        <RadioButton x:Name="rb_round" Content="Round"
                     Margin="0,0,16,0"/>
        <RadioButton x:Name="rb_rect" Content="Rectangular"/>
      </StackPanel>
    </GroupBox>

    <!-- Clearance -->
    <GroupBox Grid.Row="4" Header="Clearance (mm)" Margin="0,0,0,8">
      <Grid Margin="8">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Text="Radial clearance:" VerticalAlignment="Center"
                   Margin="0,0,8,0"/>
        <TextBox Grid.Column="1" x:Name="txt_clearance" Text="50"
                 Width="80" HorizontalAlignment="Left"
                 VerticalContentAlignment="Center" Height="26"/>
      </Grid>
    </GroupBox>

    <!-- Options -->
    <GroupBox Grid.Row="5" Header="Options" Margin="0,0,0,8">
      <StackPanel Margin="8">
        <CheckBox x:Name="chk_skip_dupes"
                  Content="Skip duplicates (within 30 mm)"
                  IsChecked="True" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_selected_only"
                  Content="Selected MEP elements only"
                  IsChecked="False" Margin="0,0,0,8"/>
        <CheckBox x:Name="chk_snap"
                  Content="Snap to standard opening sizes"
                  IsChecked="True" Margin="0,0,0,4"/>
        <CheckBox x:Name="chk_skip_grazing"
                  Content="Skip grazing / parallel runs"
                  IsChecked="True" Margin="0,0,0,8"/>
        <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
          <TextBlock Text="Overhang per face (mm):"
                     VerticalAlignment="Center" Width="170"/>
          <TextBox x:Name="txt_overhang" Text="25" Width="80" Height="26"
                   VerticalContentAlignment="Center"/>
        </StackPanel>
        <TextBlock Text="Min sizes are set per MEP category above (0 = no minimum). Data is written to ARI-F1/F2/F3."
                   Foreground="#999" FontSize="10" Margin="0,4,0,0"
                   TextWrapping="Wrap"/>
      </StackPanel>
    </GroupBox>

    <!-- Workset -->
    <GroupBox Grid.Row="6" Header="Workset" Margin="0,0,0,8">
      <StackPanel Margin="8">
        <ComboBox x:Name="cmb_workset" Height="28" Margin="0,0,0,6"/>
        <StackPanel Orientation="Horizontal">
          <TextBlock Text="Or create new:" VerticalAlignment="Center"
                     Margin="0,0,8,0"/>
          <TextBox x:Name="txt_new_workset" Text="TEMP-Workset"
                   Width="200" Height="26"
                   VerticalContentAlignment="Center"/>
        </StackPanel>
        <TextBlock Text="Select an existing workset or type a new name above."
                   Foreground="#999" FontSize="10" Margin="0,4,0,0"/>
      </StackPanel>
    </GroupBox>

    <!-- Status -->
    <TextBlock Grid.Row="7" x:Name="txt_status"
               Text="Sleeves created as DirectShapes"
               Foreground="#888" FontSize="11"
               Margin="0,0,0,10"/>

    <!-- Execute -->
    <Button Grid.Row="8" x:Name="btn_run"
            Content="Place Sleeves"
            Height="40" FontSize="14" FontWeight="Bold"
            Background="#2C3E50" Foreground="White"/>
  </Grid>
</Window>"""


# ============================================================
# UI CLASS
# ============================================================

class PlaceSleevesUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        self.chk_walls = self.window.FindName("chk_walls")
        self.chk_floors = self.window.FindName("chk_floors")
        self.chk_str_columns = self.window.FindName("chk_str_columns")
        self.chk_str_framing = self.window.FindName("chk_str_framing")
        self.chk_str_foundations = self.window.FindName("chk_str_foundations")
        self.chk_roofs = self.window.FindName("chk_roofs")
        self.chk_ceilings = self.window.FindName("chk_ceilings")
        self.lst_links = self.window.FindName("lst_links")
        self.txt_no_links = self.window.FindName("txt_no_links")
        self.chk_pipes = self.window.FindName("chk_pipes")
        self.chk_ducts = self.window.FindName("chk_ducts")
        self.chk_conduits = self.window.FindName("chk_conduits")
        self.chk_cable_trays = self.window.FindName("chk_cable_trays")
        self.txt_min_pipes = self.window.FindName("txt_min_pipes")
        self.txt_min_ducts = self.window.FindName("txt_min_ducts")
        self.txt_min_conduits = self.window.FindName("txt_min_conduits")
        self.txt_min_cable_trays = self.window.FindName("txt_min_cable_trays")
        self.rb_both = self.window.FindName("rb_both")
        self.rb_round = self.window.FindName("rb_round")
        self.rb_rect = self.window.FindName("rb_rect")
        self.txt_clearance = self.window.FindName("txt_clearance")
        self.chk_skip_dupes = self.window.FindName("chk_skip_dupes")
        self.chk_selected_only = self.window.FindName("chk_selected_only")
        self.chk_snap = self.window.FindName("chk_snap")
        self.chk_skip_grazing = self.window.FindName("chk_skip_grazing")
        self.txt_overhang = self.window.FindName("txt_overhang")
        self.cmb_workset = self.window.FindName("cmb_workset")
        self.txt_new_workset = self.window.FindName("txt_new_workset")
        self.txt_status = self.window.FindName("txt_status")
        self.btn_run = self.window.FindName("btn_run")

        # Populate linked models list
        self.link_map = get_link_instances(doc)
        if self.link_map:
            self.txt_no_links.Visibility = Visibility.Collapsed
            for name in sorted(self.link_map.keys()):
                self.lst_links.Items.Add(name)
        else:
            self.lst_links.Visibility = Visibility.Collapsed

        # Populate workset combo
        self.workset_map = get_user_worksets(doc)
        if self.workset_map:
            self.cmb_workset.Items.Add("-- Create new workset --")
            default_idx = 0
            for i, ws_name in enumerate(sorted(self.workset_map.keys())):
                self.cmb_workset.Items.Add(ws_name)
                if ws_name == TEMP_WORKSET_NAME:
                    default_idx = i + 1
            self.cmb_workset.SelectedIndex = default_idx
        else:
            self.cmb_workset.Items.Add("-- Not workshared --")
            self.cmb_workset.SelectedIndex = 0
            self.cmb_workset.IsEnabled = False
            self.txt_new_workset.IsEnabled = False

        self.btn_run.Click += self.on_run

    def on_run(self, sender, args):
        try:
            clearance_mm = float(self.txt_clearance.Text.strip())
        except (ValueError, AttributeError):
            forms.alert("Enter a valid clearance value in mm.", title="Warning")
            return

        host_cats = {}
        if self.chk_walls.IsChecked:
            host_cats["Walls"] = BuiltInCategory.OST_Walls
        if self.chk_floors.IsChecked:
            host_cats["Floors"] = BuiltInCategory.OST_Floors
        if self.chk_str_columns.IsChecked:
            host_cats["Structural Columns"] = BuiltInCategory.OST_StructuralColumns
        if self.chk_str_framing.IsChecked:
            host_cats["Structural Framing"] = BuiltInCategory.OST_StructuralFraming
        if self.chk_str_foundations.IsChecked:
            host_cats["Structural Foundations"] = BuiltInCategory.OST_StructuralFoundation
        if self.chk_roofs.IsChecked:
            host_cats["Roofs"] = BuiltInCategory.OST_Roofs
        if self.chk_ceilings.IsChecked:
            host_cats["Ceilings"] = BuiltInCategory.OST_Ceilings
        if not host_cats:
            forms.alert("Select at least one host category.", title="Warning")
            return

        def _parse_min(textbox):
            """Read a per-category minimum size (mm); blank/invalid -> 0."""
            try:
                return max(0.0, float(textbox.Text.strip()))
            except (ValueError, AttributeError):
                return 0.0

        # Each enabled category contributes its BuiltInCategory plus its own
        # minimum nominal size. Unchecked categories are skipped entirely.
        mep_cats = []
        min_size_by_cat = {}
        if self.chk_pipes.IsChecked:
            mep_cats.append(BuiltInCategory.OST_PipeCurves)
            min_size_by_cat[int(BuiltInCategory.OST_PipeCurves)] = \
                _parse_min(self.txt_min_pipes)
        if self.chk_ducts.IsChecked:
            duct_min = _parse_min(self.txt_min_ducts)
            mep_cats.extend([
                BuiltInCategory.OST_DuctCurves,
                BuiltInCategory.OST_FlexDuctCurves,
            ])
            min_size_by_cat[int(BuiltInCategory.OST_DuctCurves)] = duct_min
            min_size_by_cat[int(BuiltInCategory.OST_FlexDuctCurves)] = duct_min
        if self.chk_conduits.IsChecked:
            mep_cats.append(BuiltInCategory.OST_Conduit)
            min_size_by_cat[int(BuiltInCategory.OST_Conduit)] = \
                _parse_min(self.txt_min_conduits)
        if self.chk_cable_trays.IsChecked:
            mep_cats.append(BuiltInCategory.OST_CableTray)
            min_size_by_cat[int(BuiltInCategory.OST_CableTray)] = \
                _parse_min(self.txt_min_cable_trays)
        if not mep_cats:
            forms.alert("Select at least one MEP category.", title="Warning")
            return

        # Shape mode
        if self.rb_round.IsChecked:
            shape_mode = "round"
        elif self.rb_rect.IsChecked:
            shape_mode = "rectangular"
        else:
            shape_mode = "both"

        # Selected linked models
        selected_links = []
        for item in self.lst_links.SelectedItems:
            name = str(item)
            if name in self.link_map:
                selected_links.append(self.link_map[name])

        # Workset selection
        workset_name = None
        if doc.IsWorkshared:
            sel_ws = str(self.cmb_workset.SelectedItem) if self.cmb_workset.SelectedItem else ""
            if sel_ws == "-- Create new workset --" or not self.workset_map:
                new_name = self.txt_new_workset.Text.strip()
                if not new_name:
                    forms.alert("Enter a workset name.", title="Warning")
                    return
                workset_name = new_name
            else:
                workset_name = sel_ws

        skip_dupes = self.chk_skip_dupes.IsChecked
        selected_only = self.chk_selected_only.IsChecked

        snap_standard = bool(self.chk_snap.IsChecked)
        skip_grazing = bool(self.chk_skip_grazing.IsChecked)
        try:
            overhang_mm = float(self.txt_overhang.Text.strip())
        except (ValueError, AttributeError):
            overhang_mm = 25.0

        self.window.Close()

        run_placement(
            host_cats=host_cats,
            mep_cats=mep_cats,
            clearance_mm=clearance_mm,
            selected_links=selected_links,
            skip_dupes=skip_dupes,
            selected_only=selected_only,
            shape_mode=shape_mode,
            workset_name=workset_name,
            overhang_mm=overhang_mm,
            snap_standard=snap_standard,
            min_size_by_cat=min_size_by_cat,
            skip_grazing=skip_grazing,
        )

    def show(self):
        self.window.ShowDialog()


# ============================================================
# MAIN ENGINE
# ============================================================

def run_placement(host_cats, mep_cats, clearance_mm,
                  selected_links, skip_dupes, selected_only,
                  shape_mode="both", workset_name=None,
                  overhang_mm=25.0, snap_standard=True,
                  min_size_by_cat=None, skip_grazing=True):
    """Core placement engine using DirectShapes.

    min_size_by_cat: {BuiltInCategory int: minimum nominal size in mm}.
    An MEP element whose nominal diameter/side is below the threshold for
    its category is skipped (no sleeve). 0 or missing means no minimum.
    """
    if min_size_by_cat is None:
        min_size_by_cat = {}

    # Collect MEP elements
    if selected_only:
        sel_ids = uidoc.Selection.GetElementIds()
        mep_elements = []
        for eid in sel_ids:
            el = doc.GetElement(eid)
            if el and el.Category:
                cat_int = _id_int(el.Category.Id)
                if cat_int in [int(c) for c in mep_cats]:
                    mep_elements.append(el)
        if not mep_elements:
            forms.alert("No MEP elements in the current selection.",
                        exitscript=True)
            return
    else:
        mep_elements = []
        for cat in mep_cats:
            try:
                elems = list(
                    FilteredElementCollector(doc)
                    .OfCategory(cat)
                    .WhereElementIsNotElementType()
                    .ToElements()
                )
                mep_elements.extend(elems)
            except Exception:
                pass

    if not mep_elements:
        forms.alert("No MEP elements found.", exitscript=True)
        return

    # Build link data from user selection
    link_data = []
    for lnk in selected_links:
        ld = lnk.GetLinkDocument()
        if ld:
            link_data.append((ld, lnk.GetTotalTransform(), lnk))

    # Counters
    spatial = SpatialHashGrid(cell_size=0.5)
    existing_sleeve_count = 0
    if skip_dupes:
        for pt in collect_existing_sleeve_points(doc):
            spatial.add(pt)
            existing_sleeve_count += 1
    placed_count = 0
    error_count = 0
    skipped_count = 0
    no_curve_count = 0
    no_dir_count = 0
    no_hosts_count = 0
    no_pen_count = 0
    total_hosts_found = 0
    grazing_count = 0
    small_count = 0
    overhang_ft = max(0.0, overhang_mm) * MM_TO_FEET
    created_sleeves = []
    merge_result = {
        "groups_merged": 0,
        "sleeves_removed": 0,
        "sleeves_created": 0,
        "failed_groups": 0,
    }

    _reset_caches()

    # Pre-compute link inverse transforms (expensive; do once per link)
    link_inv_cache = {}
    for link_doc_i, link_xf, link_inst in link_data:
        link_inv_cache[id(link_inst)] = link_xf.Inverse

    output.print_md("### Place Sleeves (DirectShape)")
    output.print_md("- MEP elements: {}".format(len(mep_elements)))
    output.print_md("- Host categories: {}".format(
        ", ".join(host_cats.keys())))
    output.print_md("- Shape mode: **{}**".format(shape_mode))
    output.print_md("- Merge nearby sleeves: **{} mm**".format(
        int(MERGE_GAP_MM)))
    output.print_md("- Overhang per face: **{} mm**".format(int(overhang_mm)))
    output.print_md("- Snap to standard sizes: **{}**".format(
        "on" if snap_standard else "off"))
    min_size_labels = [
        u"{} ≥ {} mm".format(
            MEP_SERVICE_LABELS.get(cat_int, str(cat_int)), int(min_mm))
        for cat_int, min_mm in min_size_by_cat.items() if min_mm > 0
    ]
    if min_size_labels:
        output.print_md("- Min size per category: **{}**".format(
            ", ".join(sorted(min_size_labels))))
    output.print_md("- Skip grazing penetrations: **{}**".format(
        "on" if skip_grazing else "off"))
    if link_data:
        output.print_md("- Linked models selected: {}".format(len(link_data)))

    # Pre-load host caches (one collector call per category per doc)
    for cat_name, cat_bic in host_cats.items():
        _preload_hosts(doc, cat_bic)
        for link_doc_i, link_xf, link_inst in link_data:
            _preload_hosts(link_doc_i, cat_bic)

    # Reference levels for the bottom-of-opening offset (ARI-F3).
    levels_sorted = collect_levels_sorted(doc)

    # Create / bind the organized ARI-F* parameters (own transaction so the
    # bindings are committed before we write values).
    ari_ok = False
    try:
        with revit.Transaction("Sleeve Parameters"):
            ari_ok = ensure_ari_params(doc)
    except Exception as ex:
        output.print_md("**ARI parameter setup failed:** {}".format(ex))
        ari_ok = False
    output.print_md("- ARI-F* parameters: **{}**".format(
        "ready" if ari_ok else "unavailable"))

    with revit.Transaction("Place Sleeves"):
        # Resolve workset
        workset_id = None
        if doc.IsWorkshared and workset_name:
            workset_id = get_or_create_workset(doc, workset_name)
            if workset_id:
                output.print_md(
                    "- Workset: **{}**".format(workset_name))

        total_mep = len(mep_elements)
        for mep_idx, mep in enumerate(mep_elements):
            # Lightweight progress in the output window (throttled). Keeps the
            # user informed during the heavy clash loop on large models.
            if mep_idx % 10 == 0 or mep_idx + 1 == total_mep:
                output.update_progress(mep_idx + 1, total_mep)

            mep_curve = get_mep_curve(mep)
            if mep_curve is None:
                no_curve_count += 1
                continue

            mep_dir = get_mep_direction(mep_curve)
            if mep_dir is None:
                no_dir_count += 1
                continue

            # Skip MEP below the per-category minimum size (structural focus).
            try:
                mep_cat_int = _id_int(mep.Category.Id)
            except Exception:
                mep_cat_int = None
            min_size_mm = min_size_by_cat.get(mep_cat_int, 0.0)
            if min_size_mm > 0:
                nominal_mm = get_mep_nominal_mm(mep)
                if nominal_mm is not None and nominal_mm < min_size_mm:
                    small_count += 1
                    continue

            # Cache sleeve size per MEP (same regardless of host)
            sleeve_size = _get_sleeve_size_cached(
                mep, clearance_mm, shape_mode, snap_standard
            )

            found_host = False

            # ------- Current model hosts -------
            for cat_name, cat_bic in host_cats.items():
                hosts = find_clashing_hosts(mep, cat_bic, doc)
                total_hosts_found += len(hosts)
                for host in hosts:
                    found_host = True
                    try:
                        host_solid = _get_solid_cached(host)
                        if host_solid is None:
                            continue
                        pen = get_penetration(host_solid, mep_curve)
                        if pen is None:
                            no_pen_count += 1
                            continue

                        # Skip surface clips: MEP centerline barely grazes the
                        # host face — not a real through-penetration.
                        if pen["length"] < MIN_PENETRATION_MM * MM_TO_FEET:
                            grazing_count += 1
                            continue

                        # Discard grazing/parallel runs along the host.
                        if skip_grazing:
                            thick_ft = host_thickness_feet(host)
                            if (thick_ft > 1e-6 and
                                    pen["length"] >
                                    thick_ft * GRAZING_RATIO):
                                grazing_count += 1
                                continue

                        if skip_dupes and spatial.has_nearby(
                            pen["center"], 0.1
                        ):
                            skipped_count += 1
                            continue

                        sleeve_dir = pen["direction"] if pen["direction"] else mep_dir
                        sleeve_len = pen["length"] + 2 * overhang_ft
                        mark = "SLV-{:04d}".format(placed_count + 1)
                        ds = place_directshape_sleeve(
                            doc, pen["center"], sleeve_dir,
                            sleeve_size, sleeve_len, workset_id,
                            None, mark,
                        )
                        if ari_ok:
                            set_ari_params(
                                ds,
                                _foro_dimension_label(sleeve_size),
                                mark,
                                None,
                            )
                        created_sleeves.append(
                            _build_sleeve_record(
                                ds,
                                pen["center"],
                                sleeve_dir,
                                sleeve_size,
                                sleeve_len,
                                _make_host_key("doc", host.Id),
                                workset_id,
                                "",
                                _level_name(host),
                                mark,
                            )
                        )
                        spatial.add(pen["center"])
                        placed_count += 1
                    except Exception as ex:
                        output.print_md("**Error** MEP {}: {}".format(
                            mep.Id, ex))
                        error_count += 1

            if not found_host:
                no_hosts_count += 1

            # ------- Linked model hosts -------
            for link_doc_i, link_xf, link_inst in link_data:
                inv = link_inv_cache[id(link_inst)]
                mep_curve_link = mep_curve.CreateTransformed(inv)
                for cat_name, cat_bic in host_cats.items():
                    try:
                        hosts = find_clashing_hosts(
                            mep, cat_bic, link_doc_i, link_xf
                        )
                    except Exception:
                        hosts = []
                    for host in hosts:
                        try:
                            host_solid = _get_solid_cached(host)
                            if host_solid is None:
                                continue
                            pen = get_penetration(host_solid, mep_curve_link)
                            if pen is None:
                                continue

                            # Skip surface clips (linked model).
                            if pen["length"] < MIN_PENETRATION_MM * MM_TO_FEET:
                                grazing_count += 1
                                continue

                            # Discard grazing/parallel runs along the host.
                            if skip_grazing:
                                thick_ft = host_thickness_feet(host)
                                if (thick_ft > 1e-6 and
                                        pen["length"] >
                                        thick_ft * GRAZING_RATIO):
                                    grazing_count += 1
                                    continue

                            center_host = link_xf.OfPoint(pen["center"])
                            if pen["direction"]:
                                sleeve_dir = link_xf.OfVector(
                                    pen["direction"]
                                ).Normalize()
                            else:
                                sleeve_dir = mep_dir

                            if skip_dupes and spatial.has_nearby(
                                center_host, 0.1
                            ):
                                skipped_count += 1
                                continue

                            sleeve_len = pen["length"] + 2 * overhang_ft
                            mark = "SLV-{:04d}".format(placed_count + 1)
                            ds = place_directshape_sleeve(
                                doc, center_host, sleeve_dir,
                                sleeve_size, sleeve_len, workset_id,
                                None, mark,
                            )
                            if ari_ok:
                                set_ari_params(
                                    ds,
                                    _foro_dimension_label(sleeve_size),
                                    mark,
                                    None,
                                )
                            created_sleeves.append(
                                _build_sleeve_record(
                                    ds,
                                    center_host,
                                    sleeve_dir,
                                    sleeve_size,
                                    sleeve_len,
                                    _make_host_key(
                                        "link-{}".format(
                                            _id_int(link_inst.Id)
                                        ),
                                        host.Id,
                                    ),
                                    workset_id,
                                    "",
                                    _level_name(host),
                                    mark,
                                )
                            )
                            spatial.add(center_host)
                            placed_count += 1
                        except Exception as ex:
                            output.print_md(
                                "**Link error** MEP {}: {}".format(
                                    mep.Id, ex))
                            error_count += 1

    _reset_caches()  # Free memory

    # ARI-F3 (bottom-of-opening offset) needs a valid bounding box, which is
    # only available after the placement transaction committed (regenerated).
    if ari_ok and created_sleeves:
        try:
            with revit.Transaction("Sleeve Levels"):
                for rec in created_sleeves:
                    ds = doc.GetElement(rec["ds_id"])
                    if ds is not None:
                        set_ari_cota(ds, levels_sorted)
        except Exception as ex:
            output.print_md("**ARI-F3 update failed:** {}".format(ex))

    merge_result = merge_created_sleeves(
        doc, created_sleeves, MERGE_GAP_FEET, levels_sorted
    )
    final_count = (
        placed_count
        - merge_result["sleeves_removed"]
        + merge_result["sleeves_created"]
    )

    # Diagnostic report
    output.print_md("---")
    output.print_md("### Diagnostic Summary")
    output.print_md("- MEP elements processed: {}".format(len(mep_elements)))
    output.print_md("- Skipped (no curve): {}".format(no_curve_count))
    output.print_md("- Skipped (no direction): {}".format(no_dir_count))
    output.print_md("- MEP with no host intersection: {}".format(
        no_hosts_count))
    output.print_md("- Total host intersections found: {}".format(
        total_hosts_found))
    output.print_md("- Penetrations not resolved: {}".format(no_pen_count))
    if small_count > 0:
        output.print_md("- Skipped (below min size): {}".format(small_count))
    if grazing_count > 0:
        output.print_md("- Skipped (grazing/parallel): {}".format(
            grazing_count))
    output.print_md("- **Sleeves placed: {}**".format(placed_count))
    if merge_result["groups_merged"] > 0:
        output.print_md("- Merge groups applied: {}".format(
            merge_result["groups_merged"]))
        output.print_md("- Sleeves removed by merge: {}".format(
            merge_result["sleeves_removed"]))
        output.print_md("- Sleeves created by merge: {}".format(
            merge_result["sleeves_created"]))
    if merge_result["failed_groups"] > 0:
        output.print_md("- Merge groups failed: {}".format(
            merge_result["failed_groups"]))
    output.print_md("- **Final sleeves: {}**".format(final_count))
    if existing_sleeve_count > 0:
        output.print_md(
            "- Existing sleeves loaded (re-run guard): {}".format(
                existing_sleeve_count))
    if skipped_count > 0:
        output.print_md("- Duplicates skipped: {}".format(skipped_count))
    if error_count > 0:
        output.print_md("- Errors: {}".format(error_count))

    msg = u"{} sleeves placed.".format(placed_count)
    if merge_result["groups_merged"] > 0:
        msg += u"\n{} merge groups applied.".format(
            merge_result["groups_merged"]
        )
        msg += u"\n{} final sleeves.".format(final_count)
    if merge_result["failed_groups"] > 0:
        msg += u"\n{} merge groups failed.".format(
            merge_result["failed_groups"]
        )
    if skipped_count > 0:
        msg += u"\n{} duplicates skipped.".format(skipped_count)
    if error_count > 0:
        msg += u"\n{} errors.".format(error_count)
    forms.alert(msg, title="Place Sleeves")


# ============================================================
# ENTRY POINT
# ============================================================

ui = PlaceSleevesUI()
ui.show()
