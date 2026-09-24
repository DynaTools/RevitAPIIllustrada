# -*- coding: utf-8 -*-
"""Read the CURRENT cloud Model GUID of ACC files from the LOCAL Desktop
Connector cache - no APS API, no Account Admin approval required.

Why this exists
---------------
Re-linking broken ACC cloud links needs the *current* Model GUID of each file
(by name). The official way is the APS Data Management API, but that requires
the ACC Account Admin to whitelist a custom integration - impossible when the
ACC belongs to a client.

Desktop Connector already syncs that information locally. For every cloud
folder it keeps a LiteDB file::

    %LOCALAPPDATA%\\Autodesk\\Desktop Connector\\Data\\
        Autodesk.DataSourceType.BIMDocs\\<folder-urn-base64>.properties.db

Inside, the ``FileSystemProperties`` collection has one document per file::

    _id      = urn:adsk.wipprod:dm.lineage:<base64url-guid>   (the Model GUID!)
    MetaData = { "Data": { "HubId", "ProjectId", "ParentFolderUrn",
                           "Name", "StorageUrn", ... } }

The trailing base64url segment of the lineage URN decodes to the 16 bytes of
the .NET ``System.Guid`` that ``ModelPathUtils.ConvertCloudGUIDsToCloudPath``
expects, and the URN prefix (``wipprod`` / ``wipemea``) tells the region.

This module loads ``LiteDB.dll`` (shipped with Desktop Connector) through
pythonnet/clr - available both in the pyRevit CPython engine and standalone.

NOTE: this reads Desktop Connector's *internal, undocumented* store. It works
with Desktop Connector 16.x / LiteDB 5.x but Autodesk may change it without
notice. If it ever stops working, fall back to the APS API path.
"""

import base64
import glob
import json
import os

import clr  # pythonnet (pyRevit CPython engine) / standalone

# ----------------------------------------------------------------------------
# Locating Desktop Connector files
# ----------------------------------------------------------------------------
_DLL_CANDIDATES = [
    r"C:\Program Files\Autodesk\Desktop Connector\LiteDB.dll",
    r"C:\Program Files (x86)\Autodesk\Desktop Connector\LiteDB.dll",
]


def find_litedb_dll():
    for p in _DLL_CANDIDATES:
        if os.path.isfile(p):
            return p
    # Broad search as a fallback.
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)",
                                r"C:\Program Files (x86)")):
        pattern = os.path.join(base, "Autodesk", "Desktop Connector",
                               "LiteDB.dll")
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


def find_data_dir():
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
        r"~\AppData\Local")
    d = os.path.join(local, "Autodesk", "Desktop Connector", "Data",
                     "Autodesk.DataSourceType.BIMDocs")
    return d if os.path.isdir(d) else None


# ----------------------------------------------------------------------------
# URN / GUID helpers (same contract as acc_api)
# ----------------------------------------------------------------------------
def lineage_urn_to_guid_bytes(item_id):
    """Decode an ACC item lineage URN to the 16 GUID bytes Revit expects."""
    seg = item_id.split(":")[-1]
    seg += "=" * (-len(seg) % 4)
    raw = base64.urlsafe_b64decode(seg)
    if len(raw) != 16:
        raise ValueError("URN nao decodifica para 16 bytes: %s" % item_id)
    return raw


def project_id_to_guid_str(project_id):
    """ACC project id 'b.<guid>' -> '<guid>'."""
    return project_id[2:] if project_id.startswith("b.") else project_id


def region_from_urn(urn):
    """Map the wip data-center in a URN to a Revit cloud region string."""
    u = (urn or "").lower()
    if ":adsk.wipemea:" in u:
        return "EMEA"
    # wipprod is the global / US data center.
    return "US"


# ----------------------------------------------------------------------------
# LiteDB access
# ----------------------------------------------------------------------------
_LITEDB_LOADED = False


def _ensure_litedb(dll_path):
    global _LITEDB_LOADED
    if not _LITEDB_LOADED:
        clr.AddReference(dll_path)
        _LITEDB_LOADED = True
    from LiteDB import (LiteDatabase, ConnectionString, BsonDocument,
                        ConnectionType)
    return LiteDatabase, ConnectionString, BsonDocument, ConnectionType


def _open_db(db_path, LiteDatabase, ConnectionString, ConnectionType):
    """Open a LiteDB file read-only/shared. Returns a LiteDatabase or None."""
    cs = ConnectionString()
    cs.Filename = db_path
    try:
        cs.ReadOnly = True
    except Exception:
        pass
    try:
        cs.Connection = ConnectionType.Shared
    except Exception:
        pass
    try:
        return LiteDatabase(cs)
    except Exception:
        # Locked / exclusive: copy to temp and retry.
        try:
            import tempfile
            import shutil
            tmp = os.path.join(tempfile.gettempdir(),
                               "dcidx_" + os.path.basename(db_path))
            shutil.copyfile(db_path, tmp)
            cs2 = ConnectionString()
            cs2.Filename = tmp
            try:
                cs2.ReadOnly = True
            except Exception:
                pass
            return LiteDatabase(cs2)
        except Exception:
            return None


def _parse_doc(doc):
    """Turn a FileSystemProperties BsonDocument into a plain dict, or None."""
    try:
        lineage = doc["_id"].AsString
    except Exception:
        return None
    if not lineage or "dm.lineage:" not in lineage:
        return None

    meta_raw = None
    try:
        bv = doc["MetaData"]
        if bv is not None:
            meta_raw = bv.AsString
    except Exception:
        meta_raw = None
    if not meta_raw:
        return None

    name = project_id = folder_urn = hub_id = None
    try:
        meta = json.loads(meta_raw)
        data = meta.get("Data")
        if isinstance(data, str):
            data = json.loads(data)
        if isinstance(data, dict):
            name = data.get("Name")
            project_id = data.get("ProjectId")
            folder_urn = data.get("ParentFolderUrn")
            hub_id = data.get("HubId")
    except Exception:
        return None

    if not name or not project_id:
        return None

    version = None
    created_at = None
    try:
        sp = doc["SerializedProperties"]
        if sp is not None:
            props = json.loads(sp.AsString)
            vl = props.get("Autodesk.DesktopConnector.Docs.VersionLabel")
            if isinstance(vl, dict):
                version = vl.get("Value")
            ca = props.get("Autodesk.DesktopConnector.Docs.CloudCreatedAt")
            if isinstance(ca, dict):
                created_at = ca.get("Value")
    except Exception:
        pass

    return {
        "name": name,
        "name_lower": name.strip().lower(),
        "lineage_urn": lineage,
        "project_id": project_id,
        "project_guid": project_id_to_guid_str(project_id),
        "folder_urn": folder_urn,
        "hub_id": hub_id,
        "region": region_from_urn(lineage),
        "version": version,
        "created_at": created_at,
    }


def build_index(only_rvt=True, dll_path=None, data_dir=None):
    """Scan every Desktop Connector folder DB and index files by name.

    Returns ``{lower_name: [entry, ...]}``. Each entry is the dict from
    ``_parse_doc``. Entries for the same name are de-duplicated by lineage and
    sorted newest-first (so caller can prefer the current item).

    Raises ``RuntimeError`` if Desktop Connector data/DLL cannot be found.
    """
    dll_path = dll_path or find_litedb_dll()
    if not dll_path:
        raise RuntimeError(
            "LiteDB.dll do Desktop Connector nao encontrado. O Desktop "
            "Connector esta instalado?")
    data_dir = data_dir or find_data_dir()
    if not data_dir:
        raise RuntimeError(
            "Pasta de dados do Desktop Connector nao encontrada. Faca login "
            "no Desktop Connector e sincronize o projeto ao menos uma vez.")

    LiteDatabase, ConnectionString, BsonDocument, ConnectionType = \
        _ensure_litedb(dll_path)

    index = {}
    seen_lineage = set()
    dbs = glob.glob(os.path.join(data_dir, "*.properties.db"))
    for db_path in dbs:
        db = _open_db(db_path, LiteDatabase, ConnectionString, ConnectionType)
        if db is None:
            continue
        try:
            col = db.GetCollection[BsonDocument]("FileSystemProperties")
            for doc in col.FindAll():
                entry = _parse_doc(doc)
                if not entry:
                    continue
                if only_rvt and not entry["name_lower"].endswith(".rvt"):
                    continue
                if entry["lineage_urn"] in seen_lineage:
                    continue
                seen_lineage.add(entry["lineage_urn"])
                index.setdefault(entry["name_lower"], []).append(entry)
        finally:
            try:
                db.Dispose()
            except Exception:
                pass

    # Newest first within each name (helps pick the current item).
    for key in index:
        index[key].sort(key=lambda e: (e.get("created_at") or "",
                                       e.get("version") or 0),
                        reverse=True)
    return index


def distinct_projects(index):
    """Return {project_id: count_of_files} across the whole index."""
    projects = {}
    for entries in index.values():
        for e in entries:
            projects[e["project_id"]] = projects.get(e["project_id"], 0) + 1
    return projects


def folders_by_urn(index):
    """Return {folder_urn: {name_lower: entry}} (newest entry per name).

    Lets callers restrict re-linking to a single cloud folder.
    """
    folders = {}
    for entries in index.values():
        for e in entries:
            fu = e.get("folder_urn")
            if not fu:
                continue
            bucket = folders.setdefault(fu, {})
            cur = bucket.get(e["name_lower"])
            if cur is None or (e.get("created_at") or "") > (
                    cur.get("created_at") or ""):
                bucket[e["name_lower"]] = e
    return folders


def _local_rvt_names(local_folder):
    """Set of lowercased .rvt file names directly inside ``local_folder``.

    Ignores subfolders (e.g. Desktop Connector ``*_backup`` folders).
    """
    out = set()
    try:
        for n in os.listdir(local_folder):
            full = os.path.join(local_folder, n)
            if n.lower().endswith(".rvt") and os.path.isfile(full):
                out.add(n.strip().lower())
    except Exception:
        pass
    return out


def resolve_local_folder(index, local_folder, folders=None):
    """Map a LOCAL Desktop Connector folder to its cloud folder URN.

    Matches by file-name overlap (a local folder mirrors exactly one cloud
    folder). Returns a dict with ``folder_urn``, ``region``, ``project_id``,
    ``matched`` and ``total``; or ``None`` if nothing matches.
    """
    folders = folders if folders is not None else folders_by_urn(index)
    local = _local_rvt_names(local_folder)
    if not local:
        return None

    best_urn = None
    best_score = 0
    for fu, names in folders.items():
        score = len(local & set(names.keys()))
        if score > best_score:
            best_score = score
            best_urn = fu

    if not best_urn or best_score == 0:
        return None

    rep = next(iter(folders[best_urn].values()))
    return {
        "folder_urn": best_urn,
        "region": rep["region"],
        "project_id": rep["project_id"],
        "matched": best_score,
        "total": len(local),
    }


def lookup(index, name, project_id=None, folder_urn=None):
    """Return the list of entries matching ``name`` (with/without .rvt),
    optionally filtered to a ``project_id`` and/or a ``folder_urn``.
    Newest first."""
    low = (name or "").strip().lower()
    keys = [low]
    if low.endswith(".rvt"):
        keys.append(low[:-4])
    else:
        keys.append(low + ".rvt")

    out = []
    seen = set()
    for k in keys:
        for e in index.get(k, []):
            if project_id and e["project_id"] != project_id:
                continue
            if folder_urn and e.get("folder_urn") != folder_urn:
                continue
            if e["lineage_urn"] in seen:
                continue
            seen.add(e["lineage_urn"])
            out.append(e)
    return out
