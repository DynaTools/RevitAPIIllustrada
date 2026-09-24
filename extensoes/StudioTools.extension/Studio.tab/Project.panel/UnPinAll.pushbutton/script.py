# -*- coding: utf-8 -*-
"""
Desafixa todos os elementos fixados do projeto.
Deixa de fora: DWGs vinculados, links RVT, modelos genéricos, níveis e eixos.
No fim mostra quantos elementos foram desafixados.
A operação pode ser desfeita com Ctrl+Z (um único grupo de desfazer).
"""

__title__ = "Unpin\nAll\nElements"
__author__ = "Paulo Giavoni"
__doc__ = ("Desafixa todos os elementos do projeto, exceto DWGs, links RVT, "
           "modelos genéricos, níveis e eixos. Pode ser desfeito com Ctrl+Z.")

from pyrevit import revit, DB, forms, script

output = script.get_output()
doc = revit.doc


def _id_int(eid):
    """Valor numérico de um ElementId em qualquer versão do Revit.

    ``ElementId.IntegerValue`` foi removido no Revit 2026 e ``Value``
    só existe a partir do Revit 2024, então é preciso tentar as duas grafias.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue

# ─────────────────────────────────────────────
# Classes que ficam de fora
# ─────────────────────────────────────────────
EXCLUDED_TYPES = (
    DB.ImportInstance,     # DWG / DXF / IFC importado / vinculado
    DB.RevitLinkInstance,  # modelos Revit vinculados (RVT)
    DB.RevitLinkType,      # tipo de link do Revit
)

GENERIC_MODEL_CATEGORY  = DB.BuiltInCategory.OST_GenericModel
RVT_LINKS_CATEGORY_NAME = "RVT Links"

# BuiltInCategories adicionais que ficam de fora
EXCLUDED_BUILTIN_CATEGORIES = (
    DB.BuiltInCategory.OST_Grids,   # Eixos
    DB.BuiltInCategory.OST_Levels,  # Níveis
)


def is_excluded(element):
    """Devolve True se o elemento não deve ser desafixado."""
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
    """Devolve um dict com informações descritivas do elemento."""
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
    """Coleta e desafixa todos os elementos fixados elegíveis."""

    # ── Coleta ────────────────────────────────
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
            "Nenhum elemento fixado encontrado no projeto\n"
            "(ou todos estão nas categorias que ficam de fora).",
            title="Desafixar tudo",
            warn_icon=False
        )
        return

    # ── Confirmação do usuário ────────────────
    count = len(pinned_elements)
    confirm = forms.alert(
        "Encontrados {} elementos fixados para desafixar.\n\n"
        "Categorias que ficam de fora:\n"
        "  * DWG / DXF importado / vinculado\n"
        "  * Links RVT\n"
        "  * Modelos genéricos\n"
        "  * Níveis\n"
        "  * Eixos\n\n"
        "A operação poderá ser desfeita com Ctrl+Z.\n\n"
        "Continuar?".format(count),
        title="Desafixar tudo",
        yes=True,
        no=True,
        warn_icon=True
    )

    if not confirm:
        output.print_md("**Operação cancelada pelo usuário.**")
        return

    # ── Uma transação = um único passo de Ctrl+Z ──
    unlocked    = 0
    errors      = 0
    unlocked_log = []

    t = DB.Transaction(doc, "Desafixar elementos")
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
                    "Não foi possível desafixar o ID `{}`: {}".format(
                        _id_int(el.Id), str(ex)
                    )
                )

        t.Commit()

    except Exception as ex:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        forms.alert(
            "Erro crítico durante a transação.\n"
            "Todas as alterações foram revertidas.\n\n"
            "Detalhe: {}".format(str(ex)),
            title="Desafixar tudo",
            warn_icon=True
        )
        return

    # ── Relatório ─────────────────────────────
    output.print_md("---")
    output.print_md("## Operação concluída")
    output.print_md("")
    output.print_md("| Resultado | Quantidade |")
    output.print_md("|-----------|------------|")
    output.print_md("| Elementos desafixados | **{}** |".format(unlocked))
    if errors > 0:
        output.print_md("| Erros | **{}** |".format(errors))
    output.print_md("")
    output.print_md("> Pressione **Ctrl+Z** no Revit para desfazer e fixar tudo de novo.")
    output.print_md("")

    if unlocked_log:
        output.print_md("---")
        output.print_md("## Elementos desafixados")
        output.print_md("")
        output.print_md("| ID | Categoria | Nome / Família | Tipo |")
        output.print_md("|----|-----------|----------------|------|")
        for entry in unlocked_log:
            output.print_md("| {} | {} | {} | {} |".format(
                entry["id"],
                entry["category"],
                entry["name"],
                entry["type"]
            ))
        output.print_md("")

    # ── Alerta de resumo ──────────────────────
    if errors == 0:
        forms.alert(
            "Operação concluída!\n\n"
            "Elementos desafixados: {}\n\n"
            "Use Ctrl+Z para desfazer.".format(unlocked),
            title="Desafixar tudo",
            warn_icon=False
        )
    else:
        forms.alert(
            "Operação concluída com alguns erros.\n\n"
            "Elementos desafixados: {}\n"
            "Erros: {}\n\n"
            "Use Ctrl+Z para desfazer.\n"
            "Veja os detalhes na janela de saída.".format(unlocked, errors),
            title="Desafixar tudo",
            warn_icon=True
        )


unpin_all_pinned_elements()
