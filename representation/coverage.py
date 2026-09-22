"""Explicit implementation status, distinct from workbook pattern availability."""
from collections import Counter
from .animation_grammar import TEMPLATES

DEDICATED = {"category_embed", "reveal_inside", "zoom_in_nesting", "tree_expand",
    "pipeline_transform", "morph", "interface_bridge", "token_enter_and_act",
    "control_signal", "write_in", "read_out", "side_by_side", "split_screen", "event_propagation",
    "table_highlight", "push_pop", "abstract_to_concrete", "principle_to_mechanism",
    "purpose_reveal", "factor_to_metric", "resource_flow", "dependency_gate",
    "capability_unlock", "cause_chain", "problem_solution_bridge"}


def implementation_status(pattern_id):
    template = TEMPLATES.get(pattern_id)
    if template is None or template.template_id == "relation_link":
        return "fallback"
    return "dedicated" if template.template_id in DEDICATED else "simplified"


def coverage_report(story, workbook):
    import openpyxl
    with_workbook = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    try:
        rows = with_workbook["Animation_Patterns"].iter_rows(values_only=True)
        headers = next(rows)
        index = next(i for i, name in enumerate(headers) if str(name).split(":")[0] == "pattern_id")
        patterns = {str(row[index]) for row in rows if row[index]}
    finally:
        with_workbook.close()
    selected = Counter(b.pattern_id for s in story.scenes for b in s.beats if b.pattern_id)
    return {"workbook_counts": dict(Counter(implementation_status(p) for p in patterns)),
        "patterns": [{"pattern_id": p, "status": implementation_status(p)} for p in sorted(patterns)],
        "selected": [{"pattern_id": p, "status": implementation_status(p), "beat_count": count}
                     for p, count in selected.items()],
        "note": "dedicated means a specialized renderer branch, not complete workbook semantic coverage"}
