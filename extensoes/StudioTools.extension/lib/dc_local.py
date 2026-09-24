# -*- coding: utf-8 -*-
"""Lê o Model GUID de nuvem ATUAL dos arquivos do ACC a partir do cache LOCAL
do Desktop Connector - sem API APS, sem aprovação do Account Admin.

Por que isto existe
-------------------
Revincular links de nuvem do ACC quebrados exige o Model GUID *atual* de cada
arquivo (pelo nome). O caminho oficial é a API Data Management do APS, mas ela
exige que o Account Admin do ACC libere uma integração personalizada - o que é
impossível quando o ACC pertence a um cliente.

O Desktop Connector já sincroniza essa informação localmente. Para cada pasta
de nuvem ele mantém um arquivo LiteDB::

    %LOCALAPPDATA%\\Autodesk\\Desktop Connector\\Data\\
        Autodesk.DataSourceType.BIMDocs\\<folder-urn-base64>.properties.db

Dentro dele, a coleção ``FileSystemProperties`` tem um documento por arquivo::

    _id      = urn:adsk.wipprod:dm.lineage:<base64url-guid>   (o Model GUID!)
    MetaData = { "Data": { "HubId", "ProjectId", "ParentFolderUrn",
                           "Name", "StorageUrn", ... } }

O segmento base64url final da URN de linhagem decodifica nos 16 bytes do
``System.Guid`` do .NET que ``ModelPathUtils.ConvertCloudGUIDsToCloudPath``
espera, e o prefixo da URN (``wipprod`` / ``wipemea``) indica a região.

Este módulo carrega a ``LiteDB.dll`` (que vem com o Desktop Connector) via
pythonnet/clr - disponível tanto no engine CPython do pyRevit quanto avulso.

NOTA: isto lê o armazenamento *interno, não documentado* do Desktop Connector.
Funciona com o Desktop Connector 16.x / LiteDB 5.x, mas a Autodesk pode mudá-lo
sem aviso. Se um dia parar de funcionar, volte para o caminho da API APS.
"""

import base64
import glob
import json
import os

import clr  # pythonnet (engine CPython do pyRevit) / avulso

# ----------------------------------------------------------------------------
# Localização dos arquivos do Desktop Connector
# ----------------------------------------------------------------------------
_DLL_CANDIDATES = [
    r"C:\Program Files\Autodesk\Desktop Connector\LiteDB.dll",
    r"C:\Program Files (x86)\Autodesk\Desktop Connector\LiteDB.dll",
]


def find_litedb_dll():
    for p in _DLL_CANDIDATES:
        if os.path.isfile(p):
            return p
    # Busca ampla, como alternativa.
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
# Auxiliares URN / GUID (mesmo contrato do acc_api)
# ----------------------------------------------------------------------------
def lineage_urn_to_guid_bytes(item_id):
    """Decodifica a URN de linhagem de um item do ACC nos 16 bytes de GUID que o Revit espera."""
    seg = item_id.split(":")[-1]
    seg += "=" * (-len(seg) % 4)
    raw = base64.urlsafe_b64decode(seg)
    if len(raw) != 16:
        raise ValueError("A URN não decodifica para 16 bytes: %s" % item_id)
    return raw


def project_id_to_guid_str(project_id):
    """Id de projeto do ACC 'b.<guid>' -> '<guid>'."""
    return project_id[2:] if project_id.startswith("b.") else project_id


def region_from_urn(urn):
    """Converte o data center wip de uma URN na string de região de nuvem do Revit."""
    u = (urn or "").lower()
    if ":adsk.wipemea:" in u:
        return "EMEA"
    # wipprod é o data center global / dos EUA.
    return "US"


# ----------------------------------------------------------------------------
# Acesso ao LiteDB
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
    """Abre um arquivo LiteDB só leitura/compartilhado. Devolve um LiteDatabase ou None."""
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
        # Bloqueado / exclusivo: copia para a pasta temporária e tenta de novo.
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
    """Converte um BsonDocument de FileSystemProperties em um dict simples, ou None."""
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
    """Varre o DB de cada pasta do Desktop Connector e indexa os arquivos por nome.

    Devolve ``{lower_name: [entry, ...]}``. Cada entrada é o dict de
    ``_parse_doc``. As entradas de um mesmo nome são deduplicadas pela linhagem e
    ordenadas da mais nova para a mais antiga (assim quem chama pode preferir o
    item atual).

    Levanta ``RuntimeError`` se os dados/DLL do Desktop Connector não forem
    encontrados.
    """
    dll_path = dll_path or find_litedb_dll()
    if not dll_path:
        raise RuntimeError(
            "LiteDB.dll do Desktop Connector não encontrada. O Desktop "
            "Connector está instalado?")
    data_dir = data_dir or find_data_dir()
    if not data_dir:
        raise RuntimeError(
            "Pasta de dados do Desktop Connector não encontrada. Faça login "
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

    # Mais novo primeiro dentro de cada nome (ajuda a escolher o item atual).
    for key in index:
        index[key].sort(key=lambda e: (e.get("created_at") or "",
                                       e.get("version") or 0),
                        reverse=True)
    return index


def distinct_projects(index):
    """Devolve {project_id: count_of_files} considerando o índice inteiro."""
    projects = {}
    for entries in index.values():
        for e in entries:
            projects[e["project_id"]] = projects.get(e["project_id"], 0) + 1
    return projects


def folders_by_urn(index):
    """Devolve {folder_urn: {name_lower: entry}} (a entrada mais nova por nome).

    Permite a quem chama restringir a revinculação a uma única pasta de nuvem.
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
    """Conjunto dos nomes de arquivos .rvt, em minúsculas, que estão direto em ``local_folder``.

    Ignora as subpastas (ex.: as pastas ``*_backup`` do Desktop Connector).
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
    """Associa uma pasta LOCAL do Desktop Connector à URN da sua pasta de nuvem.

    A correspondência é pela sobreposição dos nomes de arquivo (uma pasta local
    espelha exatamente uma pasta de nuvem). Devolve um dict com ``folder_urn``,
    ``region``, ``project_id``, ``matched`` e ``total``; ou ``None`` se nada
    corresponder.
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
    """Devolve a lista de entradas que correspondem a ``name`` (com/sem .rvt),
    opcionalmente filtrada por um ``project_id`` e/ou uma ``folder_urn``.
    Mais novas primeiro."""
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
