# -*- coding: utf-8 -*-
"""Despeja o modelo inteiro em uma pasta de tabelas CSV fáceis de ler para um LLM.

A ideia desta ferramenta é pagar o custo de ler o modelo *uma vez só*:
depois, um assistente de IA pode responder a perguntas sobre categorias,
famílias, tipos e parâmetros lendo CSVs planos, em vez de consultar o Revit
elemento por elemento.

Organização: as tabelas principais (elementos, tipos) são largas, as de
parâmetros são longas (uma linha por parâmetro), e o 00_INDEX.md documenta o
esquema para que o LLM não precise adivinhá-lo.
"""

__title__ = "Export\nModel\nCSV"
__author__ = "Paulo Giavoni"
__doc__ = (u"Exporta o modelo inteiro (categorias, famílias, tipos, "
           u"parâmetros, níveis, ambientes, worksets, links, materiais, vistas "
           u"e avisos) para uma pasta de tabelas CSV, mais um 00_INDEX.md "
           u"que descreve o esquema, pronto para entregar a um assistente de IA.")

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

# Interno (imperial) -> métrico
FT_TO_M = 0.3048
SQFT_TO_M2 = 0.09290304
CUFT_TO_M3 = 0.028316846592

try:                       # IronPython 2.7 vs 3.x / CPython
    STRING_TYPES = (str, unicode)   # noqa: F821
except NameError:
    STRING_TYPES = (str,)


# ============================================================
# Pequenos utilitários
# ============================================================

def _id_int(eid):
    """Valor numérico de um ElementId em qualquer versão do Revit.

    ``ElementId.IntegerValue`` foi removido no Revit 2026 e ``Value``
    só existe a partir do Revit 2024, então é preciso tentar as duas grafias.
    """
    if eid is None:
        return None
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _text(v):
    """Texto unicode, dentro do possível, para tudo o que a API do Revit devolve."""
    if v is None:
        return u""
    if isinstance(v, STRING_TYPES):
        return v
    try:
        return u"{}".format(v)
    except Exception:
        return u""


def _elem_name(el):
    """Element.Name, tolerando as classes em que a propriedade fica oculta."""
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
    """Lê uma propriedade que em algumas subclasses dispara exceção (ex.: View.Scale)."""
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
# Escrita CSV (RFC 4180, em fluxo - sem listas grandes na memória)
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
    """Gravador CSV em fluxo: utf-8 com BOM, separado por vírgula, linhas CRLF."""

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
# Leitura dos parâmetros
# ============================================================

def _spec_leaf(param):
    """Nome da especificação de unidade de um parâmetro, em minúsculas, em
    todas as gerações da API.

    O Revit 2021+ expõe ``Definition.GetDataType()``, que devolve um
    ForgeTypeId como ``autodesk.spec.aec:length-2.0.0``; as versões mais
    antigas só têm o enum ``UnitType`` (``UT_Length``).
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


# A ordem importa: "sectionarea" deve cair em área, não em comprimento.
_VOLUME_HINTS = ("volume",)
_AREA_HINTS = ("area",)
_ANGLE_HINTS = ("angle", "rotation", "slope")
_LENGTH_HINTS = ("length", "size", "diameter", "thickness", "roughness",
                 "distance", "elevation", "displacement", "width", "height")


def _convert_double(raw, leaf):
    """(valor, unidade) de um parâmetro double; unidade u'' = unidade interna do Revit."""
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
    """(value, unit, value_text) canônicos de um Parameter.

    ``value`` é um número para doubles/inteiros, texto para strings e
    ``Nome [id]`` para parâmetros ElementId. ``value_text`` traz o que o
    próprio Revit mostraria (unidades do projeto, idioma do usuário) e só é
    preenchido para doubles, onde é a rede de segurança para qualquer
    especificação que este código não converteu.
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
    """Grava todos os parâmetros não vazios de um elemento. Devolve as linhas acrescentadas."""
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
    """BuiltInParameter pelo nome, ou None se esta versão do Revit não o tiver.

    A busca é pelo nome de propósito: ``DB.BuiltInParameter.FOO`` é avaliado
    no ponto da chamada, então um nome que uma versão do Revit abandonou
    dispararia a exceção antes que o try/except da função chamada a engolisse.
    """
    if name not in _BIP_CACHE:
        _BIP_CACHE[name] = getattr(DB.BuiltInParameter, name, None)
    return _BIP_CACHE[name]


def _bip_value(element, *names):
    """Primeiro valor não vazio em uma lista de nomes de BuiltInParameter."""
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
# Auxiliares de contexto dos elementos
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
    """(x, y, z, length_m) em metros, a partir da Location do elemento."""
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
# Exportação
# ============================================================

def export(folder):
    """Grava todas as tabelas. Devolve (list_of_csv, cancelled)."""
    files = []
    cancelled = False

    wtable = None
    if doc.IsWorkshared:
        try:
            wtable = doc.GetWorksetTable()
        except Exception:
            wtable = None

    # ---- passo 1: coleta ------------------------------------
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

    # ---- 01 informações do projeto --------------------------
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
        logger.debug(u"informações do projeto: %s", ex)
    csv.close()
    files.append(csv)

    # ---- 02 categorias / 03 famílias / 04 tipos / 05 parâmetros de tipo
    fam_rows = {}       # chave -> dict
    cat_rows = {}       # nome da categoria -> dict

    csv_types = Csv(folder, "04_types.csv",
                    ["type_id", "category", "family", "type",
                     "family_id", "kind", "n_instances"])
    csv_tparams = Csv(folder, "05_type_parameters.csv",
                      ["type_id", "parameter", "value", "unit",
                       "value_text", "storage", "is_shared"])

    with forms.ProgressBar(title=u"Tipos  {value}/{max_value}",
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

    # ---- 06 elementos + 07 parâmetros dos elementos ---------
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
    with forms.ProgressBar(title=u"Elementos  {value}/{max_value}",
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

    # ---- 08 definições de parâmetros ------------------------
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
        logger.debug(u"vínculos: %s", ex)

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

    # ---- 09 níveis ------------------------------------------
    csv = Csv(folder, "09_levels.csv", ["level_id", "name", "elevation_m"])
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    for lv in sorted(levels, key=lambda l: l.Elevation):
        csv.row([_id_int(lv.Id), _elem_name(lv), lv.Elevation * FT_TO_M])
    csv.close()
    files.append(csv)

    # ---- 10 ambientes e espaços ------------------------------
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
            logger.debug(u"worksets: %s", ex)
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

    # ---- 13 materiais ---------------------------------------
    csv = Csv(folder, "13_materials.csv",
              ["material_id", "name", "class", "category"])
    for m in DB.FilteredElementCollector(doc).OfClass(DB.Material):
        csv.row([_id_int(m.Id), _elem_name(m), _text(m.MaterialClass),
                 _text(m.MaterialCategory)])
    csv.close()
    files.append(csv)

    # ---- 14 vistas e pranchas --------------------------------
    csv = Csv(folder, "14_views_sheets.csv",
              ["element_id", "kind", "name", "view_type", "sheet_number",
               "is_template", "scale", "discipline", "on_sheet"])
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
        # Scale/Discipline/ViewType disparam exceção em alguns tipos de vista
        # (legendas, tabelas, vistas do navegador), então cada campo é lido à parte.
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

    # ---- 15 avisos ------------------------------------------
    csv = Csv(folder, "15_warnings.csv",
              ["description", "severity", "n_elements", "element_ids"])
    try:
        for w in doc.GetWarnings():
            ids = [_id_int(i) for i in w.GetFailingElements()]
            csv.row([_text(w.GetDescriptionText()), _text(w.GetSeverity()),
                     len(ids), u"; ".join(_text(i) for i in ids)])
    except Exception as ex:
        logger.debug(u"avisos: %s", ex)
    csv.close()
    files.append(csv)

    return files, cancelled


# ============================================================
# 00_INDEX.md - o esquema, explicado por extenso para o LLM
# ============================================================

TABLE_NOTES = {
    "01_project_info.csv": u"Identidade do documento mais todos os parâmetros de Informações do projeto, uma linha por propriedade.",
    "02_categories.csv": u"Uma linha por categoria do Revit efetivamente presente, com as contagens de instâncias/tipos/famílias. Comece por aqui para dimensionar o modelo.",
    "03_families.csv": u"Uma linha por família. `kind` é `loadable` (um .rfa) ou `system` (paredes, tubos, dutos... famílias embutidas no Revit). `family_id` fica vazio nas famílias de sistema - elas não são elementos do documento -, então junte essas por `category` + `family`.",
    "04_types.csv": u"Uma linha por tipo de elemento (tipo de família). Junta-se à 03 por `family_id` (carregáveis) ou por `category` + `family` (sistema), e às 05/06 por `type_id`.",
    "05_type_parameters.csv": u"Formato longo: uma linha por (tipo, parâmetro). Todos os parâmetros de tipo não vazios, nativos e compartilhados.",
    "06_elements.csv": u"Uma linha por instância de elemento colocada. Larga: as colunas de que todo mundo precisa (categoria, família, tipo, nível, workset, fase, geometria).",
    "07_element_parameters.csv": u"Formato longo: uma linha por (elemento, parâmetro). Só parâmetros de instância, e só quando não vazios - os parâmetros de tipo ficam na 05, com junção via 06.type_id.",
    "08_parameter_definitions.csv": u"O esquema dos parâmetros: parâmetros compartilhados/de projeto, o seu GUID, o tipo de dado, o vínculo por instância ou por tipo e as categorias a que estão vinculados.",
    "09_levels.csv": u"Níveis ordenados por elevação.",
    "10_rooms_spaces.csv": u"Ambientes (rooms) e espaços MEP. `placed` é false para os não colocados/não delimitados (área 0).",
    "11_worksets.csv": u"Worksets de usuário. Vazia se o modelo não for compartilhado (workshared).",
    "12_links.csv": u"Modelos Revit vinculados e CAD vinculado/importado.",
    "13_materials.csv": u"A biblioteca de materiais efetivamente presente no documento.",
    "14_views_sheets.csv": u"Vistas, pranchas e templates de vista.",
    "15_warnings.csv": u"A lista de avisos do Revit - as pendências do modelo, uma linha por aviso.",
}

INDEX_TEMPLATE = u"""# Exportação do modelo - {title}

Despejo estruturado de um modelo Revit, exportado para que um assistente de IA
possa analisá-lo lendo estas tabelas, em vez de consultar o Revit elemento por
elemento.

- **Modelo**: `{path}`
- **Revit**: {version}
- **Exportado em**: {when}
- **Instâncias**: {n_inst} | **Tipos**: {n_types}{partial}

## Convenções

- CSV separado por vírgula, UTF-8 com BOM, linhas CRLF, aspas conforme a RFC 4180.
  `pandas.read_csv(path)` os lê como estão.
- **As unidades são métricas**: `_m` = metros, `_m2` = metros quadrados, `_m3` =
  metros cúbicos, ângulos em graus. As coordenadas são as internas do Revit (de
  projeto), convertidas em metros.
- **Chaves**: `element_id` e `type_id` são ElementIds do Revit e são as chaves
  de junção entre todas as tabelas: `06_elements.type_id` -> `04_types.type_id`,
  e `04_types.family_id` -> `03_families.family_id` para as famílias carregáveis
  (as famílias de sistema não têm `family_id`; junte-as por `category` + `family`).
- **Célula vazia significa "não definido"**, não zero.
- As duas tabelas `*_parameters.csv` estão em **formato longo** (uma linha por
  parâmetro). Faça o pivô quando precisar de uma visão larga:
  `df.pivot_table(index='element_id', columns='parameter', values='value',
  aggfunc='first')`.
- Nas tabelas de parâmetros, `value` é o valor canônico (número para os
  parâmetros numéricos, `Nome [id]` para os parâmetros que apontam para outro
  elemento) e `unit` é a sua unidade. **`unit` vazio em uma linha `Double`
  significa que o valor está nas unidades internas do Revit** (baseadas em pés),
  porque a especificação de unidade do parâmetro não foi reconhecida - nesse
  caso use `value_text`, que é o que o próprio Revit mostra.

## Tabelas

{tables}

## Como ler um modelo, em ordem

1. `02_categories.csv` - o que há no modelo e em que quantidade.
2. `03_families.csv` / `04_types.csv` - o catálogo por trás dessas contagens.
3. `08_parameter_definitions.csv` - quais parâmetros compartilhados/de projeto
   existem e onde estão vinculados. É a resposta para "o modelo tem X?".
4. `06_elements.csv` - filtre a categoria que interessa e depois junte
   `07_element_parameters.csv` por `element_id` para ver os detalhes.
5. `15_warnings.csv` - onde o modelo não está saudável.
"""


def write_index(folder, files, cancelled):
    rows = []
    by_name = dict((f.name, f) for f in files)
    for name in sorted(TABLE_NOTES):
        f = by_name.get(name)
        if f is None:
            continue
        rows.append(u"### `{}` - {} linhas\n\n{}\n\n**Colunas**: {}\n".format(
            name, f.rows, TABLE_NOTES[name],
            u", ".join(u"`{}`".format(c) for c in f.header)))

    app = doc.Application
    text = INDEX_TEMPLATE.format(
        title=_text(doc.Title),
        path=_text(doc.PathName) or u"(não salvo)",
        version=u"{} ({})".format(app.VersionName, app.VersionBuild),
        when=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_inst=by_name["06_elements.csv"].rows if "06_elements.csv" in by_name
        else u"?",
        n_types=by_name["04_types.csv"].rows if "04_types.csv" in by_name
        else u"?",
        partial=(u"\n- **INCOMPLETA**: a exportação foi cancelada, as tabelas "
                 u"abaixo estão parciais." if cancelled else u""),
        tables=u"\n".join(rows))
    path = os.path.join(folder, "00_INDEX.md")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ============================================================
# Ponto de entrada
# ============================================================

if doc.IsFamilyDocument:
    forms.alert(u"Esta ferramenta exporta um projeto. Abra um documento de "
                u"projeto (.rvt), não uma família.", exitscript=True)

folder = os.path.join(BASE_DIR, u"{}_{}".format(
    _safe_dirname(doc.Title),
    datetime.datetime.now().strftime("%Y-%m-%d_%H%M")))
if not os.path.exists(folder):
    os.makedirs(folder)

files, cancelled = export(folder)
index = write_index(folder, files, cancelled)

total = sum(f.rows for f in files)
output.print_md(u"## Exportação do modelo {}".format(
    u"cancelada (parcial)" if cancelled else u"concluída"))
output.print_md(u"**{}** linhas em **{}** tabelas -> `{}`".format(
    total, len(files), folder))
for f in sorted(files, key=lambda x: x.name):
    output.print_md(u"- `{}` - {} linhas".format(f.name, f.rows))
output.print_md(u"Entregue primeiro o `00_INDEX.md` à IA: ele documenta o esquema.")

os.startfile(folder)
