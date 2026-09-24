# -*- coding: utf-8 -*-
"""Shared logic for the Rec Sessione teaching recorder.

Consumers:
- RecSessione.smartbutton toggles the recording state (pyRevit env vars);
- hooks/doc-changed.py records one step per committed transaction;
- hooks/dialog-showing.py records dialog windows.

Revit/pyRevit imports are lazy so this module also works in plain
CPython: `generate_readme()` can be run offline to regenerate the guide
of any old session after improving lib/spiegazioni.py, e.g.:

    python -c "import sys; sys.path.append(r'<ext>\\lib');
               import recsessione; recsessione.generate_readme(r'<dir>')"

Session folder contents:
  steps.jsonl    one JSON record per step (append/merge)
  sessione.json  session metadata
  NNN_<name>.png screenshot per step
  README.md      structured guide generated on stop (or offline)
"""

import io
import json
import os
import os.path as op
import re
import time

# --- configuration --------------------------------------------------

# Where session folders are created
BASE_DIR = op.join(op.expanduser("~"), "Documents", "RecSessioni")

# Only these commands merge when repeated back-to-back (micro-gestures
# like locking four constraints in a row); every other command gets one
# step — and one screenshot — per transaction, even if repeated fast
MERGE_COMMANDS = set([
    u"Toggle Lock",
    u"Toggle EQ",
    u"Drag",
    u"Drag refplane model end",
])

# Window for merging MERGE_COMMANDS repetitions
DEBOUNCE_SECONDS = 8

# Delay before the screenshot so the view has time to repaint
CAPTURE_DELAY_MS = 600

# Delay before shooting a dialog window (it must render first)
DIALOG_CAPTURE_DELAY_MS = 1200

# Safety cap on elements inspected per event
MAX_ELEMENTS_PER_STEP = 50

# Transaction names to skip entirely (localized, as shown in the Revit UI)
IGNORED_TRANSACTIONS = set([
    # u"Sincronizza con il file centrale",
])

# Dialog ids to skip (raw id is logged in steps.jsonl as `dialog_id`)
IGNORED_DIALOGS = set([
    "TaskDialog_Missing_Third_Party_Updaters",
    "TaskDialog_Missing_Third_Party_Updater",
    "Dialog_Revit_DocWarnDialog",
])

ENV_ACTIVE = "RECSESSIONE_ACTIVE"
ENV_DIR = "RECSESSIONE_DIR"

STEPS_FILE = "steps.jsonl"
META_FILE = "sessione.json"
README_FILE = "README.md"
ERROR_FILE = "errori.log"

try:
    _text_type = unicode
except NameError:
    _text_type = str

try:
    import spiegazioni
    COMANDI = spiegazioni.COMANDI
    FINESTRE = spiegazioni.FINESTRE
except Exception:
    COMANDI = {}
    FINESTRE = {}


# --- session state ---------------------------------------------------

def _envvars():
    from pyrevit.coreutils import envvars
    return envvars


def is_active():
    return bool(_envvars().get_pyrevit_env_var(ENV_ACTIVE))


def get_session_dir():
    return _envvars().get_pyrevit_env_var(ENV_DIR)


def start_session(nome, documento=u"", revit=u""):
    stamp = time.strftime("%Y-%m-%d")
    slug = sanitize(nome)
    session_dir = op.join(BASE_DIR, u"{}_{}".format(stamp, slug))
    counter = 2
    while op.isdir(session_dir):
        session_dir = op.join(BASE_DIR, u"{}_{}_{}".format(stamp, slug, counter))
        counter += 1
    os.makedirs(session_dir)
    _save_meta(session_dir, {
        "nome": nome,
        "documento": documento,
        "revit": revit,
        "inizio": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _envvars().set_pyrevit_env_var(ENV_DIR, session_dir)
    _envvars().set_pyrevit_env_var(ENV_ACTIVE, True)
    return session_dir


def stop_session():
    _envvars().set_pyrevit_env_var(ENV_ACTIVE, False)
    session_dir = _envvars().get_pyrevit_env_var(ENV_DIR)
    if session_dir and op.isdir(session_dir):
        meta = _load_meta(session_dir)
        meta["fine"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_meta(session_dir, meta)
    return session_dir


# --- step log (steps.jsonl) ------------------------------------------

def load_steps(session_dir):
    path = op.join(session_dir, STEPS_FILE)
    steps = []
    if op.isfile(path):
        with io.open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    steps.append(json.loads(line))
    return steps


def save_steps(session_dir, steps):
    path = op.join(session_dir, STEPS_FILE)
    with io.open(path, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(_dumps(step) + u"\n")


def record_step(session_dir, record):
    """Append the step, or merge it into the last one (debounce).

    Returns the full path of the screenshot to (re)capture — merged steps
    reuse their image so the file always shows the latest state.
    """
    steps = load_steps(session_dir)
    if steps:
        last = steps[-1]
        same_name = last.get("nome") == record.get("nome")
        recent = record.get("t", 0) - last.get("t", 0) <= DEBOUNCE_SECONDS
        mergeable = record.get("nome", u"").replace(u"&", u"") in MERGE_COMMANDS
        if same_name and recent and mergeable and not last.get("annotazioni"):
            last["ripetizioni"] = last.get("ripetizioni", 1) + 1
            last["t"] = record.get("t")
            last["ora"] = record.get("ora")
            for key in ("aggiunti", "modificati"):
                merged = dict(last.get(key) or {})
                for cat, cnt in (record.get(key) or {}).items():
                    merged[cat] = merged.get(cat, 0) + cnt
                last[key] = merged
            last["eliminati"] = ((last.get("eliminati") or 0)
                                 + (record.get("eliminati") or 0))
            save_steps(session_dir, steps)
            return op.join(session_dir, last["img"])
    record["n"] = len(steps) + 1
    record["img"] = u"{:03d}_{}.png".format(
        record["n"], sanitize(record.get("nome", u"")))
    steps.append(record)
    save_steps(session_dir, steps)
    return op.join(session_dir, record["img"])


def annotate_last(session_dir, nota):
    """Attach a note (undo/redo) to the last recorded step."""
    steps = load_steps(session_dir)
    if not steps:
        return False
    steps[-1].setdefault("annotazioni", []).append(nota)
    save_steps(session_dir, steps)
    return True


# --- screenshot (Revit-side only) -------------------------------------

def capture_screen_async(png_path, delay_ms=None):
    """Shoot the monitor hosting the Revit window after a short delay.

    The window bounds are resolved on the caller thread; the GDI capture
    runs on a background thread — it does not touch the Revit API, so it
    is safe outside the API context.
    """
    import clr
    clr.AddReference("System.Drawing")
    clr.AddReference("System.Windows.Forms")
    from System.Drawing import Bitmap, Graphics
    from System.Drawing.Imaging import ImageFormat
    from System.Threading import Thread, ThreadStart
    from System.Windows.Forms import Screen

    if delay_ms is None:
        delay_ms = CAPTURE_DELAY_MS
    # WorkingArea instead of Bounds: excludes the Windows taskbar
    bounds = Screen.FromHandle(_revit_window_handle()).WorkingArea

    def _shoot():
        try:
            Thread.Sleep(delay_ms)
            bmp = Bitmap(bounds.Width, bounds.Height)
            g = Graphics.FromImage(bmp)
            try:
                g.CopyFromScreen(bounds.X, bounds.Y, 0, 0, bmp.Size)
                bmp.Save(png_path, ImageFormat.Png)
            finally:
                g.Dispose()
                bmp.Dispose()
        except Exception as err:
            log_error(op.dirname(png_path), u"screenshot: {}".format(err))

    worker = Thread(ThreadStart(_shoot))
    worker.IsBackground = True
    worker.Start()


def _revit_window_handle():
    try:
        from pyrevit import HOST_APP
        handle = HOST_APP.uiapp.MainWindowHandle
        if handle:
            return handle
    except Exception:
        pass
    from System.Diagnostics import Process
    return Process.GetCurrentProcess().MainWindowHandle


# --- guide generation --------------------------------------------------

def generate_readme(session_dir):
    meta = _load_meta(session_dir)
    steps = load_steps(session_dir)
    unknown = []

    lines = [u"# Guida: {}".format(
        meta.get("nome") or op.basename(session_dir)), u""]

    info = []
    if meta.get("inizio"):
        periodo = meta["inizio"]
        if meta.get("fine"):
            periodo += u" → {}".format(meta["fine"].split(" ")[-1])
        info.append(u"**Sessione**: {}".format(periodo))
    if meta.get("documento"):
        info.append(u"**Documento**: {}".format(meta["documento"]))
    if meta.get("revit"):
        info.append(u"**Revit**: {}".format(meta["revit"]))
    finestre = len([s for s in steps if s.get("tipo") == "finestra"])
    riassunto = u"{} passi".format(len(steps))
    if finestre:
        riassunto += u" (di cui {} finestre)".format(finestre)
    info.append(u"**Registrati**: {}".format(riassunto))
    lines.append(u" · ".join(info))
    lines.append(u"")

    # index table
    lines.append(u"## Indice")
    lines.append(u"")
    lines.append(u"| # | Ora | Passo |")
    lines.append(u"|---|-----|-------|")
    for step in steps:
        titolo, _ = _spiegazione(step, unknown=None)
        rip = step.get("ripetizioni", 1)
        if rip > 1:
            titolo += u" (×{})".format(rip)
        lines.append(u"| {} | {} | {} |".format(
            step.get("n"), step.get("ora", u""), titolo))
    lines.append(u"")

    # steps
    lines.append(u"## Passi")
    lines.append(u"")
    for step in steps:
        lines.extend(_step_lines(step, unknown))

    # footer
    lines.append(u"---")
    if unknown:
        lines.append(u"")
        lines.append(u"### Comandi senza spiegazione")
        lines.append(u"")
        lines.append(
            u"Aggiungili a `lib/spiegazioni.py` e rigenera la guida:")
        for name in sorted(set(unknown)):
            lines.append(u"- `{}`".format(name))
        lines.append(u"")
    lines.append(u"*Generata automaticamente da Rec Sessione (pyRevit).*")

    path = op.join(session_dir, README_FILE)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"\n".join(lines))
    return path


def _spiegazione(step, unknown=None):
    """Return (title, didactic text) for a step; track unknown commands."""
    if step.get("tipo") == "finestra":
        voce = FINESTRE.get(step.get("dialog_id"))
        if voce:
            return voce["titolo"], voce.get("testo", u"")
        if unknown is not None and step.get("dialog_id"):
            unknown.append(step["dialog_id"])
        return step.get("nome", u"Finestra"), u""
    nome = step.get("nome", u"")
    chiave = nome.replace(u"&", u"").strip()
    voce = COMANDI.get(chiave) or COMANDI.get(nome)
    if voce:
        return voce["titolo"], voce.get("testo", u"")
    if unknown is not None and nome:
        unknown.append(chiave)
    return nome, u""


def _step_lines(step, unknown):
    titolo, testo = _spiegazione(step, unknown)
    rip = step.get("ripetizioni", 1)
    header = u"### Passo {} — {}".format(step.get("n"), titolo)
    if rip > 1:
        header += u" (×{})".format(rip)
    lines = [header]

    sub = [step.get("ora") or u""]
    if step.get("vista"):
        sub.append(u"vista: {}".format(step["vista"]))
    raw = step.get("dialog_id") or step.get("nome")
    if raw and raw != titolo:
        sub.append(u"comando: `{}`".format(raw))
    lines.append(u"*{}*".format(u" — ".join(p for p in sub if p)))
    lines.append(u"")
    lines.append(u"![Passo {}]({})".format(step.get("n"), step.get("img")))
    lines.append(u"")

    if testo:
        lines.append(testo)
        lines.append(u"")
    if step.get("messaggio"):
        lines.append(u"> «{}»".format(step["messaggio"]))
        lines.append(u"")

    fatti = []
    if step.get("aggiunti"):
        fatti.append(u"- Elementi aggiunti: {}".format(
            _fmt_counts(step["aggiunti"])))
    if step.get("modificati"):
        fatti.append(u"- Elementi modificati: {}".format(
            _fmt_counts(step["modificati"])))
    if step.get("eliminati"):
        fatti.append(u"- Elementi eliminati: {}".format(step["eliminati"]))
    if fatti:
        lines.extend(fatti)
        lines.append(u"")
    for nota in step.get("annotazioni") or []:
        lines.append(u"> ✎ {}".format(nota))
        lines.append(u"")
    return lines


def _fmt_counts(counts):
    return u", ".join(
        u"{} ×{}".format(cat, cnt) for cat, cnt in sorted(counts.items()))


# --- helpers ----------------------------------------------------------

def sanitize(text, maxlen=40):
    text = re.sub(r"[^\w\-]+", u"-", u"{}".format(text), flags=re.UNICODE)
    text = re.sub(r"-{2,}", u"-", text)
    text = text.strip(u"-_")
    return text[:maxlen] or u"passo"


def log_error(session_dir, message):
    try:
        path = op.join(session_dir, ERROR_FILE)
        with io.open(path, "a", encoding="utf-8") as f:
            f.write(u"[{}]\n{}\n".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def _dumps(obj):
    text = json.dumps(obj, ensure_ascii=False)
    if not isinstance(text, _text_type):
        text = text.decode("utf-8")
    return text


def _meta_path(session_dir):
    return op.join(session_dir, META_FILE)


def _load_meta(session_dir):
    try:
        with io.open(_meta_path(session_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_meta(session_dir, meta):
    with io.open(_meta_path(session_dir), "w", encoding="utf-8") as f:
        f.write(_dumps(meta))
