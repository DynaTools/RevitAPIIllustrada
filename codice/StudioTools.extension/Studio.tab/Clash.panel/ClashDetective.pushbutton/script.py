#! python3
# -*- coding: utf-8 -*-
"""Clash Detective.

Detect geometric clashes (AABB overlap) between two sources (host model
or any loaded Revit link), then export a PDF report to the Desktop and
display an interactive HTML output inside pyRevit.

Author: Paulo Giavoni
Engine: CPython3
"""
from __future__ import print_function

__title__ = "Clash\nDetective"
__author__ = "Paulo Giavoni"

import os
import io
import json
import math
import uuid
import datetime
import traceback

import clr  # noqa: F401  (needed for .NET imports below)

from System import Array
from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows import Window, MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult
from System.Windows.Markup import XamlReader

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    FilteredElementCollector,
    RevitLinkInstance,
    Transform,
    XYZ,
)

# NOTE: This script intentionally avoids importing the `pyrevit` Python
# modules (`pyrevit.revit`, `pyrevit.forms`, `pyrevit.script`) because
# in this pyRevit build their import chain crashes on CPython3 inside
# `pyrevit/revit/events.py` ("interface takes exactly one argument").
# We use `__revit__` directly and a thin `_alert` wrapper around
# System.Windows.MessageBox instead.
uiapp = __revit__  # noqa: F821 – injected by pyRevit
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document


def _alert(message, title="Clash Detective", yes_no=False):
    """Lightweight replacement for pyrevit.forms.alert (CPython3-safe)."""
    if yes_no:
        res = MessageBox.Show(
            message, title, MessageBoxButton.YesNo,
            MessageBoxImage.Question)
        return res == MessageBoxResult.Yes
    MessageBox.Show(message, title, MessageBoxButton.OK,
                    MessageBoxImage.Information)
    return True


def _id_int(eid):
    """Numeric value of an ElementId on any Revit version.

    ``ElementId.IntegerValue`` was removed in Revit 2026 and ``Value``
    only exists from Revit 2024 on, so both spellings must be tried.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
_MEP_CATEGORIES = [
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctTerminal,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_Sprinklers,
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting,
    BuiltInCategory.OST_MechanicalEquipment,
    BuiltInCategory.OST_PlumbingFixtures,
    BuiltInCategory.OST_ElectricalEquipment,
    BuiltInCategory.OST_ElectricalFixtures,
    BuiltInCategory.OST_LightingFixtures,
    BuiltInCategory.OST_LightingDevices,
    BuiltInCategory.OST_FireAlarmDevices,
    BuiltInCategory.OST_DataDevices,
    BuiltInCategory.OST_CommunicationDevices,
    BuiltInCategory.OST_SecurityDevices,
]

_ARCH_CATEGORIES = [
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Floors,
    BuiltInCategory.OST_Ceilings,
    BuiltInCategory.OST_Roofs,
    BuiltInCategory.OST_Doors,
    BuiltInCategory.OST_Windows,
    BuiltInCategory.OST_Stairs,
    BuiltInCategory.OST_Furniture,
    BuiltInCategory.OST_FurnitureSystems,
    BuiltInCategory.OST_Casework,
    BuiltInCategory.OST_SpecialityEquipment,
    BuiltInCategory.OST_GenericModel,
]

_STR_CATEGORIES = [
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_StructuralFraming,
    BuiltInCategory.OST_StructuralFoundation,
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Floors,
]

_DISCIPLINE_PRESETS = {
    "Architecture": _ARCH_CATEGORIES,
    "Structure":    _STR_CATEGORIES,
    "MEP":          _MEP_CATEGORIES,
}

_BIC_LABELS = {}


def _bic_label(bic):
    """Cached friendly label from BuiltInCategory."""
    key = int(bic)
    if key in _BIC_LABELS:
        return _BIC_LABELS[key]
    try:
        cat = doc.Settings.Categories.get_Item(bic)
        label = cat.Name if cat is not None else str(bic)
    except Exception:
        label = str(bic).replace("OST_", "")
    _BIC_LABELS[key] = label
    return label


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
class Source(object):
    __slots__ = ("label", "doc", "transform", "is_host", "link_instance",
                 "link_id")

    def __init__(self, label, source_doc, transform, is_host,
                 link_instance=None, link_id=None):
        self.label = label
        self.doc = source_doc
        self.transform = transform
        self.is_host = is_host
        self.link_instance = link_instance
        self.link_id = link_id


def _list_sources():
    """Return list[Source]: host doc + all valid loaded links."""
    sources = [Source("[Host] " + (doc.Title or "Current Model"),
                      doc, Transform.Identity, True)]
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            continue
        try:
            tx = li.GetTotalTransform()
        except Exception:
            tx = Transform.Identity
        name = li.Name or (ldoc.Title or "Link")
        sources.append(Source("[Link] " + name, ldoc, tx, False, li,
                              li.Id))
    return sources


# ---------------------------------------------------------------------------
# Bounding box collection
# ---------------------------------------------------------------------------
class BBoxItem(object):
    __slots__ = ("eid", "cat_label", "bic_int", "level_name",
                 "min_x", "min_y", "min_z", "max_x", "max_y", "max_z")

    def __init__(self, eid, cat_label, bic_int, level_name,
                 mn, mx):
        self.eid = eid
        self.cat_label = cat_label
        self.bic_int = bic_int
        self.level_name = level_name
        self.min_x, self.min_y, self.min_z = mn
        self.max_x, self.max_y, self.max_z = mx


def _world_aabb(bbox, transform):
    """Transform 8 corners of a Revit BoundingBoxXYZ to world AABB."""
    mn, mx = bbox.Min, bbox.Max
    corners = [
        XYZ(mn.X, mn.Y, mn.Z), XYZ(mx.X, mn.Y, mn.Z),
        XYZ(mn.X, mx.Y, mn.Z), XYZ(mx.X, mx.Y, mn.Z),
        XYZ(mn.X, mn.Y, mx.Z), XYZ(mx.X, mn.Y, mx.Z),
        XYZ(mn.X, mx.Y, mx.Z), XYZ(mx.X, mx.Y, mx.Z),
    ]
    pts = [transform.OfPoint(c) for c in corners]
    xs = [p.X for p in pts]
    ys = [p.Y for p in pts]
    zs = [p.Z for p in pts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _level_name(elem, source_doc):
    try:
        lid = elem.LevelId
        if lid is not None and lid != ElementId.InvalidElementId:
            lev = source_doc.GetElement(lid)
            if lev is not None:
                return lev.Name
    except Exception:
        pass
    return ""


def _collect_bbox_items(source, bic_list, ignore_pinned, ignore_demolished):
    """Return list[BBoxItem] for a source filtered by categories."""
    items = []
    sdoc = source.doc
    tx = source.transform
    for bic in bic_list:
        try:
            collector = (FilteredElementCollector(sdoc)
                         .OfCategory(bic)
                         .WhereElementIsNotElementType())
        except Exception:
            continue
        cat_label = _bic_label(bic)
        bic_int = int(bic)
        for elem in collector:
            try:
                if ignore_pinned and getattr(elem, "Pinned", False):
                    continue
                if ignore_demolished:
                    try:
                        if elem.DemolishedPhaseId is not None and \
                                elem.DemolishedPhaseId != ElementId.InvalidElementId:
                            continue
                    except Exception:
                        pass
                bbox = elem.get_BoundingBox(None)
                if bbox is None:
                    continue
                mn, mx = _world_aabb(bbox, tx)
                items.append(BBoxItem(elem.Id, cat_label, bic_int,
                                      _level_name(elem, sdoc), mn, mx))
            except Exception:
                continue
    return items


# ---------------------------------------------------------------------------
# Spatial hash + AABB overlap
# ---------------------------------------------------------------------------
def _build_grid(items, cell_ft=10.0):
    grid = {}
    inv = 1.0 / cell_ft
    for idx, it in enumerate(items):
        ix0 = int(math.floor(it.min_x * inv))
        iy0 = int(math.floor(it.min_y * inv))
        iz0 = int(math.floor(it.min_z * inv))
        ix1 = int(math.floor(it.max_x * inv))
        iy1 = int(math.floor(it.max_y * inv))
        iz1 = int(math.floor(it.max_z * inv))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                for iz in range(iz0, iz1 + 1):
                    grid.setdefault((ix, iy, iz), []).append(idx)
    return grid, inv


def _aabb_overlap(a, b, tol_ft):
    if a.max_x + tol_ft < b.min_x or b.max_x + tol_ft < a.min_x:
        return None
    if a.max_y + tol_ft < b.min_y or b.max_y + tol_ft < a.min_y:
        return None
    if a.max_z + tol_ft < b.min_z or b.max_z + tol_ft < a.min_z:
        return None
    ox = max(0.0, min(a.max_x, b.max_x) - max(a.min_x, b.min_x))
    oy = max(0.0, min(a.max_y, b.max_y) - max(a.min_y, b.min_y))
    oz = max(0.0, min(a.max_z, b.max_z) - max(a.min_z, b.min_z))
    cx = (max(a.min_x, b.min_x) + min(a.max_x, b.max_x)) * 0.5
    cy = (max(a.min_y, b.min_y) + min(a.max_y, b.max_y)) * 0.5
    cz = (max(a.min_z, b.min_z) + min(a.max_z, b.max_z)) * 0.5
    return (ox * oy * oz, cx, cy, cz)


class ClashResult(object):
    __slots__ = ("cid", "a", "b", "cx", "cy", "cz", "vol_ft3", "level_name")

    def __init__(self, cid, a, b, cx, cy, cz, vol_ft3, level_name):
        self.cid = cid
        self.a = a
        self.b = b
        self.cx = cx
        self.cy = cy
        self.cz = cz
        self.vol_ft3 = vol_ft3
        self.level_name = level_name


def detect_clashes(items_a, items_b, tol_ft, same_source):
    """Run AABB clash test. Returns list[ClashResult]."""
    grid, inv = _build_grid(items_b, cell_ft=10.0)
    clashes = []
    cid = 0
    for a in items_a:
        ix0 = int(math.floor((a.min_x - tol_ft) * inv))
        iy0 = int(math.floor((a.min_y - tol_ft) * inv))
        iz0 = int(math.floor((a.min_z - tol_ft) * inv))
        ix1 = int(math.floor((a.max_x + tol_ft) * inv))
        iy1 = int(math.floor((a.max_y + tol_ft) * inv))
        iz1 = int(math.floor((a.max_z + tol_ft) * inv))
        seen = set()
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                for iz in range(iz0, iz1 + 1):
                    bucket = grid.get((ix, iy, iz))
                    if not bucket:
                        continue
                    for j in bucket:
                        if j in seen:
                            continue
                        seen.add(j)
                        b = items_b[j]
                        if same_source and a.eid == b.eid:
                            continue
                        ov = _aabb_overlap(a, b, tol_ft)
                        if ov is None:
                            continue
                        vol, cx, cy, cz = ov
                        cid += 1
                        clashes.append(ClashResult(
                            cid, a, b, cx, cy, cz, vol,
                            a.level_name or b.level_name))
    return clashes


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
_FT_TO_M = 0.3048


def _ft_to_m(v):
    return v * _FT_TO_M


def _ft3_to_m3(v):
    return v * (_FT_TO_M ** 3)


def _desktop_path(filename):
    desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    if not os.path.isdir(desk):
        desk = os.path.expanduser("~")
    return os.path.join(desk, filename)


def _safe_project_name():
    try:
        pi = doc.ProjectInformation
        name = pi.Name or doc.Title or "Project"
    except Exception:
        name = doc.Title or "Project"
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", " "):
            keep.append(ch)
    return ("".join(keep)).strip().replace(" ", "_") or "Project"


def export_pdf_report(meta, clashes, save_path=None):
    """Export PDF report using reportlab. Returns path or None."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            PageBreak,
        )
    except ImportError:
        return None

    if save_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = _desktop_path(
            "ClashReport_{0}_{1}.pdf".format(_safe_project_name(), ts))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title2", parent=styles["Title"], fontSize=18, spaceAfter=10)
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=13, spaceBefore=12,
        spaceAfter=6, textColor=colors.HexColor("#2C3E50"))
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=body, fontSize=8)

    story = []

    # ---- Cover ----
    story.append(Paragraph("Clash Detective Report", title_style))
    story.append(Paragraph(
        "<b>Project:</b> {0}".format(meta["project"]), body))
    story.append(Paragraph(
        "<b>Date:</b> {0}".format(meta["date"]), body))
    story.append(Paragraph(
        "<b>Source A:</b> {0}".format(meta["source_a"]), body))
    story.append(Paragraph(
        "<b>Source B:</b> {0}".format(meta["source_b"]), body))
    story.append(Paragraph(
        "<b>Categories A:</b> {0}".format(meta["cats_a"]), body))
    story.append(Paragraph(
        "<b>Categories B:</b> {0}".format(meta["cats_b"]), body))
    story.append(Paragraph(
        "<b>Tolerance:</b> {0:.1f} mm".format(meta["tolerance_mm"]), body))
    story.append(Paragraph(
        "<b>Total clashes:</b> {0}".format(len(clashes)), body))
    story.append(Spacer(1, 6 * mm))

    # ---- Summary matrix (Cat A x Cat B) ----
    story.append(Paragraph("Summary by category", h2))
    matrix = {}
    cats_a_set = set()
    cats_b_set = set()
    for c in clashes:
        ca = c.a.cat_label
        cb = c.b.cat_label
        cats_a_set.add(ca)
        cats_b_set.add(cb)
        matrix[(ca, cb)] = matrix.get((ca, cb), 0) + 1
    if not clashes:
        story.append(Paragraph("No clashes detected.", body))
    else:
        cats_a_l = sorted(cats_a_set)
        cats_b_l = sorted(cats_b_set)
        head = ["A \\ B"] + cats_b_l
        rows = [head]
        for ca in cats_a_l:
            row = [ca]
            for cb in cats_b_l:
                row.append(str(matrix.get((ca, cb), 0)))
            rows.append(row)
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                [colors.whitesmoke, colors.white]),
        ]))
        story.append(t)
    story.append(PageBreak())

    # ---- Detail table ----
    story.append(Paragraph("Clash details", h2))
    if not clashes:
        story.append(Paragraph("No clashes detected.", body))
    else:
        head = ["#", "A id", "A cat", "B id", "B cat", "Level",
                "X (m)", "Y (m)", "Z (m)", "Vol (m³)"]
        rows = [head]
        for c in clashes:
            rows.append([
                str(c.cid),
                str(_id_int(c.a.eid)),
                c.a.cat_label,
                str(_id_int(c.b.eid)),
                c.b.cat_label,
                c.level_name or "-",
                "{0:.2f}".format(_ft_to_m(c.cx)),
                "{0:.2f}".format(_ft_to_m(c.cy)),
                "{0:.2f}".format(_ft_to_m(c.cz)),
                "{0:.3f}".format(_ft3_to_m3(c.vol_ft3)),
            ])
        t = Table(rows, repeatRows=1, colWidths=[
            10 * mm, 18 * mm, 28 * mm, 18 * mm, 28 * mm,
            22 * mm, 16 * mm, 16 * mm, 16 * mm, 18 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (0, 1), (-1, -1), "LEFT"),
            ("ALIGN", (6, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                [colors.whitesmoke, colors.white]),
        ]))
        story.append(t)

    def _footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 10 * mm,
                          "Clash Detective")
        canvas.drawRightString(
            A4[0] - 15 * mm, 10 * mm,
            "Page {0}".format(pdf_doc.page))
        canvas.restoreState()

    pdf = SimpleDocTemplate(
        save_path, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=18 * mm,
        title="Clash Detective Report")
    pdf.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return save_path


def export_html_report(meta, clashes, save_path=None):
    if save_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = _desktop_path(
            "ClashReport_{0}_{1}.html".format(_safe_project_name(), ts))

    rows_html = []
    for c in clashes:
        rows_html.append(
            "<tr><td>{0}</td><td>{1}</td><td>{2}</td>"
            "<td>{3}</td><td>{4}</td><td>{5}</td>"
            "<td>{6:.2f}</td><td>{7:.2f}</td><td>{8:.2f}</td>"
            "<td>{9:.3f}</td></tr>".format(
                c.cid, _id_int(c.a.eid), c.a.cat_label,
                _id_int(c.b.eid), c.b.cat_label,
                c.level_name or "-",
                _ft_to_m(c.cx), _ft_to_m(c.cy), _ft_to_m(c.cz),
                _ft3_to_m3(c.vol_ft3)))

    html = u"""<!doctype html><html><head><meta charset='utf-8'>
<title>Clash Report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}
h1{{color:#2C3E50}} h2{{color:#2C3E50;margin-top:24px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th{{background:#2C3E50;color:#fff;padding:6px;text-align:left}}
td{{border:1px solid #ccc;padding:4px}}
tr:nth-child(even){{background:#f5f5f5}}
.meta td:first-child{{font-weight:bold;width:160px}}
</style></head><body>
<h1>Clash Detective Report</h1>
<table class='meta'>
<tr><td>Project</td><td>{project}</td></tr>
<tr><td>Date</td><td>{date}</td></tr>
<tr><td>Source A</td><td>{source_a}</td></tr>
<tr><td>Source B</td><td>{source_b}</td></tr>
<tr><td>Categories A</td><td>{cats_a}</td></tr>
<tr><td>Categories B</td><td>{cats_b}</td></tr>
<tr><td>Tolerance</td><td>{tol:.1f} mm</td></tr>
<tr><td>Total clashes</td><td>{n}</td></tr>
</table>
<h2>Clash details</h2>
<table><thead><tr>
<th>#</th><th>A id</th><th>A cat</th><th>B id</th><th>B cat</th>
<th>Level</th><th>X (m)</th><th>Y (m)</th><th>Z (m)</th><th>Vol (m³)</th>
</tr></thead><tbody>
{rows}
</tbody></table>
</body></html>""".format(
        project=meta["project"], date=meta["date"],
        source_a=meta["source_a"], source_b=meta["source_b"],
        cats_a=meta["cats_a"], cats_b=meta["cats_b"],
        tol=meta["tolerance_mm"], n=len(clashes),
        rows="\n".join(rows_html) or
        "<tr><td colspan='10'>No clashes detected.</td></tr>")

    with io.open(save_path, "w", encoding="utf-8") as f:
        f.write(html)
    return save_path


# ---------------------------------------------------------------------------
# JSON persistence
# ---------------------------------------------------------------------------
def _appdata_dir():
    base = os.path.join(os.environ.get("APPDATA", ""), "pyRevit",
                        "pyRevit", "clashes")
    try:
        if not os.path.isdir(base):
            os.makedirs(base)
    except Exception:
        pass
    return base


def _project_guid():
    try:
        return str(doc.ProjectInformation.UniqueId)
    except Exception:
        return _safe_project_name()


def save_clash_json(meta, clashes):
    payload = {
        "version": 1,
        "timestamp": meta["date"],
        "project": meta["project"],
        "source_a": meta["source_a"],
        "source_b": meta["source_b"],
        "categories_a": meta["cats_a"],
        "categories_b": meta["cats_b"],
        "tolerance_mm": meta["tolerance_mm"],
        "clashes": [{
            "id": c.cid,
            "a_id": _id_int(c.a.eid),
            "a_cat": c.a.cat_label,
            "b_id": _id_int(c.b.eid),
            "b_cat": c.b.cat_label,
            "x_m": _ft_to_m(c.cx),
            "y_m": _ft_to_m(c.cy),
            "z_m": _ft_to_m(c.cz),
            "vol_m3": _ft3_to_m3(c.vol_ft3),
            "level": c.level_name or "",
            "status": "New",
        } for c in clashes],
    }
    path = os.path.join(_appdata_dir(),
                        "{0}.json".format(_project_guid()))
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2, ensure_ascii=False))
    except Exception:
        pass
    return path


# ---------------------------------------------------------------------------
# WPF UI
# ---------------------------------------------------------------------------
_XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Clash Detective" Width="780" Height="680"
        WindowStartupLocation="CenterScreen"
        ResizeMode="CanResize" FontFamily="Segoe UI" FontSize="12">
  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Sources -->
    <GroupBox Grid.Row="0" Header="Sources" Padding="8" Margin="0,0,0,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="80"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="80"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Column="0" Text="Source A:" VerticalAlignment="Center"/>
        <ComboBox  Grid.Column="1" x:Name="cbA" Margin="4,0,12,0"/>
        <TextBlock Grid.Column="2" Text="Source B:" VerticalAlignment="Center"/>
        <ComboBox  Grid.Column="3" x:Name="cbB" Margin="4,0,0,0"/>
      </Grid>
    </GroupBox>

    <!-- Categories -->
    <GroupBox Grid.Row="1" Header="Categories" Padding="8" Margin="0,0,0,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="Source A disciplines" FontWeight="Bold" Margin="0,0,0,4"/>
          <CheckBox x:Name="cbAArch" Content="Architecture"/>
          <CheckBox x:Name="cbAStr"  Content="Structure"/>
          <CheckBox x:Name="cbAMep"  Content="MEP" IsChecked="True"/>
        </StackPanel>
        <StackPanel Grid.Column="1">
          <TextBlock Text="Source B disciplines" FontWeight="Bold" Margin="0,0,0,4"/>
          <CheckBox x:Name="cbBArch" Content="Architecture" IsChecked="True"/>
          <CheckBox x:Name="cbBStr"  Content="Structure"/>
          <CheckBox x:Name="cbBMep"  Content="MEP"/>
        </StackPanel>
      </Grid>
    </GroupBox>

    <!-- Options -->
    <GroupBox Grid.Row="2" Header="Options" Padding="8" Margin="0,0,0,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="80"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Column="0" Text="Tolerance (mm):" VerticalAlignment="Center"/>
        <TextBox   Grid.Column="1" x:Name="tbTol" Text="0" Margin="6,0,12,0"/>
        <StackPanel Grid.Column="2" Orientation="Horizontal">
          <CheckBox x:Name="cbIgnorePinned" Content="Ignore pinned" Margin="0,0,12,0"/>
          <CheckBox x:Name="cbIgnoreDemo"   Content="Ignore demolished" Margin="0,0,12,0"/>
          <CheckBox x:Name="cbGroupByA"     Content="Group by A" IsChecked="True"/>
        </StackPanel>
      </Grid>
    </GroupBox>

    <!-- Run row -->
    <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,0,0,8">
      <Button x:Name="btnRun" Content="Run clash test" Padding="14,5"
              Background="#2C3E50" Foreground="White" FontWeight="Bold"/>
      <TextBlock x:Name="tbStatus" VerticalAlignment="Center" Margin="14,0,0,0"
                 Foreground="#555"/>
    </StackPanel>

    <!-- Results -->
    <DataGrid Grid.Row="4" x:Name="dgResults" AutoGenerateColumns="False"
              IsReadOnly="True" SelectionMode="Single"
              GridLinesVisibility="Horizontal" HeadersVisibility="Column"
              AlternatingRowBackground="#F5F7FA">
      <DataGrid.Columns>
        <DataGridTextColumn Header="#"        Binding="{Binding cid}"      Width="40"/>
        <DataGridTextColumn Header="A id"     Binding="{Binding a_id}"     Width="70"/>
        <DataGridTextColumn Header="A cat"    Binding="{Binding a_cat}"    Width="*"/>
        <DataGridTextColumn Header="B id"     Binding="{Binding b_id}"     Width="70"/>
        <DataGridTextColumn Header="B cat"    Binding="{Binding b_cat}"    Width="*"/>
        <DataGridTextColumn Header="Level"    Binding="{Binding level}"    Width="100"/>
        <DataGridTextColumn Header="X (m)"    Binding="{Binding x}"        Width="60"/>
        <DataGridTextColumn Header="Y (m)"    Binding="{Binding y}"        Width="60"/>
        <DataGridTextColumn Header="Z (m)"    Binding="{Binding z}"        Width="60"/>
        <DataGridTextColumn Header="Vol (m³)" Binding="{Binding vol}"      Width="70"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- Footer -->
    <StackPanel Grid.Row="5" Orientation="Horizontal" HorizontalAlignment="Right"
                Margin="0,8,0,0">
      <Button x:Name="btnPdf"   Content="Export PDF"  Padding="12,5" Margin="0,0,8,0"/>
      <Button x:Name="btnHtml"  Content="Export HTML" Padding="12,5" Margin="0,0,8,0"/>
      <Button x:Name="btnClose" Content="Close"       Padding="12,5"/>
    </StackPanel>
  </Grid>
</Window>"""


class ClashRow(object):
    """Lightweight row object for DataGrid binding."""
    def __init__(self, c):
        self.cid = c.cid
        self.a_id = _id_int(c.a.eid)
        self.a_cat = c.a.cat_label
        self.b_id = _id_int(c.b.eid)
        self.b_cat = c.b.cat_label
        self.level = c.level_name or "-"
        self.x = "{0:.2f}".format(_ft_to_m(c.cx))
        self.y = "{0:.2f}".format(_ft_to_m(c.cy))
        self.z = "{0:.2f}".format(_ft_to_m(c.cz))
        self.vol = "{0:.3f}".format(_ft3_to_m3(c.vol_ft3))
        self._clash = c


class ClashWindow(object):
    def __init__(self, sources):
        self.sources = sources
        ms = MemoryStream(Encoding.UTF8.GetBytes(_XAML))
        self.win = XamlReader.Load(ms)

        self.cbA = self.win.FindName("cbA")
        self.cbB = self.win.FindName("cbB")
        for s in sources:
            self.cbA.Items.Add(s.label)
            self.cbB.Items.Add(s.label)
        self.cbA.SelectedIndex = 0
        self.cbB.SelectedIndex = 1 if len(sources) > 1 else 0

        self.cbAArch = self.win.FindName("cbAArch")
        self.cbAStr = self.win.FindName("cbAStr")
        self.cbAMep = self.win.FindName("cbAMep")
        self.cbBArch = self.win.FindName("cbBArch")
        self.cbBStr = self.win.FindName("cbBStr")
        self.cbBMep = self.win.FindName("cbBMep")

        self.tbTol = self.win.FindName("tbTol")
        self.cbIgnorePinned = self.win.FindName("cbIgnorePinned")
        self.cbIgnoreDemo = self.win.FindName("cbIgnoreDemo")

        self.tbStatus = self.win.FindName("tbStatus")
        self.dg = self.win.FindName("dgResults")

        self.win.FindName("btnRun").Click += self._on_run
        self.win.FindName("btnPdf").Click += self._on_pdf
        self.win.FindName("btnHtml").Click += self._on_html
        self.win.FindName("btnClose").Click += self._on_close
        self.dg.MouseDoubleClick += self._on_row_dbl

        self._clashes = []
        self._meta = None

    # ---- helpers ----
    def _disc_for(self, source_label, arch, struc, mep):
        cats = []
        names = []
        if arch:
            cats.extend(_ARCH_CATEGORIES); names.append("Architecture")
        if struc:
            cats.extend(_STR_CATEGORIES);  names.append("Structure")
        if mep:
            cats.extend(_MEP_CATEGORIES);  names.append("MEP")
        # de-duplicate while keeping order
        seen = set(); uniq = []
        for c in cats:
            k = int(c)
            if k in seen:
                continue
            seen.add(k); uniq.append(c)
        return uniq, ", ".join(names) if names else "(none)"

    def _selected_source(self, combo):
        return self.sources[combo.SelectedIndex]

    def _set_status(self, msg):
        self.tbStatus.Text = msg

    # ---- handlers ----
    def _on_run(self, _s, _e):
        try:
            sa = self._selected_source(self.cbA)
            sb = self._selected_source(self.cbB)
            cats_a, label_a = self._disc_for(
                sa.label, self.cbAArch.IsChecked, self.cbAStr.IsChecked,
                self.cbAMep.IsChecked)
            cats_b, label_b = self._disc_for(
                sb.label, self.cbBArch.IsChecked, self.cbBStr.IsChecked,
                self.cbBMep.IsChecked)
            if not cats_a or not cats_b:
                _alert("Select at least one discipline for each source.")
                return
            try:
                tol_mm = float((self.tbTol.Text or "0").replace(",", "."))
            except ValueError:
                tol_mm = 0.0
            tol_ft = (tol_mm / 1000.0) / _FT_TO_M

            ignore_pinned = bool(self.cbIgnorePinned.IsChecked)
            ignore_demo = bool(self.cbIgnoreDemo.IsChecked)

            self._set_status("Collecting bounding boxes…")
            self.win.UpdateLayout()
            items_a = _collect_bbox_items(sa, cats_a, ignore_pinned,
                                          ignore_demo)
            items_b = _collect_bbox_items(sb, cats_b, ignore_pinned,
                                          ignore_demo)
            same_source = (sa.is_host == sb.is_host and
                           (sa.link_id == sb.link_id))
            self._set_status("Detecting clashes ({0} × {1})…".format(
                len(items_a), len(items_b)))
            self.win.UpdateLayout()
            clashes = detect_clashes(items_a, items_b, tol_ft, same_source)

            self._clashes = clashes
            self._meta = {
                "project": _safe_project_name(),
                "date": datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"),
                "source_a": sa.label,
                "source_b": sb.label,
                "cats_a": label_a,
                "cats_b": label_b,
                "tolerance_mm": tol_mm,
                "source_a_is_host": sa.is_host,
                "source_b_is_host": sb.is_host,
            }

            rows = [ClashRow(c) for c in clashes]
            self.dg.ItemsSource = rows
            self._set_status(
                "Found {0} clashes ({1} A × {2} B elements).".format(
                    len(clashes), len(items_a), len(items_b)))
        except Exception as ex:
            traceback.print_exc()
            _alert("Clash run failed:\n{0}".format(ex))

    def _on_pdf(self, _s, _e):
        if self._meta is None:
            _alert("Run a clash test first.")
            return
        try:
            path = export_pdf_report(self._meta, self._clashes)
            if path is None:
                _alert(
                    "reportlab is not installed in the pyRevit CPython "
                    "environment.\n\nInstall with:\n"
                    "  pip install reportlab\n\nUse Export HTML instead.",
                    title="PDF export")
                return
            _alert("PDF saved to:\n{0}".format(path))
            try:
                os.startfile(path)
            except Exception:
                pass
        except Exception as ex:
            traceback.print_exc()
            _alert("PDF export failed:\n{0}".format(ex))

    def _on_html(self, _s, _e):
        if self._meta is None:
            _alert("Run a clash test first.")
            return
        try:
            path = export_html_report(self._meta, self._clashes)
            _alert("HTML saved to:\n{0}".format(path))
            try:
                os.startfile(path)
            except Exception:
                pass
        except Exception as ex:
            traceback.print_exc()
            _alert("HTML export failed:\n{0}".format(ex))

    def _on_close(self, _s, _e):
        self.win.Close()

    def _on_row_dbl(self, _s, _e):
        row = self.dg.SelectedItem
        if row is None:
            return
        clash = getattr(row, "_clash", None)
        if clash is None:
            return
        # Only host elements can be selected/zoomed.
        host_eids = []
        sa_is_host = self._meta and self._meta.get("source_a_is_host")
        sb_is_host = self._meta and self._meta.get("source_b_is_host")
        if sa_is_host:
            host_eids.append(clash.a.eid)
        if sb_is_host:
            host_eids.append(clash.b.eid)
        try:
            if host_eids:
                uidoc.Selection.SetElementIds(
                    Array[ElementId](host_eids))
                uidoc.ShowElements(Array[ElementId](host_eids))
            else:
                _alert(
                    "Both elements belong to a linked file - cannot select "
                    "directly.\nLocation (m): "
                    "X={0:.2f} Y={1:.2f} Z={2:.2f}".format(
                        _ft_to_m(clash.cx), _ft_to_m(clash.cy),
                        _ft_to_m(clash.cz)))
        except Exception:
            traceback.print_exc()

    def show(self):
        self.win.ShowDialog()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    sources = _list_sources()
    if len(sources) < 2:
        if not _alert(
                "No Revit links are loaded.\n\n"
                "Clash Detective compares two sources. With only the host "
                "model available you can still run host vs host (rarely "
                "useful).\n\nContinue?",
                yes_no=True):
            return
    ClashWindow(sources).show()


if __name__ == "__main__":
    main()
