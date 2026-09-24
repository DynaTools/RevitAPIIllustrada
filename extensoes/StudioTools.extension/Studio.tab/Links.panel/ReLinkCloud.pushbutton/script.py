#! python3
# -*- coding: utf-8 -*-
"""Re-linka pelo NOME os links de nuvem do ACC quebrados, mantendo-os na nuvem.

Por que isto existe
-------------------
No fluxo de coordenação "Consumed", cada publicação cria um item NOVO no
ACC, ou seja, um novo Model GUID. Um link do Revit guarda o GUID antigo, então
quebra (``LinkNotFound``) e ``Reload()`` não o conserta. Re-linkar pelo caminho
local converteria o link em um link de arquivo LOCAL (ruim para a equipe).

Esta ferramenta busca o Model GUID ATUAL de cada arquivo, pelo nome, direto no
cache LOCAL do Desktop Connector (sem APS API, sem aprovação do Account Admin;
por isso funciona mesmo quando o ACC é de um cliente), reconstrói o ModelPath
de nuvem e re-linka NA NUVEM via ``RevitLinkType.LoadFrom``.

Requisitos
----------
* Autodesk Desktop Connector instalado e com login feito.
* O projeto sincronizado no Desktop Connector pelo menos uma vez (para que o
  índice local conheça os Model GUIDs atuais).

NOTA: isto lê o armazenamento interno/não documentado do Desktop Connector via
``lib/dc_local.py``. Funciona hoje (Desktop Connector 16.x), mas a Autodesk pode
mudá-lo sem aviso.
"""

__title__ = "ReLink\nCloud"
__doc__ = (
    "Re-linka pelo nome os links de nuvem do ACC quebrados, usando o cache local "
    "do Desktop Connector. Mantém os links na nuvem (sem converter para local). Mostra uma prévia antes."
)
__author__ = "Paulo Giavoni"

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System
from System.Windows.Forms import (
    Form, Label, Button, TextBox, CheckedListBox, ListBox,
    DialogResult, FormBorderStyle, FormStartPosition, SelectionMode,
    AnchorStyles, Application, FolderBrowserDialog, MessageBox,
)
from System.Drawing import Size, Point

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkType,
    LinkLoadResultType,
    ModelPathUtils,
    WorksetConfiguration,
    WorksetConfigurationOption,
    Element,
)
from Autodesk.Revit.UI import (
    TaskDialog, TaskDialogCommonButtons, TaskDialogResult,
)

import os
import json
import traceback
import datetime

import dc_local

# Documento ativo (protegido: ActiveUIDocument é None quando não há projeto aberto).
_uidoc = __revit__.ActiveUIDocument  # noqa: F821
doc = _uidoc.Document if _uidoc is not None else None


# ============================================================
# AUXILIARES DE UI / CONFIG (sem dependência do pyrevit - roda em CPython)
# ============================================================
_CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "pyRevit_ACC")
_CFG_PATH = os.path.join(_CFG_DIR, "relink_config.json")


def _cfg_load():
    try:
        with open(_CFG_PATH, "r") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _cfg_save(cfg):
    try:
        if not os.path.isdir(_CFG_DIR):
            os.makedirs(_CFG_DIR)
        with open(_CFG_PATH, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


_LOG_PATH = os.path.join(_CFG_DIR, "relink_log.txt")


def _log(text):
    """Acrescenta ao log contínuo, sem nunca falhar, para diagnóstico posterior."""
    try:
        if not os.path.isdir(_CFG_DIR):
            os.makedirs(_CFG_DIR)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (stamp, text))
    except Exception:
        pass


class _ScriptExit(Exception):
    pass


def _alert(msg, title="ReLink Cloud", exit_after=False):
    TaskDialog.Show(title, msg)
    if exit_after:
        raise _ScriptExit()


def _confirm(msg, title="ReLink Cloud"):
    td = TaskDialog(title)
    td.MainInstruction = title
    td.MainContent = msg
    td.CommonButtons = (TaskDialogCommonButtons.Yes |
                        TaskDialogCommonButtons.No)
    td.DefaultButton = TaskDialogResult.No
    return td.Show() == TaskDialogResult.Yes


def _ask_string(prompt, title="ReLink Cloud", default=""):
    f = Form()
    f.Text = title
    f.FormBorderStyle = FormBorderStyle.FixedDialog
    f.StartPosition = FormStartPosition.CenterScreen
    f.ClientSize = Size(460, 130)
    f.MaximizeBox = False
    f.MinimizeBox = False

    lbl = Label()
    lbl.Text = prompt
    lbl.Location = Point(12, 12)
    lbl.Size = Size(436, 40)
    f.Controls.Add(lbl)

    tb = TextBox()
    tb.Text = default
    tb.Location = Point(12, 58)
    tb.Size = Size(436, 24)
    f.Controls.Add(tb)

    ok = Button()
    ok.Text = "OK"
    ok.DialogResult = DialogResult.OK
    ok.Location = Point(292, 92)
    ok.Size = Size(75, 26)
    f.Controls.Add(ok)

    cancel = Button()
    cancel.Text = "Cancelar"
    cancel.DialogResult = DialogResult.Cancel
    cancel.Location = Point(373, 92)
    cancel.Size = Size(75, 26)
    f.Controls.Add(cancel)

    f.AcceptButton = ok
    f.CancelButton = cancel
    if f.ShowDialog() == DialogResult.OK:
        return tb.Text.strip()
    return None


def _select_one(items, title="Selecione"):
    items = list(items)
    if not items:
        return None
    f = Form()
    f.Text = title
    f.StartPosition = FormStartPosition.CenterScreen
    f.ClientSize = Size(460, 360)
    f.MinimizeBox = False

    lb = ListBox()
    lb.Location = Point(12, 12)
    lb.Size = Size(436, 300)
    lb.SelectionMode = SelectionMode.One
    for it in items:
        lb.Items.Add(it)
    lb.SelectedIndex = 0
    f.Controls.Add(lb)

    ok = Button()
    ok.Text = "Selecionar"
    ok.DialogResult = DialogResult.OK
    ok.Location = Point(292, 322)
    ok.Size = Size(75, 26)
    f.Controls.Add(ok)

    cancel = Button()
    cancel.Text = "Cancelar"
    cancel.DialogResult = DialogResult.Cancel
    cancel.Location = Point(373, 322)
    cancel.Size = Size(75, 26)
    f.Controls.Add(cancel)

    f.AcceptButton = ok
    f.CancelButton = cancel
    if f.ShowDialog() == DialogResult.OK and lb.SelectedItem is not None:
        return str(lb.SelectedItem)
    return None


def _select_many(labels, preselect, title="Selecione"):
    """labels: list[str]; preselect: list[bool]. Retorna a lista de índices."""
    f = Form()
    f.Text = title
    f.StartPosition = FormStartPosition.CenterScreen
    f.ClientSize = Size(820, 560)

    clb = CheckedListBox()
    clb.Location = Point(12, 12)
    clb.Size = Size(796, 480)
    clb.CheckOnClick = True
    clb.HorizontalScrollbar = True
    clb.Anchor = (AnchorStyles.Top | AnchorStyles.Bottom |
                  AnchorStyles.Left | AnchorStyles.Right)
    for i, lab in enumerate(labels):
        clb.Items.Add(lab, bool(preselect[i]))
    f.Controls.Add(clb)

    ok = Button()
    ok.Text = "Re-linkar selecionados"
    ok.DialogResult = DialogResult.OK
    ok.Location = Point(620, 502)
    ok.Size = Size(180, 30)
    ok.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
    f.Controls.Add(ok)

    cancel = Button()
    cancel.Text = "Cancelar"
    cancel.DialogResult = DialogResult.Cancel
    cancel.Location = Point(12, 502)
    cancel.Size = Size(100, 30)
    cancel.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
    f.Controls.Add(cancel)

    f.AcceptButton = ok
    f.CancelButton = cancel
    if f.ShowDialog() != DialogResult.OK:
        return None
    return [i for i in range(clb.Items.Count) if clb.GetItemChecked(i)]


def _pick_folder(prompt, initial=None):
    """Seletor de pasta. Retorna o caminho escolhido (str) ou None."""
    dlg = FolderBrowserDialog()
    dlg.Description = prompt
    try:
        dlg.ShowNewFolderButton = False
    except Exception:
        pass
    if initial and os.path.isdir(initial):
        try:
            dlg.SelectedPath = initial
        except Exception:
            pass
    if dlg.ShowDialog() == DialogResult.OK:
        return dlg.SelectedPath
    return None


# ============================================================
# AUXILIARES
# ============================================================
def _link_type_name(link_type):
    try:
        name = Element.Name.GetValue(link_type)
    except Exception:
        try:
            name = link_type.Name
        except Exception:
            name = ""
    # Remove um eventual sufixo " : position N" que alguns links trazem.
    if " : " in name:
        name = name.split(" : ")[0]
    return name.strip()


def _name_candidates(name):
    """Retorna as chaves possíveis do índice para o nome de um link (com/sem .rvt)."""
    low = name.lower()
    keys = [low]
    if not low.endswith(".rvt"):
        keys.append(low + ".rvt")
    else:
        keys.append(low[:-4])
    return keys


def _workset_config():
    for opt_name in ("OpenLastViewed", "OpenAllWorksets"):
        opt = getattr(WorksetConfigurationOption, opt_name, None)
        if opt is not None:
            try:
                return WorksetConfiguration(opt)
            except Exception:
                continue
    return None


def _make_cloud_path(region, project_guid_str, guid_bytes):
    if not project_guid_str:
        raise ValueError("GUID do projeto ausente")
    pg = System.Guid(project_guid_str)
    mg = System.Guid(System.Array[System.Byte](bytearray(guid_bytes)))
    # Prefere a assinatura com região (Revit 2021+); senão, usa a antiga, só
    # para US. Só tenta a assinatura com região quando a região é conhecida.
    if region:
        try:
            return ModelPathUtils.ConvertCloudGUIDsToCloudPath(region, pg, mg)
        except Exception:
            pass
    return ModelPathUtils.ConvertCloudGUIDsToCloudPath(pg, mg)


# ============================================================
# PRINCIPAL
# ============================================================
def main():
    try:
        Application.EnableVisualStyles()
    except Exception:
        pass

    # ========================================================
    # 0. PROTEÇÕES DO DOCUMENTO
    # ========================================================
    if doc is None:
        _alert("Nenhum projeto aberto. Abra o modelo antes de rodar.",
               exit_after=True)
    if doc.IsFamilyDocument:
        _alert("Este comando roda em um PROJETO, não em uma família.",
               exit_after=True)

    cfg = _cfg_load()
    _log("=== ReLink Cloud iniciado | doc='%s' ===" % (doc.Title or "?"))

    # ========================================================
    # 1. MONTA O ÍNDICE LOCAL A PARTIR DO DESKTOP CONNECTOR
    # ========================================================
    try:
        index = dc_local.build_index()
    except Exception as ex:
        _alert("Não consegui ler o cache do Desktop Connector:\n\n%s\n\n"
               "Verifique se o Desktop Connector está instalado, logado e com "
               "o projeto sincronizado." % ex, exit_after=True)

    if not index:
        _alert("Nenhum arquivo .rvt encontrado no cache do Desktop Connector.\n"
               "Sincronize o projeto no Desktop Connector e tente de novo.",
               exit_after=True)

    # ========================================================
    # 2. IDENTIFICA O PROJETO DO HOSPEDEIRO + REGIÃO (e valida a decodificação do GUID)
    # ========================================================
    project_id = None
    region = None
    validation_msg = "Validação do hospedeiro: não foi possível comparar."

    host_visible = None
    try:
        host_cloud = doc.GetCloudModelPath()
        host_visible = ModelPathUtils.ConvertModelPathToUserVisiblePath(
            host_cloud)
    except Exception:
        host_visible = None

    if host_visible:
        host_name = doc.Title or ""
        for cand in dc_local.lookup(index, host_name):
            try:
                gb = dc_local.lineage_urn_to_guid_bytes(cand["lineage_urn"])
                built = _make_cloud_path(cand["region"],
                                         cand["project_guid"], gb)
                built_visible = (
                    ModelPathUtils.ConvertModelPathToUserVisiblePath(built))
            except Exception:
                continue
            if built_visible == host_visible:
                project_id = cand["project_id"]
                region = cand["region"]
                validation_msg = "Validação do hospedeiro: OK (o GUID bate)."
                break
        if project_id is None:
            validation_msg = ("Validação do hospedeiro: não encontrei o hospedeiro no "
                              "cache (não foi possível confirmar o projeto "
                              "automaticamente).")

    # Alternativa: o usuário escolhe o projeto no índice local.
    if project_id is None:
        projects = dc_local.distinct_projects(index)
        # Monta um rótulo legível com um nome de arquivo de exemplo por projeto.
        sample = {}
        for entries in index.values():
            for e in entries:
                sample.setdefault(e["project_id"], e["name"])
        labels = []
        label_to_pid = {}
        for pid, cnt in sorted(projects.items(), key=lambda x: -x[1]):
            lab = "%s  (%d arquivos)  ex: %s" % (pid, cnt,
                                                 sample.get(pid, "?"))
            labels.append(lab)
            label_to_pid[lab] = pid
        if cfg.get("project_id") in projects:
            # Coloca primeiro o projeto memorizado.
            pass
        chosen = _select_one(labels, title="Selecione o projeto ACC do modelo")
        if not chosen:
            raise _ScriptExit()
        project_id = label_to_pid[chosen]
        # Região: pega de qualquer entrada desse projeto.
        for entries in index.values():
            for e in entries:
                if e["project_id"] == project_id:
                    region = e["region"]
                    break
            if region:
                break

    cfg["project_id"] = project_id
    cfg["region"] = region
    _cfg_save(cfg)

    project_guid = dc_local.project_id_to_guid_str(project_id)

    # ========================================================
    # 2b. OPCIONAL: indicar uma pasta específica da nuvem (ex.: Consumed)
    # ========================================================
    # O caminho de nuvem de um link é só região + projeto + GUID do modelo; a
    # PASTA não faz parte dele. Então "indicar a pasta" significa: quando o mesmo
    # nome de arquivo existe em várias pastas (ex.: Shared vs Consumed), pegar o
    # GUID da pasta que o usuário indicar. O usuário escolhe a pasta LOCAL do Desktop
    # Connector; nós a associamos à pasta da nuvem pelos nomes de arquivo em comum.
    folder_urn = None
    folder_label = "Pasta: todas do projeto (item mais recente por nome)."
    dc_root = os.path.join(os.environ.get("USERPROFILE", ""), "DC")
    if _confirm("Quer indicar a pasta de onde puxar os links "
                "(ex.: Consumed em vez de Shared)?\n\n"
                "Sim  = escolher a pasta no Desktop Connector\n"
                "Não = usar o item mais recente do projeto",
                title="ReLink Cloud - pasta"):
        start = cfg.get("last_folder") or (
            dc_root if os.path.isdir(dc_root) else None)
        chosen = _pick_folder(
            "Selecione a pasta (no Desktop Connector) de onde puxar os links",
            initial=start)
        if chosen:
            folders = dc_local.folders_by_urn(index)
            info = dc_local.resolve_local_folder(index, chosen, folders=folders)
            if not info:
                _alert("Não consegui casar essa pasta com o cache do ACC.\n"
                       "Verifique se ela contém arquivos .rvt sincronizados "
                       "pelo Desktop Connector.\n\nVou seguir sem filtro de "
                       "pasta (item mais recente do projeto).",
                       title="ReLink Cloud - pasta")
            else:
                folder_urn = info["folder_urn"]
                project_id = info["project_id"]
                region = info["region"]
                project_guid = dc_local.project_id_to_guid_str(project_id)
                cfg["last_folder"] = chosen
                _cfg_save(cfg)
                folder_label = ("Pasta indicada: %s  (%d/%d arquivos casaram "
                                "no ACC)" % (chosen, info["matched"],
                                             info["total"]))

    # ========================================================
    # 3. RESOLVE CADA LINK -> CAMINHO DE NUVEM (prévia)
    # ========================================================
    link_types = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
    if not link_types:
        _alert("Nenhum link do Revit neste projeto.", exit_after=True)

    rows = []
    for lt in link_types:
        name = _link_type_name(lt)
        try:
            status = str(lt.GetLinkedFileStatus())
        except Exception:
            status = "?"

        matches = dc_local.lookup(index, name, project_id=project_id,
                                  folder_urn=folder_urn)

        note = ""
        cloud_path = None
        if not matches:
            if folder_urn:
                note = "NÃO encontrado na pasta indicada"
            else:
                note = "NÃO encontrado no cache do projeto"
        else:
            # As entradas vêm da mais nova para a mais antiga: pega o item atual (o mais recente).
            entry = matches[0]
            # Usa a região / o GUID do projeto gravados na própria entrada; na
            # falta deles, os valores do hospedeiro. Isto é correto mesmo se um
            # link estiver em outra região/hub que não a do hospedeiro.
            e_region = entry.get("region") or region
            e_pguid = entry.get("project_guid") or project_guid
            try:
                gb = dc_local.lineage_urn_to_guid_bytes(entry["lineage_urn"])
                cloud_path = _make_cloud_path(e_region, e_pguid, gb)
                if len(matches) > 1:
                    note = ("Pronto (%d candidatos, usando o mais recente)"
                            % len(matches))
                else:
                    note = "Pronto para re-linkar"
            except Exception as ex:
                note = "ERRO ao resolver o GUID: %s" % ex

        rows.append({
            "link_type": lt,
            "name": name,
            "status": status,
            "note": note,
            "cloud_path": cloud_path,
            "ready": cloud_path is not None,
        })

    # ========================================================
    # 7. PRÉVIA + CONFIRMAÇÃO
    # ========================================================
    ready_rows = [r for r in rows if r["ready"]]

    _alert("{0}\n{1}\n\nLinks prontos para re-linkar: {2} de {3}.\n\n"
           "Na próxima janela, marque os que deseja aplicar.".format(
               validation_msg, folder_label, len(ready_rows), len(rows)),
           title="ReLink Cloud - prévia")

    labels = []
    for r in rows:
        tag = "[OK]" if r["ready"] else "[--]"
        labels.append("{0} {1}  |  {2}  |  {3}".format(
            tag, r["name"], r["status"], r["note"]))
    preselect = [r["ready"] for r in rows]

    picked = _select_many(
        labels, preselect,
        title="ReLink Cloud - marque os links para re-linkar")
    if picked is None:
        raise _ScriptExit()

    to_apply = [rows[i] for i in picked if rows[i]["ready"]]
    if not to_apply:
        _alert("Nenhum dos selecionados está pronto para re-linkar.",
               exit_after=True)

    if not _confirm(
            "Vai re-linkar %d link(s) na NUVEM.\n\n"
            "Isso altera o modelo aberto (mas não sincroniza).\n"
            "Recomendado testar em 1 modelo antes dos 60.\n\nContinuar?"
            % len(to_apply)):
        raise _ScriptExit()

    # ========================================================
    # 8. APLICA (LoadFrom precisa rodar FORA de uma transação)
    # ========================================================
    wc = _workset_config()
    _log("Aplicando %d link(s)." % len(to_apply))
    results = []
    for r in to_apply:
        ok = False
        result_text = ""
        try:
            path = r["cloud_path"]
            if path is None:
                raise ValueError("caminho de nuvem ausente")
            # LoadFrom(path, wc) é o preferido; senão, usa a sobrecarga sem
            # WorksetConfiguration, caso não tenha sido possível montar uma.
            if wc is not None:
                res = r["link_type"].LoadFrom(path, wc)
            else:
                res = r["link_type"].LoadFrom(path)
            load_result = res.LoadResult if res is not None else None
            result_text = str(load_result)
            try:
                ok = (load_result == LinkLoadResultType.LinkLoaded)
            except Exception:
                ok = (result_text == "LinkLoaded")
        except Exception as ex:
            result_text = "ERRO: %s" % ex
        _log("  [%s] %s -> %s" % ("OK" if ok else "ERRO", r["name"],
                                  result_text))
        results.append({"name": r["name"], "ok": ok, "result": result_text})

    # ========================================================
    # 9. RELATÓRIO
    # ========================================================
    ok_count = sum(1 for x in results if x["ok"])
    lines = []
    for x in results:
        flag = "OK  " if x["ok"] else "ERRO"
        lines.append("[%s] %s  ->  %s" % (flag, x["name"], x["result"]))

    _log("Concluído: %d/%d OK." % (ok_count, len(results)))

    td = TaskDialog("ReLink Cloud - relatório")
    td.MainInstruction = "Re-linkados: %d / %d" % (ok_count, len(results))
    td.MainContent = "%s\n\nLog: %s" % (validation_msg, _LOG_PATH)
    td.ExpandedContent = "\n".join(lines)
    td.Show()


try:
    main()
except _ScriptExit:
    pass
except Exception:
    tb = traceback.format_exc()
    _log("ERRO NÃO TRATADO:\n" + tb)
    try:
        td = TaskDialog("ReLink Cloud - erro")
        td.MainInstruction = "Ocorreu um erro inesperado."
        td.MainContent = ("O processo foi interrompido. Links já aplicados "
                          "antes do erro permanecem aplicados.\n\nLog: %s"
                          % _LOG_PATH)
        td.ExpandedContent = tb
        td.Show()
    except Exception:
        try:
            MessageBox.Show(tb, "ReLink Cloud - erro")
        except Exception:
            pass
