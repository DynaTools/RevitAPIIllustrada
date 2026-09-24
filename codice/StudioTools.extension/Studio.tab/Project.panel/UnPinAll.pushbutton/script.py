# -*- coding: utf-8 -*-
"""
Unpins all pinned elements in the project.
Excludes: linked DWGs, RVT links, generic models, levels and grids.
At the end shows how many elements were unpinned.
The operation is undoable with Ctrl+Z (single undo group).
"""

__title__ = "Unpin\nAll\nElements"
__author__ = "Paulo Giavoni"
__doc__ = ("Unpins all elements in the project, excluding DWGs, RVT links, "
           "generic models, levels and grids. Undoable with Ctrl+Z.")

from pyrevit import revit, DB, forms, script

output = script.get_output()
doc = revit.doc


def _id_int(eid):
    """Numeric value of an ElementId on any Revit version.

    ``ElementId.IntegerValue`` was removed in Revit 2026 and ``Value``
    only exists from Revit 2024 on, so both spellings must be tried.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

# ─────────────────────────────────────────────
# Type classes to exclude
# ─────────────────────────────────────────────
EXCLUDED_TYPES = (
    DB.ImportInstance,     # imported / linked DWG / DXF / IFC
    DB.RevitLinkInstance,  # linked Revit models (RVT)
    DB.RevitLinkType,      # Revit link type
)

GENERIC_MODEL_CATEGORY  = DB.BuiltInCategory.OST_GenericModel
RVT_LINKS_CATEGORY_NAME = "RVT Links"

# Additional BuiltInCategories to exclude
EXCLUDED_BUILTIN_CATEGORIES = (
    DB.BuiltInCategory.OST_Grids,   # Grids
    DB.BuiltInCategory.OST_Levels,  # Levels
)


def is_excluded(element):
    """Returns True if the element must be excluded from unpinning."""
    if isinstance(element, EXCLUDED_TYPES):
        return True

    cat = element.Category
    if cat is None:
        return False

    try:
        bic = cat.BuiltInCategory
        if bic == GENERIC_MODEL_CATEGORY:
            return True
        if bic == DB.BuiltInCategory.OST_RvtLinks:
            return True
        if bic in EXCLUDED_BUILTIN_CATEGORIES:
            return True
    except Exception:
        try:
            if cat.Name == RVT_LINKS_CATEGORY_NAME:
                return True
        except Exception:
            pass

    return False


def get_element_info(el):
    """Returns a dict with descriptive info about the element."""
    try:
        el_id = _id_int(el.Id)
    except Exception:
        el_id = "?"

    try:
        category = el.Category.Name if el.Category else "-"
    except Exception:
        category = "-"

    try:
        name = el.Name if el.Name else "-"
    except Exception:
        name = "-"

    try:
        type_el = doc.GetElement(el.GetTypeId())
        type_name = type_el.Name if (type_el and type_el.Name) else "-"
    except Exception:
        type_name = "-"

    return {"id": el_id, "category": category, "name": name, "type": type_name}


def unpin_all_pinned_elements():
    """Collects and unpins all eligible pinned elements."""

    # ── Collect ───────────────────────────────
    collector = (DB.FilteredElementCollector(doc)
                   .WhereElementIsNotElementType()
                   .ToElements())

    pinned_elements = []
    for el in collector:
        try:
            if not el.Pinned:
                continue
            if is_excluded(el):
                continue
            pinned_elements.append(el)
        except Exception:
            continue

    if not pinned_elements:
        forms.alert(
            "No pinned elements found in the project\n"
            "(or all of them fall in the excluded categories).",
            title="Unpin All",
            warn_icon=False
        )
        return

    # ── User confirmation ─────────────────────
    count = len(pinned_elements)
    confirm = forms.alert(
        "Found {} pinned elements to unpin.\n\n"
        "Excluded categories:\n"
        "  * Imported / linked DWG / DXF\n"
        "  * RVT links\n"
        "  * Generic models\n"
        "  * Levels\n"
        "  * Grids\n\n"
        "The operation will be undoable with Ctrl+Z.\n\n"
        "Proceed?".format(count),
        title="Unpin All",
        yes=True,
        no=True,
        warn_icon=True
    )

    if not confirm:
        output.print_md("**Operation cancelled by user.**")
        return

    # ── Single transaction = single Ctrl+Z step ──
    unlocked    = 0
    errors      = 0
    unlocked_log = []

    t = DB.Transaction(doc, "Unpin elements")
    t.Start()

    try:
        for el in pinned_elements:
            try:
                info = get_element_info(el)
                el.Pinned = False
                unlocked += 1
                unlocked_log.append(info)
            except Exception as ex:
                errors += 1
                output.print_md(
                    "Could not unpin ID `{}`: {}".format(
                        _id_int(el.Id), str(ex)
                    )
                )

        t.Commit()

    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert(
            "Critical error during the transaction.\n"
            "All changes have been rolled back.\n\n"
            "Detail: {}".format(str(ex)),
            title="Unpin All",
            warn_icon=True
        )
        return

    # ── Report ────────────────────────────────
    output.print_md("---")
    output.print_md("## Operation completed")
    output.print_md("")
    output.print_md("| Result | Count |")
    output.print_md("|--------|-------|")
    output.print_md("| Elements unpinned | **{}** |".format(unlocked))
    if errors > 0:
        output.print_md("| Errors | **{}** |".format(errors))
    output.print_md("")
    output.print_md("> Press **Ctrl+Z** in Revit to undo and re-pin everything.")
    output.print_md("")

    if unlocked_log:
        output.print_md("---")
        output.print_md("## Unpinned elements")
        output.print_md("")
        output.print_md("| ID | Category | Name / Family | Type |")
        output.print_md("|----|----------|---------------|------|")
        for entry in unlocked_log:
            output.print_md("| {} | {} | {} | {} |".format(
                entry["id"],
                entry["category"],
                entry["name"],
                entry["type"]
            ))
        output.print_md("")

    # ── Summary alert ─────────────────────────
    if errors == 0:
        forms.alert(
            "Operation completed!\n\n"
            "Elements unpinned: {}\n\n"
            "Use Ctrl+Z to undo.".format(unlocked),
            title="Unpin All",
            warn_icon=False
        )
    else:
        forms.alert(
            "Operation completed with some errors.\n\n"
            "Elements unpinned: {}\n"
            "Errors: {}\n\n"
            "Use Ctrl+Z to undo.\n"
            "Check the output window for details.".format(unlocked, errors),
            title="Unpin All",
            warn_icon=True
        )


unpin_all_pinned_elements()
