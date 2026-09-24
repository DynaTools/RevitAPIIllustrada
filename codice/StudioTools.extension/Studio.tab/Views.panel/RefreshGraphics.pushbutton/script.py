# -*- coding: utf-8 -*-
"""Refresh / regenerate the active view graphics.

Fixes the common glitch where a 3D (or other) view shows nothing, yet the
elements are still there (you can still select them by clicking or box-select).
That is a graphics / display-cache desync, NOT lost geometry.

The tool applies, on the ACTIVE view, every API "kick" that forces Revit to
rebuild the display:

  * clears any stuck Temporary Hide/Isolate, Reveal Hidden or temp properties
  * toggles Detail Level and Visual Style, then reverts them
  * regenerates the document
  * refreshes the active view and bounces it (switch away and back)
  * collects managed memory (.NET GC)

Nothing is deleted and view settings are restored. Undoable with Ctrl+Z.
"""
from pyrevit import revit, DB, forms, script
import System

__title__ = "Refresh\nGraphics"
__author__ = "Paulo Giavoni"

uidoc = revit.uidoc
doc = revit.doc
output = script.get_output()

view = doc.ActiveView if doc else None
if view is None:
    forms.alert("No active view.", title="Refresh Graphics", warn_icon=True)
    script.exit()

done = []

# --------------------------------------------------------------------------
# 1. transaction: clear stuck temp view modes + toggle graphics + regenerate
# --------------------------------------------------------------------------
TEMP_MODES = [
    ("Temporary Hide/Isolate", DB.TemporaryViewMode.TemporaryHideIsolate),
    ("Reveal Hidden Elements", DB.TemporaryViewMode.RevealHiddenElements),
    ("Temporary View Properties", DB.TemporaryViewMode.TemporaryViewProperties),
]

t = DB.Transaction(doc, "Refresh view graphics")
t.Start()
try:
    for label, mode in TEMP_MODES:
        try:
            if view.IsInTemporaryViewMode(mode):
                view.DisableTemporaryViewMode(mode)
                done.append("Cleared: " + label)
        except Exception:
            pass

    # toggle Detail Level and revert (forces a display rebuild)
    try:
        original = view.DetailLevel
        alt = (DB.ViewDetailLevel.Fine
               if original != DB.ViewDetailLevel.Fine
               else DB.ViewDetailLevel.Coarse)
        view.DetailLevel = alt
        doc.Regenerate()
        view.DetailLevel = original
        done.append("Toggled Detail Level")
    except Exception:
        pass

    # toggle Visual Style and revert
    try:
        original_ds = view.DisplayStyle
        alt_ds = (DB.DisplayStyle.Wireframe
                  if original_ds != DB.DisplayStyle.Wireframe
                  else DB.DisplayStyle.Shading)
        view.DisplayStyle = alt_ds
        doc.Regenerate()
        view.DisplayStyle = original_ds
        done.append("Toggled Visual Style")
    except Exception:
        pass

    doc.Regenerate()
    t.Commit()
    done.append("Document regenerated")
except Exception as ex:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    output.print_md("Transaction step failed: `{}`".format(ex))

# --------------------------------------------------------------------------
# 2. outside transaction: refresh + bounce the active view
# --------------------------------------------------------------------------
try:
    uidoc.RefreshActiveView()
    done.append("Active view refreshed")
except Exception:
    pass

try:
    other_id = None
    for uv in uidoc.GetOpenUIViews():
        if uv.ViewId != view.Id:
            other_id = uv.ViewId
            break
    if other_id is not None:
        other_view = doc.GetElement(other_id)
        uidoc.ActiveView = other_view
        uidoc.ActiveView = view
        uidoc.RefreshActiveView()
        done.append("View reactivated (full redraw)")
    else:
        done.append("Only one view open - could not bounce")
except Exception:
    pass

# --------------------------------------------------------------------------
# 3. free managed memory
# --------------------------------------------------------------------------
try:
    System.GC.Collect()
    System.GC.WaitForPendingFinalizers()
    done.append("Managed memory collected")
except Exception:
    pass

# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
output.print_md("### Refresh Graphics - {}".format(view.Name))
for d in done:
    output.print_md("- " + d)

forms.alert(
    "Graphics refresh completed on view:\n{}\n\n"
    "If it is STILL blank, try in this order:\n"
    "  1. Zoom to Fit (type ZF)\n"
    "  2. change Visual Style manually (Wireframe then back)\n"
    "  3. toggle Thin Lines (type TL)\n"
    "  4. check for a collapsed Section Box\n"
    "  5. close the model and choose Audit when reopening.".format(view.Name),
    title="Refresh Graphics", warn_icon=False)
