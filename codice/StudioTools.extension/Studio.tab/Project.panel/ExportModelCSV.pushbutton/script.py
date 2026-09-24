# -*- coding: utf-8 -*-
"""Dump the whole model to a folder of LLM-friendly CSV tables.

The point of this tool is to pay the cost of reading the model *once*:
an AI assistant can then answer questions about categories, families,
types and parameters by reading flat CSVs instead of querying Revit
element by element.

Layout: the core tables (elements, types) are wide, the parameter tables
are long (one row per parameter), and 00_INDEX.md documents the schema so
the LLM does not have to guess it.
"""

__title__ = "Export\nModel\nCSV"
__author__ = "Paulo Giavoni"
__doc__ = ("Exports the entire model (categories, families, types, "
           "parameters, levels, rooms, worksets, links, materials, views "
           "and warnings) to a folder of CSV tables plus an 00_INDEX.md "
           "describing the schema, ready to hand to an AI assistant.")

import io
import math
import os
import re
import datetime

from pyrevit import revit, DB, forms, script

doc = revit.doc
output = script.get_output()
logger = script.get_logger()

BASE_DIR = os.path.join(os.path.expanduser("~"), "Documents", "RevitExports")

# Internal (imperial) -> metric
FT_TO_M = 0.3048
SQFT_TO_M2 = 0.09290304
CUFT_TO_M3 = 0.028316846592

try:                       # IronPython 2.7 vs 3.x / CPython
    STRING_TYPES = (str, unicode)   # noqa: F821
except NameError:
    STRING_TYPES = (str,)


# ============================================================
# Small utilities
# ============================================================

def _id_int(eid):
    """Numeric value of an ElementId on any Revit version.

    ``ElementId.IntegerValue`` was removed in Revit 2026 and ``Value``
    only exists from Revit 2024 on, so both spellings must be tried.
    """
    if eid is None:
        return None
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _text(v):
    """Best-effort unicode text for anything the Revit API hands back."""
    if v is None:
        return u""
    if isinstance(v, STRING_TYPES):
        return v
    try:
        return u"{}".format(v)
    except Exception:
        return u""


def _elem_name(el):
    """Element.Name, tolerating the classes where the property is hidden."""
    if el is None:
        return u""
    try:
        return _text(el.Name)
    except Exception:
        pass
    try:
        return _text(DB.Element.Name.GetValue(el))
    except Exception:
        return u""


def _safe(obj, prop):
    """Read a property that some subclasses raise on (e.g. View.Scale)."""
    try:
        v = getattr(obj, prop)
    except Exception:
        return None
    if isinstance(v, (bool, int, float)) or v is None:
        return v
    return _text(v)


def _safe_dirname(name):
    name = re.sub(r"\.rvt$", "", _text(name), flags=re.IGNORECASE)
    name = re.sub(r"[^\w\-. ]+", "_", name).strip(" .")
    return name or "Model"


# ============================================================
# CSV writing (RFC 4180, streamed - no big lists in memory)
# ============================================================

def _cell(v):
    if v is None:
        return u""
    if isinstance(v, bool):
        return u"true" if v else u"false"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):   # NaN / inf
            return u""
        s = u"{:.6f}".format(v)
        if u"." in s:
            s = s.rstrip(u"0").rstrip(u".")
        s = s or u"0"
    else:
        s = _text(v)
    if s and (u"," in s or u'"' in s or u"\n" in s or u"\r" in s):
        s = u'"' + s.replace(u'"', u'""') + u'"'
    return s


class Csv(object):
    """Streaming CSV writer: utf-8 with BOM, comma separated, CRLF rows."""

    def __init__(self, folder, filename, header):
        self.name = filename
        self.path = os.path.join(folder, filename)
        self.header = list(header)
        self.rows = 0
        self._f = io.open(self.path, "w", encoding="utf-8-sig", newline="")
        self._f.write(u",".join(_cell(c) for c in header) + u"\r\n")

    def row(self, cells):
        self._f.write(u",".join(_cell(c) for c in cells) + u"\r\n")
        self.rows += 1

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass


# ============================================================
# Parameter reading
# ============================================================

def _spec_leaf(param):
    """Lowercase unit-spec name of a parameter, across API generations.

    Revit 2021+ exposes ``Definition.GetDataType()`` returning a
    ForgeTypeId such as ``autodesk.spec.aec:length-2.0.0``; older
    versions only have the ``UnitType`` enum (``UT_Length``).
    """
    d = param.Definition
    try:
        tid = _text(d.GetDataType().TypeId).lower()
        if u":" in tid:
            tid = tid.split(u":", 1)[1]
        return tid.split(u"-", 1)[0]
    except Exception:
        pass
    try:
        return _text(d.UnitType).lower()
    except Exception:
        return u""


# Order matters: "sectionarea" must match area, not length.
_VOLUME_HINTS = ("volume",)
_AREA_HINTS = ("area",)
_ANGLE_HINTS = ("angle", "rotation", "slope")
_LENGTH_HINTS = ("length", "size", "diameter", "thickness", "roughness",
                 "distance", "elevation", "displacement", "width", "height")


def _convert_double(raw, leaf):
    """(value, unit) for a double parameter; unit u'' means Revit internal."""
    if any(h in leaf for h in _VOLUME_HINTS):
        return raw * CUFT_TO_M3, u"m3"
    if any(h in leaf for h in _AREA_HINTS):
        return raw * SQFT_TO_M2, u"m2"
    if any(h in leaf for h in _ANGLE_HINTS):
        return math.degrees(raw), u"deg"
    if any(h in leaf for h in _LENGTH_HINTS):
        return raw * FT_TO_M, u"m"
    return raw, u""


def _param_value(param):
    """Canonical (value, unit, value_text) for one Parameter.

    ``value`` is a number for doubles/integers, text for strings and
    ``Name [id]`` for ElementId parameters. ``value_text`` carries what
    Revit itself would display (project units, user locale) and is only
    filled for doubles, where it is the safety net for any spec this
    code did not convert.
    """
    try:
        st = param.StorageType
    except Exception:
        return None, u"", u""

    try:
        if st == DB.StorageType.String:
            return param.AsString(), u"", u""

        if st == DB.StorageType.Integer:
            v = param.AsInteger()
            leaf = _spec_leaf(param)
            if u"yesno" in leaf or u"ut_yesno" in leaf:
                return bool(v), u"", u""
            return v, u"", u""

        if st == DB.StorageType.Double:
            raw = param.AsDouble()
            value, unit = _convert_double(raw, _spec_leaf(param))
            try:
                vtext = _text(param.AsValueString())
            except Exception:
                vtext = u""
            return value, unit, vtext

        if st == DB.StorageType.ElementId:
            eid = param.AsElementId()
            n = _id_int(eid)
            if n is None or n < 0:
                return None, u"", u""
            nm = _elem_name(doc.GetElement(eid))
            return (u"{} [{}]".format(nm, n) if nm else n), u"", u""
    except Exception:
        pass
    return None, u"", u""


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, STRING_TYPES) and not value.strip():
        return True
    return False


def _write_params(csv, owner_id, element):
    """Write every non-empty parameter of one element. Returns rows added."""
    n = 0
    try:
        params = element.Parameters
    except Exception:
        return 0
    for p in params:
        try:
            name = _text(p.Definition.Name)
        except Exception:
            continue
        value, unit, vtext = _param_value(p)
        if _is_empty(value):
            continue
        try:
            storage = _text(p.StorageType).replace(u"StorageType.", u"")
        except Exception:
            storage = u""
        csv.row([owner_id, name, value, unit, vtext, storage,
                 bool(getattr(p, "IsShared", False))])
        n += 1
    return n


_BIP_CACHE = {}


def _bip(name):
    """BuiltInParameter by name, or None if this Revit version lacks it.

    Looked up by name on purpose: ``DB.BuiltInParameter.FOO`` is evaluated
    at the call site, so a name that a given Revit version dropped would
    raise before the callee's try/except could swallow it.
    """
    if name not in _BIP_CACHE:
        _BIP_CACHE[name] = getattr(DB.BuiltInParameter, name, None)
    return _BIP_CACHE[name]


def _bip_value(element, *names):
    """First non-empty value among a list of BuiltInParameter names."""
    for name in names:
        bip = _bip(name)
        if bip is None:
            continue
        try:
            p = element.get_Parameter(bip)
        except Exception:
            continue
        if p is None or not p.HasValue:
            continue
        value, _unit, _vt = _param_value(p)
        if not _is_empty(value):
            return value
    return None


# ============================================================
# Element context helpers
# ============================================================

def _level_name(element):
    try:
        lid = element.LevelId
        if lid is not None and _id_int(lid) > 0:
            return _elem_name(doc.GetElement(lid))
    except Exception:
        pass
    v = _bip_value(element,
                   "SCHEDULE_LEVEL_PARAM",
                   "FAMILY_LEVEL_PARAM",
                   "INSTANCE_REFERENCE_LEVEL_PARAM",
                   "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM",
                   "RBS_START_LEVEL_PARAM")
    if isinstance(v, STRING_TYPES) and u"[" in v:
        return v.rsplit(u" [", 1)[0]
    return v


def _workset_name(element, wtable):
    if wtable is None:
        return None
    try:
        return _text(wtable.GetWorkset(element.WorksetId).Name)
    except Exception:
        return None


def _location(element):
    """(x, y, z, length_m) in metres from the element Location."""
    try:
        loc = element.Location
    except Exception:
        return None, None, None, None
    if loc is None:
        return None, None, None, None
    try:
        if isinstance(loc, DB.LocationPoint):
            p = loc.Point
            return p.X * FT_TO_M, p.Y * FT_TO_M, p.Z * FT_TO_M, None
        if isinstance(loc, DB.LocationCurve):
            c = loc.Curve
            p = c.GetEndPoint(0)
            try:
                ln = c.Length * FT_TO_M
            except Exception:
                ln = None
            return p.X * FT_TO_M, p.Y * FT_TO_M, p.Z * FT_TO_M, ln
    except Exception:
        pass
    return None, None, None, None


def _bbox(element):
    try:
        bb = element.get_BoundingBox(None)
    except Exception:
        return [None] * 6
    if bb is None:
        return [None] * 6
    try:
        return [bb.Min.X * FT_TO_M, bb.Min.Y * FT_TO_M, bb.Min.Z * FT_TO_M,
                bb.Max.X * FT_TO_M, bb.Max.Y * FT_TO_M, bb.Max.Z * FT_TO_M]
    except Exception:
        return [None] * 6


def _category_name(element):
    try:
        cat = element.Category
        return _text(cat.Name) if cat is not None else None
    except Exception:
        return None


def _family_name(element_type):
    try:
        fn = _text(element_type.FamilyName)
        if fn:
            return fn
    except Exception:
        pass
    v = _bip_value(element_type, "ALL_MODEL_FAMILY_NAME")
    return _text(v) if v else u""


# ============================================================
# Export
# ============================================================

def export(folder):
    """Write every table. Returns (list_of_csv, cancelled)."""
    files = []
    cancelled = False

    wtable = None
    if doc.IsWorkshared:
        try:
            wtable = doc.GetWorksetTable()
        except Exception:
            wtable = None

    # ---- pass 1: collect ------------------------------------
    instances = [e for e in DB.FilteredElementCollector(doc)
                 .WhereElementIsNotElementType()
                 if _category_name(e)]
    types = [e for e in DB.FilteredElementCollector(doc)
             .WhereElementIsElementType()
             if _category_name(e)]

    inst_per_type = {}
    for e in instances:
        tid = _id_int(e.GetTypeId())
        if tid and tid > 0:
            inst_per_type[tid] = inst_per_type.get(tid, 0) + 1

    # ---- 01 project info ------------------------------------
    csv = Csv(folder, "01_project_info.csv", ["property", "value", "unit"])
    app = doc.Application
    csv.row(["document_title", doc.Title, ""])
    csv.row(["document_path", doc.PathName, ""])
    csv.row(["revit_version", u"{} ({})".format(app.VersionName,
                                                app.VersionBuild), ""])
    csv.row(["exported_at", datetime.datetime.now().isoformat(), ""])
    csv.row(["is_workshared", doc.IsWorkshared, ""])
    csv.row(["element_instances", len(instances), ""])
    csv.row(["element_types", len(types), ""])
    try:
        for p in doc.ProjectInformation.Parameters:
            value, unit, vtext = _param_value(p)
            if not _is_empty(value):
                csv.row([_text(p.Definition.Name), value, unit])
    except Exception as ex:
        logger.debug("project info: %s", ex)
    csv.close()
    files.append(csv)

    # ---- 02 categories / 03 families / 04 types / 05 type params
    fam_rows = {}       # key -> dict
    cat_rows = {}       # category name -> dict

    csv_types = Csv(folder, "04_types.csv",
                    ["type_id", "category", "family", "type",
                     "family_id", "kind", "n_instances"])
    csv_tparams = Csv(folder, "05_type_parameters.csv",
                      ["type_id", "parameter", "value", "unit",
                       "value_text", "storage", "is_shared"])

    with forms.ProgressBar(title="Types  {value}/{max_value}",
                           cancellable=True) as pb:
        for i, et in enumerate(types):
            if pb.cancelled:
                cancelled = True
                break
            pb.update_progress(i + 1, len(types))

            tid = _id_int(et.Id)
            cat = _category_name(et)
            fam = _family_name(et)
            tname = _elem_name(et)
            n_inst = inst_per_type.get(tid, 0)

            fam_id = None
            kind = "system"
            try:
                if isinstance(et, DB.FamilySymbol) and et.Family is not None:
                    fam_id = _id_int(et.Family.Id)
                    kind = "loadable"
            except Exception:
                pass

            csv_types.row([tid, cat, fam, tname, fam_id, kind, n_inst])
            _write_params(csv_tparams, tid, et)

            fkey = fam_id if fam_id is not None else (u"sys", cat, fam)
            f = fam_rows.setdefault(fkey, {"id": fam_id, "name": fam,
                                           "cat": cat, "kind": kind,
                                           "types": 0, "inst": 0})
            f["types"] += 1
            f["inst"] += n_inst

            c = cat_rows.setdefault(cat, {"types": 0, "inst": 0, "fams": set(),
                                          "id": None, "ctype": None})
            c["types"] += 1
            c["fams"].add(fkey)
            if c["id"] is None:
                try:
                    c["id"] = _id_int(et.Category.Id)
                    c["ctype"] = _text(et.Category.CategoryType)
                except Exception:
                    pass

    csv_types.close()
    csv_tparams.close()
    files.extend([csv_types, csv_tparams])

    for e in instances:
        cat = _category_name(e)
        c = cat_rows.setdefault(cat, {"types": 0, "inst": 0, "fams": set(),
                                      "id": None, "ctype": None})
        c["inst"] += 1
        if c["id"] is None:
            try:
                c["id"] = _id_int(e.Category.Id)
                c["ctype"] = _text(e.Category.CategoryType)
            except Exception:
                pass

    csv = Csv(folder, "02_categories.csv",
              ["category", "category_id", "category_type",
               "n_instances", "n_types", "n_families"])
    for cat in sorted(cat_rows, key=lambda k: _text(k)):
        c = cat_rows[cat]
        csv.row([cat, c["id"], c["ctype"], c["inst"], c["types"],
                 len(c["fams"])])
    csv.close()
    files.append(csv)

    csv = Csv(folder, "03_families.csv",
              ["family_id", "family", "category", "kind",
               "n_types", "n_instances"])
    for f in sorted(fam_rows.values(),
                    key=lambda d: (_text(d["cat"]), _text(d["name"]))):
        csv.row([f["id"], f["name"], f["cat"], f["kind"], f["types"],
                 f["inst"]])
    csv.close()
    files.append(csv)

    if cancelled:
        return files, cancelled

    # ---- 06 elements + 07 element parameters ----------------
    csv_el = Csv(folder, "06_elements.csv",
                 ["element_id", "category", "family", "type", "type_id",
                  "name", "mark", "level", "workset", "design_option",
                  "phase_created", "phase_demolished", "group_id", "host_id",
                  "view_specific", "owner_view",
                  "x", "y", "z", "length_m", "area_m2", "volume_m3",
                  "bbox_min_x", "bbox_min_y", "bbox_min_z",
                  "bbox_max_x", "bbox_max_y", "bbox_max_z"])
    csv_ep = Csv(folder, "07_element_parameters.csv",
                 ["element_id", "parameter", "value", "unit",
                  "value_text", "storage", "is_shared"])

    type_cache = {}
    with forms.ProgressBar(title="Elements  {value}/{max_value}",
                           cancellable=True) as pb:
        for i, e in enumerate(instances):
            if pb.cancelled:
                cancelled = True
                break
            if i % 200 == 0:
                pb.update_progress(i + 1, len(instances))

            eid = _id_int(e.Id)
            tid = _id_int(e.GetTypeId())
            if tid in type_cache:
                fam, tname = type_cache[tid]
            else:
                et = doc.GetElement(e.GetTypeId()) if tid and tid > 0 else None
                fam = _family_name(et) if et is not None else u""
                tname = _elem_name(et) if et is not None else u""
                type_cache[tid] = (fam, tname)

            x, y, z, length = _location(e)
            if length is None:
                length = _bip_value(e, "CURVE_ELEM_LENGTH",
                                    "INSTANCE_LENGTH_PARAM")
            area = _bip_value(e, "HOST_AREA_COMPUTED", "ROOM_AREA")
            volume = _bip_value(e, "HOST_VOLUME_COMPUTED", "ROOM_VOLUME")

            try:
                dopt = _elem_name(e.DesignOption)
            except Exception:
                dopt = None
            try:
                gid = _id_int(e.GroupId)
                gid = gid if gid and gid > 0 else None
            except Exception:
                gid = None
            try:
                hid = _id_int(e.Host.Id) if getattr(e, "Host", None) else None
            except Exception:
                hid = None
            try:
                vs = bool(e.ViewSpecific)
                ov = _elem_name(doc.GetElement(e.OwnerViewId)) if vs else None
            except Exception:
                vs, ov = None, None

            bb = _bbox(e)
            csv_el.row([eid, _category_name(e), fam, tname, tid,
                        _elem_name(e),
                        _bip_value(e, "ALL_MODEL_MARK"),
                        _level_name(e), _workset_name(e, wtable), dopt,
                        _bip_value(e, "PHASE_CREATED"),
                        _bip_value(e, "PHASE_DEMOLISHED"),
                        gid, hid, vs, ov,
                        x, y, z, length, area, volume] + bb)
            _write_params(csv_ep, eid, e)

    csv_el.close()
    csv_ep.close()
    files.extend([csv_el, csv_ep])

    if cancelled:
        return files, cancelled

    # ---- 08 parameter definitions ---------------------------
    bindings = {}
    try:
        it = doc.ParameterBindings.ForwardIterator()
        it.Reset()
        while it.MoveNext():
            d, b = it.Key, it.Current
            kind = "instance" if isinstance(b, DB.InstanceBinding) else "type"
            cats = sorted(_text(c.Name) for c in b.Categories)
            bindings[_text(d.Name)] = (kind, u"; ".join(cats))
    except Exception as ex:
        logger.debug("bindings: %s", ex)

    csv = Csv(folder, "08_parameter_definitions.csv",
              ["parameter", "is_shared", "guid", "data_type", "group",
               "binding", "categories"])
    for pe in DB.FilteredElementCollector(doc).OfClass(DB.ParameterElement):
        try:
            d = pe.GetDefinition()
        except Exception:
            continue
        name = _text(d.Name)
        guid = u""
        shared = isinstance(pe, DB.SharedParameterElement)
        if shared:
            try:
                guid = _text(pe.GuidValue)
            except Exception:
                pass
        try:
            dtype = _text(d.GetDataType().TypeId)
        except Exception:
            dtype = _text(getattr(d, "ParameterType", u""))
        try:
            group = _text(d.GetGroupTypeId().TypeId)
        except Exception:
            group = _text(getattr(d, "ParameterGroup", u""))
        kind, cats = bindings.get(name, (u"", u""))
        csv.row([name, shared, guid, dtype, group, kind, cats])
    csv.close()
    files.append(csv)

    # ---- 09 levels ------------------------------------------
    csv = Csv(folder, "09_levels.csv", ["level_id", "name", "elevation_m"])
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    for lv in sorted(levels, key=lambda l: l.Elevation):
        csv.row([_id_int(lv.Id), _elem_name(lv), lv.Elevation * FT_TO_M])
    csv.close()
    files.append(csv)

    # ---- 10 rooms & spaces ----------------------------------
    csv = Csv(folder, "10_rooms_spaces.csv",
              ["element_id", "kind", "number", "name", "level",
               "area_m2", "volume_m3", "perimeter_m", "placed"])
    for bic, kind in ((DB.BuiltInCategory.OST_Rooms, "room"),
                      (DB.BuiltInCategory.OST_MEPSpaces, "space")):
        try:
            spatial = (DB.FilteredElementCollector(doc).OfCategory(bic)
                       .WhereElementIsNotElementType())
        except Exception:
            continue
        for sp in spatial:
            try:
                area = sp.Area * SQFT_TO_M2
            except Exception:
                area = None
            try:
                vol = sp.Volume * CUFT_TO_M3
            except Exception:
                vol = None
            csv.row([_id_int(sp.Id), kind, _bip_value(sp, "ROOM_NUMBER"),
                     _elem_name(sp), _level_name(sp), area, vol,
                     _bip_value(sp, "ROOM_PERIMETER"), bool(area)])
    csv.close()
    files.append(csv)

    # ---- 11 worksets ----------------------------------------
    csv = Csv(folder, "11_worksets.csv",
              ["workset_id", "name", "kind", "is_open", "is_editable",
               "owner"])
    if doc.IsWorkshared:
        try:
            for ws in DB.FilteredWorksetCollector(doc):
                csv.row([ws.Id.IntegerValue, _text(ws.Name),
                         _text(ws.Kind), ws.IsOpen, ws.IsEditable,
                         _text(ws.Owner)])
        except Exception as ex:
            logger.debug("worksets: %s", ex)
    csv.close()
    files.append(csv)

    # ---- 12 links -------------------------------------------
    csv = Csv(folder, "12_links.csv",
              ["element_id", "kind", "name", "path", "is_loaded", "pinned"])
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        path, loaded = u"", None
        try:
            lt = doc.GetElement(li.GetTypeId())
            eref = lt.GetExternalFileReference()
            path = _text(DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(
                eref.GetAbsolutePath()))
            loaded = (eref.GetLinkedFileStatus() ==
                      DB.LinkedFileStatus.Loaded)
        except Exception:
            pass
        csv.row([_id_int(li.Id), "RVT", _elem_name(li), path, loaded,
                 getattr(li, "Pinned", None)])
    for ii in DB.FilteredElementCollector(doc).OfClass(DB.ImportInstance):
        kind = "DWG-link" if ii.IsLinked else "DWG-import"
        csv.row([_id_int(ii.Id), kind, _elem_name(doc.GetElement(
            ii.GetTypeId())), u"", None, getattr(ii, "Pinned", None)])
    csv.close()
    files.append(csv)

    # ---- 13 materials ---------------------------------------
    csv = Csv(folder, "13_materials.csv",
              ["material_id", "name", "class", "category"])
    for m in DB.FilteredElementCollector(doc).OfClass(DB.Material):
        csv.row([_id_int(m.Id), _elem_name(m), _text(m.MaterialClass),
                 _text(m.MaterialCategory)])
    csv.close()
    files.append(csv)

    # ---- 14 views & sheets ----------------------------------
    csv = Csv(folder, "14_views_sheets.csv",
              ["element_id", "kind", "name", "view_type", "sheet_number",
               "is_template", "scale", "discipline", "on_sheet"])
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        # Scale/Discipline/ViewType throw on some view kinds (legends,
        # schedules, browser views), so each field is read on its own.
        is_sheet = isinstance(v, DB.ViewSheet)
        csv.row([_id_int(v.Id), "sheet" if is_sheet else "view",
                 _elem_name(v), _safe(v, "ViewType"),
                 _safe(v, "SheetNumber") if is_sheet else u"",
                 _safe(v, "IsTemplate"),
                 None if is_sheet else _safe(v, "Scale"),
                 _safe(v, "Discipline"),
                 _bip_value(v, "VIEWPORT_SHEET_NUMBER")])
    csv.close()
    files.append(csv)

    # ---- 15 warnings ----------------------------------------
    csv = Csv(folder, "15_warnings.csv",
              ["description", "severity", "n_elements", "element_ids"])
    try:
        for w in doc.GetWarnings():
            ids = [_id_int(i) for i in w.GetFailingElements()]
            csv.row([_text(w.GetDescriptionText()), _text(w.GetSeverity()),
                     len(ids), u"; ".join(_text(i) for i in ids)])
    except Exception as ex:
        logger.debug("warnings: %s", ex)
    csv.close()
    files.append(csv)

    return files, cancelled


# ============================================================
# 00_INDEX.md - the schema, spelled out for the LLM
# ============================================================

TABLE_NOTES = {
    "01_project_info.csv": "Document identity plus every Project Information parameter, one row per property.",
    "02_categories.csv": "One row per Revit category actually present, with instance/type/family counts. Start here to size up the model.",
    "03_families.csv": "One row per family. `kind` is `loadable` (a .rfa) or `system` (walls, pipes, ducts... families built into Revit). `family_id` is empty for system families - they are not elements in the document - so join those on `category` + `family` instead.",
    "04_types.csv": "One row per element type (family type). Join to 03 on `family_id` (loadable) or on `category` + `family` (system), and to 05/06 on `type_id`.",
    "05_type_parameters.csv": "Long format: one row per (type, parameter). Every non-empty type parameter, built-in and shared.",
    "06_elements.csv": "One row per placed element instance. Wide: the columns everybody needs (category, family, type, level, workset, phase, geometry).",
    "07_element_parameters.csv": "Long format: one row per (element, parameter). Instance parameters only and only when non-empty - type parameters live in 05, joinable via 06.type_id.",
    "08_parameter_definitions.csv": "The parameter schema: shared/project parameters, their GUID, data type, instance-or-type binding and the categories they are bound to.",
    "09_levels.csv": "Levels sorted by elevation.",
    "10_rooms_spaces.csv": "Rooms and MEP spaces. `placed` is false for unplaced/unbounded ones (area 0).",
    "11_worksets.csv": "User worksets. Empty if the model is not workshared.",
    "12_links.csv": "Linked Revit models and linked/imported CAD.",
    "13_materials.csv": "Material library actually in the document.",
    "14_views_sheets.csv": "Views, sheets and view templates.",
    "15_warnings.csv": "The Revit warning list - the model's open issues, one row per warning.",
}

INDEX_TEMPLATE = u"""# Model export - {title}

Structured dump of a Revit model, exported so an AI assistant can analyse it
by reading these tables instead of querying Revit element by element.

- **Model**: `{path}`
- **Revit**: {version}
- **Exported**: {when}
- **Instances**: {n_inst} | **Types**: {n_types}{partial}

## Conventions

- CSV, comma separated, UTF-8 with BOM, CRLF rows, RFC 4180 quoting.
  `pandas.read_csv(path)` reads them as-is.
- **Units are metric**: `_m` = metres, `_m2` = square metres, `_m3` = cubic
  metres, angles in degrees. Coordinates are Revit internal (project) coords
  converted to metres.
- **Keys**: `element_id` and `type_id` are Revit ElementIds and are the join
  keys across every table: `06_elements.type_id` -> `04_types.type_id`, and
  `04_types.family_id` -> `03_families.family_id` for loadable families
  (system families carry no `family_id`; join them on `category` + `family`).
- **Empty cells mean "not set"**, not zero.
- The two `*_parameters.csv` tables are **long format** (one row per
  parameter). Pivot them when you need a wide view:
  `df.pivot_table(index='element_id', columns='parameter', values='value',
  aggfunc='first')`.
- In the parameter tables, `value` is the canonical value (number for
  numeric parameters, `Name [id]` for parameters that point at another
  element) and `unit` is its unit. **`unit` empty on a `Double` row means
  the value is in Revit internal units** (feet-based) because the parameter's
  unit spec was not recognised - use `value_text`, which is what Revit itself
  displays, in that case.

## Tables

{tables}

## Reading a model, in order

1. `02_categories.csv` - what is in the model and how much of it.
2. `03_families.csv` / `04_types.csv` - the catalogue behind those counts.
3. `08_parameter_definitions.csv` - which shared/project parameters exist and
   where they are bound. This is the answer to "does the model carry X?".
4. `06_elements.csv` - filter to the category you care about, then join
   `07_element_parameters.csv` on `element_id` for the details.
5. `15_warnings.csv` - where the model is unhealthy.
"""


def write_index(folder, files, cancelled):
    rows = []
    by_name = dict((f.name, f) for f in files)
    for name in sorted(TABLE_NOTES):
        f = by_name.get(name)
        if f is None:
            continue
        rows.append(u"### `{}` - {} rows\n\n{}\n\n**Columns**: {}\n".format(
            name, f.rows, TABLE_NOTES[name],
            u", ".join(u"`{}`".format(c) for c in f.header)))

    app = doc.Application
    text = INDEX_TEMPLATE.format(
        title=_text(doc.Title),
        path=_text(doc.PathName) or u"(unsaved)",
        version=u"{} ({})".format(app.VersionName, app.VersionBuild),
        when=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_inst=by_name["06_elements.csv"].rows if "06_elements.csv" in by_name
        else u"?",
        n_types=by_name["04_types.csv"].rows if "04_types.csv" in by_name
        else u"?",
        partial=(u"\n- **INCOMPLETE**: the export was cancelled, tables below "
                 u"are partial." if cancelled else u""),
        tables=u"\n".join(rows))
    path = os.path.join(folder, "00_INDEX.md")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ============================================================
# Entry point
# ============================================================

if doc.IsFamilyDocument:
    forms.alert("This tool exports a project. Open a project document "
                "(.rvt), not a family.", exitscript=True)

folder = os.path.join(BASE_DIR, u"{}_{}".format(
    _safe_dirname(doc.Title),
    datetime.datetime.now().strftime("%Y-%m-%d_%H%M")))
if not os.path.exists(folder):
    os.makedirs(folder)

files, cancelled = export(folder)
index = write_index(folder, files, cancelled)

total = sum(f.rows for f in files)
output.print_md("## Model export {}".format(
    "cancelled (partial)" if cancelled else "complete"))
output.print_md("**{}** rows across **{}** tables -> `{}`".format(
    total, len(files), folder))
for f in sorted(files, key=lambda x: x.name):
    output.print_md("- `{}` - {} rows".format(f.name, f.rows))
output.print_md("Hand `00_INDEX.md` to the AI first: it documents the schema.")

os.startfile(folder)
