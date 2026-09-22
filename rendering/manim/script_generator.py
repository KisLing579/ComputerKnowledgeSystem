from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from rendering.models import RenderPlan


class ManimScriptGenerator:
    """Generate a Manim scene that executes semantic visual-story beats."""

    def generate(self, plan: RenderPlan, output: str | Path) -> Path:
        return self.generate_payload(asdict(plan), output)

    def generate_payload(self, plan: dict, output: str | Path) -> Path:
        from rendering.subgraph import prepare_subgraph, group_subquestions, add_subquestion_intros
        plan = group_subquestions(plan)
        plan = prepare_subgraph(plan)
        plan = add_subquestion_intros(plan)
        output = Path(output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(plan, ensure_ascii=False)
        code = _SCRIPT_TEMPLATE.replace("__PLAN_JSON__", repr(payload))
        from .structured_nodes import SOURCE as STRUCTURED_SOURCE
        code += "\n" + STRUCTURED_SOURCE
        from .execution_nodes import SOURCE as EXECUTION_SOURCE
        code += "\n" + EXECUTION_SOURCE
        from .memory_nodes import SOURCE as MEMORY_SOURCE
        code += "\n" + MEMORY_SOURCE
        from .memory_system_nodes import SOURCE as MEMORY_SYSTEM_SOURCE
        code += "\n" + MEMORY_SYSTEM_SOURCE
        from .processor_nodes import SOURCE as PROCESSOR_SOURCE
        from .processor_effects import SOURCE as PROCESSOR_EFFECTS
        code += "\n" + PROCESSOR_SOURCE + "\n" + PROCESSOR_EFFECTS
        from .memory_behavior import SOURCE as MEMORY_BEHAVIOR_SOURCE
        code += "\n" + MEMORY_BEHAVIOR_SOURCE
        from .data_structure_effects import SOURCE
        code += "\n" + SOURCE
        from .isa_effects import SOURCE as ISA_SOURCE
        code += "\n" + ISA_SOURCE
        from .causal_effects import SOURCE as CAUSAL_SOURCE
        code += "\n" + CAUSAL_SOURCE
        from .cache_effects import SOURCE as CACHE_SOURCE
        code += "\n" + CACHE_SOURCE
        if plan.get('metadata', {}).get('language') == 'en':
            from resource_planning.localization import localize_script
            from resource_planning.text_engine import DeepseekModel
            code = localize_script(code, DeepseekModel())
        output.write_text(code, encoding="utf-8")
        return output


_SCRIPT_TEMPLATE = r'''from manim import *
import json
import copy

PLAN = json.loads(__PLAN_JSON__)
ENGLISH = PLAN.get("metadata", {}).get("language") == "en"
if ENGLISH:
    import manimpango
    available_fonts = set(manimpango.list_fonts())
    english_font = next((f for f in ("Arial", "Segoe UI", "DejaVu Sans", "Liberation Sans", "Noto Sans")
                         if f in available_fonts), "sans-serif")
    cjk_font = next((f for f in ("Microsoft YaHei", "Noto Sans SC", "Noto Sans CJK SC", "SimHei")
                    if f in available_fonts), "sans-serif")
    # Cover all appended effect captions without changing Manim's global defaults.
    class Text(Text):
        def __init__(self, text, **kwargs):
            kwargs.setdefault("font", cjk_font if any(0x3400 <= ord(c) <= 0x9fff for c in str(text)) else english_font)
            super().__init__(text, **kwargs)


def fitted_text(text, size, width, height, max_lines=2):
    """Wrap English using measured glyph widths, preserving whole words."""
    text = str(text)
    result = Text(text, font_size=size)
    if ENGLISH and result.width > width and max_lines > 1:
        lines = []
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split():
                candidate = (line + " " + word).strip()
                if line and Text(candidate, font_size=size).width > width:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines-1] + [" ".join(lines[max_lines-1:])]
        result = Text("\n".join(lines), font_size=size)
    result.scale(min(1, width / max(result.width, 1e-6), height / max(result.height, 1e-6)))
    return result


def panel_spec(spec, center, factor=0.53, vertical_factor=0.82):
    result = copy.deepcopy(spec)
    for node in result.get("nodes", []):
        node["x"] = center + factor * float(node.get("x", 0))
        node["y"] = vertical_factor * float(node.get("y", 0))
        node["scale"] = factor * float(node.get("scale", 1))
        meta = node.get("metadata", {})
        if "initial_x" in meta:
            meta["initial_x"] = center + factor * float(meta["initial_x"])
        if "initial_y" in meta:
            meta["initial_y"] = vertical_factor * float(meta["initial_y"])
    return result


def prerequisite_panel_spec(spec):
    """Center the prerequisite's local visual in the right teaching panel."""
    result = copy.deepcopy(spec)
    nodes = result.get('nodes', [])
    if nodes:
        cx = (min(float(n.get('x', 0)) for n in nodes) + max(float(n.get('x', 0)) for n in nodes)) / 2
        cy = (min(float(n.get('y', 0)) for n in nodes) + max(float(n.get('y', 0)) for n in nodes)) / 2
        for node in nodes:
            node['x'] = float(node.get('x', 0)) - cx
            node['y'] = float(node.get('y', 0)) - cy
    return panel_spec(result, 3.2)


def label(text, size=24):
    return Text(str(text), font_size=size)


def box_label(name, width=2.8, height=1.2, rounded=True):
    shape = RoundedRectangle(width=width, height=height, corner_radius=0.16) if rounded else Rectangle(width=width, height=height)
    txt = fitted_text(name, 22, width * 0.82, height * 0.7)
    if txt.width > width * 0.82:
        txt.scale_to_fit_width(width * 0.82)
    txt.move_to(shape)
    return VGroup(shape, txt)


def make_node(spec):
    name = spec.get("name", "")
    archetype = spec.get("archetype", "functional_block")
    w = float(spec.get("width", 2.8))
    h = float(spec.get("height", 1.2))

    if archetype in {"instruction_format", "stack_frame", "memory_map", "character_table", "table_mapping"}:
        obj = make_structured_node(spec)
    elif archetype in {"addressing", "control_flow", "datapath_graph"}:
        obj = make_execution_node(spec)
    elif archetype in {"cache_lookup", "cache_address_decode", "cache_set_lookup", "tlb_translation", "page_table_map", "address_translation"}:
        obj = make_memory_node(spec)
    elif archetype in {"cache_write_policy", "replacement_choice", "memory_hierarchy_stack", "virtual_memory_map", "page_fault_flow", "memory_request_timeline"}:
        obj = make_memory_system_node(spec)
    elif archetype in {'timing_state', 'control_fsm', 'control_table', 'microcode_flow', 'pipeline_timeline', 'hazard_dependency', 'branch_predictor', 'issue_bundle', 'dynamic_schedule'}:
        obj = make_processor_node(spec)
    elif archetype in {'cache_map', 'banked_memory', 'locality_trace', 'access_pattern', 'miss_taxonomy', 'protection_boundary', 'process_switch', 'queue_flow'}:
        obj = make_memory_behavior_node(spec)
    elif archetype == "code_block":
        body = RoundedRectangle(width=w, height=h, corner_radius=0.12)
        lines = VGroup(*[Line(LEFT * w * 0.34, RIGHT * w * 0.26).shift(UP * (0.24 - i * 0.22)) for i in range(3)])
        lines.move_to(body.get_center() + DOWN * 0.05)
        title = label(name, 20).move_to(body.get_top() + DOWN * 0.22)
        obj = VGroup(body, lines, title)
    elif archetype == "bit_field":
        body = RoundedRectangle(width=w, height=h, corner_radius=0.08)
        cells = VGroup()
        for i in range(4):
            x = -w * 0.375 + i * w * 0.25
            cells.add(Rectangle(width=w * 0.24, height=h * 0.45).move_to([x, -0.12, 0]))
        title = label(name, 20).move_to(body.get_top() + DOWN * 0.2)
        obj = VGroup(body, cells, title)
    elif archetype == "bit_cell":
        body = Square(side_length=min(w, h))
        obj = VGroup(body, label(name, 24).move_to(body))
    elif archetype == "storage_block":
        body = RoundedRectangle(width=w, height=h, corner_radius=0.12)
        grid = VGroup()
        for x in (-w * 0.25, 0, w * 0.25):
            grid.add(Line(UP * h * 0.2, DOWN * h * 0.2).shift(RIGHT * x))
        for y in (-h * 0.18, h * 0.18):
            grid.add(Line(LEFT * w * 0.38, RIGHT * w * 0.38).shift(UP * y))
        grid.move_to(body.get_center() + DOWN * 0.06)
        title = label(name, 20).move_to(body.get_top() + DOWN * 0.2)
        obj = VGroup(body, grid, title)
    elif archetype == "memory_chip":
        body = RoundedRectangle(width=w, height=h, corner_radius=0.08)
        pins = VGroup()
        for dx in (-w*0.3, -w*0.1, w*0.1, w*0.3):
            pins.add(Line(DOWN*h*0.5, DOWN*h*0.68).shift(RIGHT*dx))
            pins.add(Line(UP*h*0.5, UP*h*0.68).shift(RIGHT*dx))
        obj = VGroup(body, pins, label(name, 21).move_to(body))
    elif archetype == "interface_layer":
        body = RoundedRectangle(width=w, height=h, corner_radius=0.12)
        obj = VGroup(body, label(name, 22).move_to(body))
    elif archetype in {"concept_layer", "category_group", "container"}:
        body = DashedVMobject(RoundedRectangle(width=w, height=h, corner_radius=0.18))
        title = label(name, 22).next_to(body.get_top(), DOWN, buff=0.16)
        obj = VGroup(body, title)
    elif archetype == "interface_hub":
        body = Circle(radius=min(w, h) * 0.34)
        ports = VGroup(*[Line(RIGHT * body.width/2, RIGHT * (body.width/2 + 0.2)).rotate(a, about_point=ORIGIN)
                        for a in (0, PI/2, PI, -PI/2)])
        obj = VGroup(body, ports, label(name, 19).move_to(body))
    elif archetype == "data_token":
        body = RoundedRectangle(width=w, height=h, corner_radius=h*0.35)
        obj = VGroup(body, label(name, 20).move_to(body))
    elif archetype == "hardware_icon":
        body = Square(side_length=min(w, h)*0.85)
        pins = VGroup()
        half = body.width / 2
        for d in (-body.height * 0.3, 0, body.height * 0.3):
            pins.add(Line(LEFT*(half + 0.2), LEFT*half).shift(UP*d))
            pins.add(Line(RIGHT*half, RIGHT*(half + 0.2)).shift(UP*d))
        title = fitted_text(name, 19, body.width * 0.8, body.height * 0.7)
        obj = VGroup(body, pins, title.move_to(body))
    elif archetype == "transformer":
        body = RoundedRectangle(width=w, height=h, corner_radius=0.15)
        arrow = Text("⇢", font_size=26).move_to(body.get_center() + DOWN*0.12)
        title = label(name, 20).move_to(body.get_top() + DOWN*0.22)
        obj = VGroup(body, title, arrow)
    elif archetype == "parallel_flow":
        lanes = VGroup(*[Arrow(LEFT*w*0.38, RIGHT*w*0.38, buff=0).shift(UP*y) for y in (-h*0.25,0,h*0.2)])
        title = label(name, 20).next_to(lanes, UP, buff=0.12)
        obj = VGroup(lanes, title)
    elif archetype == "pipeline":
        stages = VGroup(*[Rectangle(width=w/4.3, height=h*0.5).shift(RIGHT*((i-1.5)*w/4.0)) for i in range(4)])
        title = label(name, 20).next_to(stages, UP, buff=0.12)
        obj = VGroup(stages, title)
    elif archetype == "timeline":
        axis = Arrow(LEFT*w*0.45, RIGHT*w*0.45, buff=0)
        title = label(name, 20).next_to(axis, UP, buff=0.18)
        obj = VGroup(axis, title)
    else:
        obj = box_label(name, width=w, height=h)

    # Fit legacy node titles in both languages, using actual shape dimensions.
    centered_types = {"bit_cell", "memory_chip", "interface_layer", "interface_hub", "data_token"}
    header_types = {"code_block", "bit_field", "storage_block", "concept_layer", "category_group", "container", "transformer"}
    open_types = {"parallel_flow", "pipeline", "timeline"}
    if archetype in centered_types | header_types | open_types:
        for item in obj.submobjects:
            if isinstance(item, Text) and "".join(str(getattr(item, "text", "")).split()) == "".join(str(name).split()):
                if archetype in centered_types:
                    # A central rectangle inside the circle must fit its curved boundary too.
                    ratio = 0.65 if archetype == "interface_hub" else 0.8
                    replacement = fitted_text(name, item.font_size, body.width * ratio, body.height * 0.65)
                    replacement.move_to(body.get_center())
                else:
                    replacement = fitted_text(name, item.font_size, w * 0.82, h * 0.22, max_lines=1)
                    replacement.move_to([0, h * 0.34, 0])
                item.become(replacement)

    if spec.get('metadata', {}).get('interface_boundary'):
        # Keep the workbook archetype and add a scene-level boundary treatment.
        bars = VGroup(Line(LEFT*w/2, RIGHT*w/2).shift(UP*(h/2+.08)),
                      Line(LEFT*w/2, RIGHT*w/2).shift(DOWN*(h/2+.08)))
        bars.set_color(BLUE_C)
        obj = VGroup(obj, bars)
    # Keep the background inside the component group so it moves and morphs
    # with its text. Draw it first; later components occlude the whole group.
    background = Rectangle(width=obj.width + 0.08, height=obj.height + 0.08)
    background.set_stroke(width=0)
    background.set_fill(config.background_color, opacity=1)
    background.move_to(obj)
    obj = VGroup(background, obj)
    obj.scale(float(spec.get("scale", 1.0)))
    obj.move_to([float(spec.get("x", 0)), float(spec.get("y", 0)), 0])
    return obj


def scene_spec_by_id(scene_spec, node_id):
    for spec in scene_spec.get("nodes", []):
        if spec.get("knowledge_node_id") == node_id:
            return spec
    return None


def ensure_node(scene, scene_spec, objects, node_id, *, use_initial=False, fade=True):
    if not node_id:
        return None
    spec = scene_spec_by_id(scene_spec, node_id)
    if spec is None:
        return objects.get(node_id)
    if node_id in objects:
        return objects[node_id]
    obj = make_node(spec)
    if use_initial:
        meta = spec.get("metadata", {})
        if "initial_x" in meta:
            obj.move_to([float(meta.get("initial_x", spec.get("x",0))), float(meta.get("initial_y", spec.get("y",0))), 0])
        if "initial_scale" in meta:
            obj.scale(float(meta.get("initial_scale", 1.0)))
    objects[node_id] = obj
    reveals = [obj]
    mirror = getattr(scene, "graph_mirror", None)
    if mirror and objects is not mirror[1] and node_id not in mirror[1]:
        graph_spec = scene_spec_by_id(mirror[0], node_id)
        if graph_spec:
            graph_obj = make_node(graph_spec)
            mirror[1][node_id] = graph_obj
            reveals.append(graph_obj)
    if fade:
        scene.play(*[FadeIn(item) for item in reveals], run_time=0.45)
    else:
        scene.add(*reveals)
    return obj


def transform_to_final(scene, scene_spec, objects, node_id, duration=0.7):
    invalidate_local_links(scene, {node_id})
    if node_id not in objects:
        return ensure_node(scene, scene_spec, objects, node_id)
    spec = scene_spec_by_id(scene_spec, node_id)
    if spec is None:
        return objects[node_id]
    desired = make_node(spec)
    replace_component(scene, objects[node_id], desired, duration)
    objects[node_id] = desired
    return desired


def replace_component(scene, old, new, duration=0.7):
    # Morph continuously, then discard aligned source glyphs at the endpoint.
    scene.play(Transform(old, new), run_time=duration)
    scene.remove(old, *old.get_family())
    scene.add(new)
    return new


def role_node(scene_spec, role):
    for spec in scene_spec.get("nodes", []):
        if spec.get("metadata", {}).get("semantic_role") == role:
            return spec.get("knowledge_node_id")
    return None


def relation_by_id(scene_spec, rel_id):
    for rel in scene_spec.get("relations", []):
        if rel.get("relation_id") == rel_id:
            return rel
    return None


def pulse_between(scene, a, b, duration=0.6, dashed=False):
    if a is None or b is None:
        return
    start, end = a.get_center(), b.get_center()
    distance = sum(float(y - x) ** 2 for x, y in zip(start, end)) ** 0.5
    if distance < 1e-6:
        scene.play(Indicate(b), run_time=duration)
        return
    line = DashedLine(start, end, dash_length=0.12) if dashed else Arrow(start, end, buff=min(0.55, distance * 0.2), stroke_width=2.4, max_tip_length_to_length_ratio=0.12)
    # DashedLine is a collection of dashes, not a continuous motion path.
    motion_path = Line(line.get_start(), line.get_end(), buff=0)
    scene.play(Create(line), run_time=duration*0.65)
    dot = Dot(radius=0.06).move_to(line.get_start())
    scene.add(dot)
    scene.play(MoveAlongPath(dot, motion_path), run_time=duration)
    scene.play(FadeOut(dot), FadeOut(line), run_time=0.25)


def show_subtitle(scene, text, current):
    text = str(text or "")
    if current is not None and getattr(current, "subtitle_text", None) == text:
        return current
    if current is not None:
        scene.remove(current, *current.get_family())
    if not text:
        return None
    new = fitted_text(text, 21, 11.2, 0.65) if ENGLISH else Text(text, font_size=21)
    if new.width > 11.2:
        new.scale_to_fit_width(11.2)
    new.to_edge(DOWN, buff=0.18)
    new.subtitle_text = text
    scene.add(new)
    return new


def invalidate_local_links(scene, node_ids):
    remaining = []
    for endpoints, items in getattr(scene, "local_links", []):
        if endpoints & set(node_ids):
            for item in items:
                scene.remove(item, *item.get_family())
        else:
            remaining.append((endpoints, items))
    scene.local_links = remaining


def remember_local_link(scene, node_ids, *items):
    if not hasattr(scene, "local_links"):
        scene.local_links = []
    scene.local_links.append((set(node_ids), items))


def fallback_relation(scene, scene_spec, objects, beat):
    rel_ids = beat.get("relation_ids", [])
    if not rel_ids:
        return
    rel = relation_by_id(scene_spec, rel_ids[0])
    if not rel:
        return
    a = ensure_node(scene, scene_spec, objects, rel.get("source_node_id"))
    b = ensure_node(scene, scene_spec, objects, rel.get("target_node_id"))
    if a is None or b is None:
        return
    delta = b.get_center() - a.get_center()
    if abs(delta[0]) >= abs(delta[1]):
        start, end = (a.get_right(), b.get_left()) if delta[0] >= 0 else (a.get_left(), b.get_right())
    else:
        start, end = (a.get_top(), b.get_bottom()) if delta[1] >= 0 else (a.get_bottom(), b.get_top())
    arrow = Arrow(start, end, buff=0.08, stroke_width=2.2, max_tip_length_to_length_ratio=0.12)
    if rel.get("label_mode") == "shown":
        txt = label(rel.get("narrative_relation_type") or rel.get("relation_type"), 16).next_to(arrow, UP, buff=0.05)
        if abs(delta[0]) >= abs(delta[1]) and txt.width > max(.4, arrow.width):
            txt.scale_to_fit_width(max(.4, arrow.width))
        scene.play(Create(arrow), FadeIn(txt), run_time=float(beat.get("duration",0.6)))
        remember_local_link(scene, (rel.get("source_node_id"), rel.get("target_node_id")), arrow, txt)
    else:
        scene.play(Create(arrow), run_time=float(beat.get("duration",0.6)))
        scene.play(FadeOut(arrow), run_time=0.2)


def animate_beat(scene, scene_spec, objects, beat):
    if beat.get('template_id') == 'evidence_revisit':
        # Re-establish the view without rerunning its transformations or signals.
        ids = list(beat.get('node_ids', []))
        for rel in scene_spec.get('relations', []):
            if rel.get('relation_id') in beat.get('relation_ids', []):
                ids.extend(rel.get(k) for k in ('stored_source_node_id', 'stored_target_node_id', 'mediator_node_id') if rel.get(k))
        ids = list(dict.fromkeys(ids))
        for nid in ids:
            ensure_node(scene, scene_spec, objects, nid, fade=False)
        targets = [objects[nid] for nid in ids if nid in objects]
        if targets:
            scene.play(*[Indicate(obj, scale_factor=1.02) for obj in targets], run_time=1.2)
        else:
            scene.wait(1.2)
        return
    if scene_spec.get("layout") == "persistent_subgraph":
        animate_graph_beat(scene, scene_spec, objects, beat)
        return
    template = beat.get("template_id", "")
    phase = beat.get("phase_id", "")
    p = beat.get("parameters", {})
    duration = float(beat.get("duration", 0.7))
    if template == "address_calc":
        animate_address_calculation(scene, scene_spec, objects, beat)
        return
    if template == 'processor_trace':
        animate_processor_trace(scene, scene_spec, objects, beat)
        return
    if template == 'memory_trace':
        animate_memory_trace(scene, scene_spec, objects, beat)
        return
    if template == 'semantic_scene':
        ids = beat.get('node_ids', [])
        for nid in ids:
            ensure_node(scene, scene_spec, objects, nid)
        if phase.startswith('highlight') or phase == 'emphasize_claim':
            anims = [Indicate(objects[n], color=YELLOW, scale_factor=1.03) for n in ids if n in objects]
            if anims:
                scene.play(*anims, run_time=duration)
        return
    if p.get('scene_pattern') in {'ABSTRACTION_INTERFACE', 'ONE_ABSTRACTION_MULTI_IMPLEMENTATION'}:
        # Relation grammar still supplies the pattern, phases, timing and text.
        # In this scene, its effect stays local and the shared interface persists.
        rel = relation_by_id(scene_spec, (beat.get('relation_ids') or [''])[0])
        if rel and rel['relation_type'] in {'INTERFACES_WITH', 'DEPENDS_ON', 'IMPLEMENTS'}:
            a = ensure_node(scene, scene_spec, objects, rel['stored_source_node_id'])
            b = ensure_node(scene, scene_spec, objects, rel['stored_target_node_id'])
            if a is not None and b is not None:
                if p.get('scene_relation_start'):
                    # Attach vertically to the interface bar at the other
                    # object's x coordinate; get_boundary_point picks a corner
                    # on long bars and creates misleading diagonal crossings.
                    def attachment(obj, other, is_boundary):
                        point = (obj.get_top() if other.get_center()[1] >= obj.get_center()[1]
                                 else obj.get_bottom()).copy()
                        if is_boundary:
                            point[0] = max(obj.get_left()[0]+.1,
                                min(obj.get_right()[0]-.1, other.get_center()[0]))
                        return point
                    boundary = p.get('scene_semantic_roles', {}).get('boundary')
                    start = attachment(a, b, rel['stored_source_node_id'] == boundary)
                    end = attachment(b, a, rel['stored_target_node_id'] == boundary)
                    link = (DashedLine(start, end, buff=.08, color=GREEN_C)
                            if rel['relation_type'] == 'IMPLEMENTS'
                            else Line(start, end, buff=.08, color=BLUE_C)
                            if rel['relation_type'] == 'INTERFACES_WITH'
                            else Arrow(start, end, buff=.08, color=BLUE_C, max_tip_length_to_length_ratio=.15))
                    scene.play(Create(link), run_time=duration)
                    remember_local_link(scene, (rel['stored_source_node_id'], rel['stored_target_node_id']), link)
                elif p.get('scene_relation_end'):
                    scene.play(Indicate(b, scale_factor=1.03), run_time=duration)
                else:
                    scene.play(Indicate(a, color=BLUE_C, scale_factor=1.02),
                               Indicate(b, color=BLUE_C, scale_factor=1.02), run_time=duration)
            return
    if template in {"dependency_gate", "capability_unlock", "cause_chain", "problem_solution_bridge"}:
        animate_causal_relation(scene, scene_spec, objects, beat)
        return
    if template in {"abstract_to_concrete", "principle_to_mechanism", "purpose_reveal", "factor_to_metric", "resource_flow"}:
        animate_isa_relation(scene, scene_spec, objects, beat)
        return
    if template in {"table_highlight", "push_pop"}:
        animate_data_structure(scene, scene_spec, objects, beat)
        return

    # --- category / IS_A -------------------------------------------------
    if template == "category_embed":
        cat = p.get("category_id") or p.get("supertype_id") or role_node(scene_spec, "category")
        mem = p.get("member_id") or p.get("subtype_id") or role_node(scene_spec, "member")
        if phase == "establish_supertype":
            ensure_node(scene, scene_spec, objects, cat)
        elif phase == "introduce_member":
            ensure_node(scene, scene_spec, objects, mem, use_initial=True)
        elif phase == "embed_member":
            transform_to_final(scene, scene_spec, objects, mem, duration)
        elif phase == "emphasize_membership":
            a, b = objects.get(cat), objects.get(mem)
            anims = [Indicate(x, scale_factor=1.03) for x in (a,b) if x is not None]
            if anims: scene.play(*anims, run_time=duration)
        return

    # --- part/whole ------------------------------------------------------
    if template in {"reveal_inside", "zoom_in_nesting"}:
        whole = p.get("whole_id") or role_node(scene_spec, "whole")
        part = p.get("part_id") or role_node(scene_spec, "part")
        if phase in {"establish_whole", "establish_parent"}:
            ensure_node(scene, scene_spec, objects, whole)
        elif phase in {"open_structure", "focus_child"}:
            if whole in objects: scene.play(Indicate(objects[whole], scale_factor=1.02), run_time=duration)
        elif phase in {"reveal_part", "zoom_child"}:
            ensure_node(scene, scene_spec, objects, part, use_initial=True)
            transform_to_final(scene, scene_spec, objects, part, duration)
        elif phase == "emphasize_part" and part in objects:
            scene.play(Indicate(objects[part]), run_time=duration)
        return

    if template == "tree_expand":
        root = beat.get("node_ids", [None])[0] if beat.get("node_ids") else role_node(scene_spec, "root")
        if phase == "show_parent":
            ensure_node(scene, scene_spec, objects, root)
        elif phase == "expand_children":
            for nid in beat.get("node_ids", []):
                ensure_node(scene, scene_spec, objects, nid)
            # Semantic tree connectors, intentionally without raw relation labels.
            root_obj = objects.get(root)
            if root_obj:
                lines = []
                for nid in beat.get("node_ids", [])[1:]:
                    if nid in objects:
                        lines.append(Line(root_obj.get_bottom(), objects[nid].get_top()))
                if lines:
                    scene.play(*[Create(x) for x in lines], run_time=duration)
                    remember_local_link(scene, beat.get("node_ids", []), *lines)
        elif phase == "highlight_structure":
            anims = [Indicate(objects[n]) for n in beat.get("node_ids", []) if n in objects]
            if anims: scene.play(*anims, run_time=duration)
        return

    # --- transform -------------------------------------------------------
    if template in {"pipeline_transform", "morph"}:
        source = p.get("source_id") or (beat.get("node_ids") or [None])[0]
        target = p.get("target_id") or (beat.get("node_ids") or [None])[-1]
        mediator = p.get("mediator_id")
        if phase == "show_source":
            ensure_node(scene, scene_spec, objects, source)
        elif phase == "show_mediator":
            ensure_node(scene, scene_spec, objects, mediator)
        elif phase in {"pass_through", "transform"}:
            src_obj = ensure_node(scene, scene_spec, objects, source)
            if src_obj is not None:
                ghost = src_obj.copy()
                scene.add(ghost)
                if mediator:
                    med = ensure_node(scene, scene_spec, objects, mediator)
                    scene.play(ghost.animate.move_to(med.get_center()), run_time=duration*0.55)
                tgt_spec = scene_spec_by_id(scene_spec, target)
                if tgt_spec:
                    tgt = make_node(tgt_spec)
                    ghost = replace_component(scene, ghost, tgt, duration*0.7)
                    scene.play(FadeOut(ghost), run_time=0.18)
        elif phase in {"reveal_target", "settle_target"}:
            ensure_node(scene, scene_spec, objects, target)
            if target in objects: scene.play(Indicate(objects[target]), run_time=duration)
        return

    # --- interface -------------------------------------------------------
    if template == "interface_bridge":
        upper = role_node(scene_spec, "upper_layer")
        lower = role_node(scene_spec, "lower_layer")
        inter = role_node(scene_spec, "interface")
        if phase == "show_upper": ensure_node(scene, scene_spec, objects, upper)
        elif phase == "show_lower": ensure_node(scene, scene_spec, objects, lower)
        elif phase == "insert_interface": ensure_node(scene, scene_spec, objects, inter)
        elif phase == "bridge_interaction":
            if upper in objects and inter in objects: pulse_between(scene, objects[upper], objects[inter], duration*0.6)
            if inter in objects and lower in objects: pulse_between(scene, objects[inter], objects[lower], duration*0.6)
        return

    # --- execution -------------------------------------------------------
    if template == "token_enter_and_act":
        executor = p.get("executor_id") or role_node(scene_spec, "executor")
        token = p.get("token_id") or role_node(scene_spec, "token")
        if phase == "show_executor": ensure_node(scene, scene_spec, objects, executor)
        elif phase == "show_token": ensure_node(scene, scene_spec, objects, token, use_initial=True)
        elif phase == "enter_executor":
            tok = ensure_node(scene, scene_spec, objects, token)
            exe = ensure_node(scene, scene_spec, objects, executor)
            if tok and exe:
                ghost = tok.copy(); scene.add(ghost)
                scene.play(ghost.animate.move_to(exe.get_center()), run_time=duration)
                scene.play(FadeOut(ghost), run_time=0.18)
        elif phase == "activate_executor" and executor in objects:
            scene.play(Indicate(objects[executor], scale_factor=1.04), run_time=duration)
        return

    # --- control / management -------------------------------------------
    if template in {"control_signal", "highlight_target"}:
        controller = p.get("controller_id") or role_node(scene_spec, "controller")
        target = p.get("target_id") or role_node(scene_spec, "target")
        if phase in {"show_controller", "show_relation_context"}: ensure_node(scene, scene_spec, objects, controller)
        elif phase == "show_target": ensure_node(scene, scene_spec, objects, target)
        elif phase == "emit_signal":
            a = ensure_node(scene, scene_spec, objects, controller); b = ensure_node(scene, scene_spec, objects, target)
            pulse_between(scene, a, b, duration, dashed=True)
        elif phase in {"target_changes", "highlight_target"} and target in objects:
            scene.play(Indicate(objects[target], scale_factor=1.05), run_time=duration)
        return

    # --- storage ---------------------------------------------------------
    if template in {"write_in", "read_out"}:
        storage = p.get("storage_id") or role_node(scene_spec, "storage")
        payload = p.get("payload_id") or role_node(scene_spec, "payload")
        if phase == "show_storage": ensure_node(scene, scene_spec, objects, storage)
        elif phase in {"show_payload", "select_payload"}: ensure_node(scene, scene_spec, objects, payload)
        elif phase == "write_payload":
            a = ensure_node(scene, scene_spec, objects, payload); b = ensure_node(scene, scene_spec, objects, storage)
            if a and b:
                ghost=a.copy(); scene.add(ghost); scene.play(ghost.animate.move_to(b.get_center()), run_time=duration); scene.play(FadeOut(ghost), run_time=0.15)
        elif phase == "read_payload":
            a = ensure_node(scene, scene_spec, objects, storage); b = ensure_node(scene, scene_spec, objects, payload)
            if a and b:
                ghost=b.copy().move_to(a.get_center()); scene.add(ghost); scene.play(ghost.animate.move_to(b.get_center()), run_time=duration); scene.play(FadeOut(ghost), run_time=0.15)
        elif phase == "persist_payload" and storage in objects:
            scene.play(Indicate(objects[storage]), run_time=duration)
        return

    # --- comparisons -----------------------------------------------------
    if template in {"side_by_side", "split_screen"}:
        left = p.get("left_id") or role_node(scene_spec, "left")
        right = p.get("right_id") or role_node(scene_spec, "right")
        if phase in {"show_left", "split"}: ensure_node(scene, scene_spec, objects, left)
        elif phase in {"show_right", "show_both"}:
            ensure_node(scene, scene_spec, objects, left); ensure_node(scene, scene_spec, objects, right)
        elif phase in {"compare", "sync_compare"}:
            anims=[Indicate(objects[x]) for x in (left,right) if x in objects]
            if anims: scene.play(*anims, run_time=duration)
        return

    # --- event propagation: persist the event through its phase sequence ---
    if template == "event_propagation":
        rel = relation_by_id(scene_spec, (beat.get("relation_ids") or [None])[0])
        if not rel:
            fallback_relation(scene, scene_spec, objects, beat)
            return
        source = ensure_node(scene, scene_spec, objects, rel["stored_source_node_id"])
        target = ensure_node(scene, scene_spec, objects, rel["stored_target_node_id"])
        if source is None or target is None:
            return
        key = rel["relation_id"]
        state = scene.event_tokens
        if key not in state:
            state[key] = Dot(radius=0.07, color=YELLOW).move_to(source.get_top() + UP*0.12)
            scene.play(FadeIn(state[key]), run_time=0.25)
        token = state[key]
        if phase == "propagate":
            route = Line(token.get_center(), target.get_top() + UP*0.12)
            scene.play(MoveAlongPath(token, route), run_time=duration)
        elif phase in {"show_consequence", "target_response"}:
            scene.play(Indicate(target, color=YELLOW, scale_factor=1.06), run_time=duration)
            scene.play(FadeOut(token), run_time=0.2)
            state.pop(key, None)
        else:
            scene.play(Indicate(source, scale_factor=1.03), run_time=duration)
        return

    # --- flow / generic causal / mechanism ------------------------------
    if template in {"connect_highlight", "process_flow"}:
        ids = list(beat.get("node_ids", []))
        for nid in ids: ensure_node(scene, scene_spec, objects, nid)
        if phase in {"move_payload", "propagate", "connect", "advance"} and len(ids)>=2:
            pulse_between(scene, objects.get(ids[0]), objects.get(ids[-1]), duration)
        elif phase in {"highlight", "show_consequence", "target_response"} and ids:
            scene.play(Indicate(objects[ids[-1]]), run_time=duration)
        return

    if template in {"mechanism_overlay", "multilevel_cache_fallback"}:
        animate_cache_mechanism(scene, scene_spec, objects, beat)
        return
    if template in {"overlay", "layer_hide_reveal", "metric_change", "tradeoff_gauge", "timeline_trend", "parallel_flow", "pipeline_stages", "path_reveal", "bit_build", "sequence_reveal", "hierarchy_gradient"}:
        ids = list(beat.get("node_ids", []))
        for nid in ids: ensure_node(scene, scene_spec, objects, nid)
        anims = [Indicate(objects[nid], scale_factor=1.03) for nid in ids if nid in objects]
        if anims: scene.play(*anims, run_time=duration)
        return

    if template in {"definition_focus", "overview_reveal", "fade_reveal", "highlight_existing"}:
        ids=list(beat.get("node_ids", []))
        for nid in ids: ensure_node(scene, scene_spec, objects, nid)
        if phase in {"definition", "highlight"}:
            anims=[Indicate(objects[nid], scale_factor=1.04) for nid in ids if nid in objects]
            if anims: scene.play(*anims, run_time=duration)
        return

    if template == "text_note":
        note = Text(str(beat.get("narration", "")), font_size=26)
        if note.width > 11: note.scale_to_fit_width(11)
        scene.play(FadeIn(note), run_time=0.4); scene.wait(duration); scene.play(FadeOut(note), run_time=0.25)
        return

    fallback_relation(scene, scene_spec, objects, beat)


def graph_relation(scene, rel, objects):
    a = objects[rel["stored_source_node_id"]]
    b = objects[rel["stored_target_node_id"]]
    start, end = a.get_center(), b.get_center()
    delta = end - start
    if np.linalg.norm(delta) < 1e-6:
        curve = Arc(radius=0.5, start_angle=0, angle=TAU*0.9).next_to(a, RIGHT, buff=0.05)
    else:
        normal = np.array([-delta[1], delta[0], 0]) / np.linalg.norm(delta)
        sign = 1 if rel.get("metadata", {}).get("canonical_forward", True) else -1
        offset = normal * float(rel.get("metadata", {}).get("lane", 0)) * 0.55 * sign
        start = a.get_boundary_point(delta)
        end = b.get_boundary_point(-delta)
        curve = CubicBezier(start, start + (end-start)/3 + offset,
                            start + 2*(end-start)/3 + offset, end)
    curve.set_stroke(BLUE_C, width=2).set_fill(opacity=0)
    tip = Arrow(curve.point_from_proportion(0.92), curve.get_end(), buff=0,
                color=BLUE_C, stroke_width=0, tip_length=0.12,
                max_tip_length_to_length_ratio=0.8)
    names = {"PART_OF": "组成", "CONTAINS": "包含", "IS_A": "属于",
             "CONTROLS": "控制", "MANAGES": "管理", "USES": "使用",
             "EXECUTES": "执行", "TRANSFORMS_TO": "转换", "STORES": "存储",
             "INTERFACES_WITH": "接口", "IMPLEMENTS": "实现", "REQUIRES": "需要",
             "AFFECTS": "影响", "ENABLES": "支持", "CAUSES": "导致",
             "HAS_FUNCTION": "功能", "EXPLOITS": "利用", "BASED_ON": "基于",
             "DESCRIBES": "描述", "CONSTRAINS": "约束", "RESULTS_IN": "带来",
             "SOLVES": "解决", "PREVENTS": "防止", "DEPENDS_ON": "依赖"}
    text = Text(names.get(rel["relation_type"], rel["relation_type"]), font_size=16)
    text.move_to(curve.point_from_proportion(0.4))
    text.add_background_rectangle(color=config.background_color, opacity=1, buff=0.035)
    curve.set_z_index(-2)
    tip.set_z_index(-2)
    text.set_z_index(-1)
    group = VGroup(curve, tip, text)
    scene.play(Create(curve), FadeIn(tip), FadeIn(text), run_time=0.4)
    return group


def animate_graph_beat(scene, spec, objects, beat):
    duration = float(beat.get("duration", 0.7))
    rels = [relation_by_id(spec, rid) for rid in beat.get("relation_ids", [])]
    rels = [r for r in rels if r]
    phase = beat.get("phase_id", "")
    for rel in rels:
        a, b = objects[rel["stored_source_node_id"]], objects[rel["stored_target_node_id"]]
        if phase in {"emit_signal", "move_payload", "enter_executor", "write_payload", "read_payload", "propagate"}:
            pulse_between(scene, a, b, duration, dashed=phase == "emit_signal")
        elif phase in {"transform", "pass_through"}:
            ghost = a.copy().set_z_index(5)
            scene.add(ghost)
            target = b.copy().set_z_index(5)
            ghost = replace_component(scene, ghost, target, duration)
            scene.play(FadeOut(ghost), run_time=0.15)
        else:
            scene.play(Indicate(b, scale_factor=1.03), run_time=duration)
    if not rels:
        scene.wait(duration)


def emphasize_graph_edge(group, active):
    opacity = 1 if active else 0.5
    # set_opacity on the whole group would fill the open Bezier curve.
    group[0].set_stroke(opacity=opacity).set_fill(opacity=0)
    group[1].set_opacity(opacity)
    group[2].set_opacity(1)


def recent_local_nodes(scenes, scene_index, beat_index, limit=2):
    """The preceding two drawing beats; title cards do not age the cache."""
    history = []
    for index, spec in enumerate(scenes[:scene_index + 1]):
        if spec.get('scene_role') == 'subquestion_intro':
            continue
        local = spec.get('metadata', {}).get('local_scene')
        if not local:
            continue
        beats = spec.get('beats', [])
        if index == scene_index:
            beats = beats[:beat_index]
        for beat in beats:
            ids = set(beat.get('node_ids', []))
            stage = local.get('metadata', {}).get('local_stages', {}).get(beat.get('beat_id'), local)
            for rel in stage.get('relations', []):
                if rel.get('relation_id') in beat.get('relation_ids', []):
                    ids.update(rel[k] for k in ('source_node_id', 'target_node_id', 'mediator_node_id') if rel.get(k))
            history.append(ids)
    return set().union(*history[-limit:]) if history else set()


def upcoming_local_nodes(scenes, scene_index, beat_index=0, limit=2):
    """Nodes needed by the next two beats, across subquestion boundaries."""
    needed = set()
    remaining = limit
    for index in range(scene_index, len(scenes)):
        spec = scenes[index]
        if spec.get('scene_role') == 'subquestion_intro':
            continue
        local = spec.get("metadata", {}).get("local_scene")
        if spec.get("scene_role") == "summary" or not local:
            break
        start = beat_index if index == scene_index else 0
        for beat in spec.get("beats", [])[start:]:
            if remaining <= 0:
                return needed
            needed.update(beat.get("node_ids", []))
            stage = local.get("metadata", {}).get("local_stages", {}).get(beat.get("beat_id"), local)
            for relation in stage.get("relations", []):
                if relation.get("relation_id") in beat.get("relation_ids", []):
                    needed.update(relation.get(key) for key in
                                  ("source_node_id", "target_node_id", "mediator_node_id")
                                  if relation.get(key))
            remaining -= 1
    return needed


def next_scene_carry_nodes(scenes, start, visible, limit=2):
    """Retain at most two visible nodes, ordered by first use in the next scene."""
    for spec in scenes[start:]:
        if spec.get('scene_role') == 'subquestion_intro':
            continue
        if spec.get('scene_role') == 'summary':
            return set()
        local = spec.get('metadata', {}).get('local_scene') or spec
        ordered = []
        for beat in spec.get('beats', []):
            ids = list(beat.get('node_ids', []))
            stage = local.get('metadata', {}).get('local_stages', {}).get(beat.get('beat_id'), local)
            for rel in stage.get('relations', []):
                if rel.get('relation_id') in beat.get('relation_ids', []):
                    ids.extend(rel.get(k) for k in
                               ('source_node_id', 'target_node_id', 'mediator_node_id'))
            for nid in ids:
                if nid and nid in visible and nid not in ordered:
                    ordered.append(nid)
        return set(ordered[:limit])
    return set()


class GeneratedExplanation(Scene):
    def construct(self):
        import textwrap
        question = Text("\n".join(textwrap.wrap(PLAN.get("question", "Explanation"), width=56 if ENGLISH else 32, break_long_words=not ENGLISH, break_on_hyphens=not ENGLISH)), font_size=36)
        if question.width > 11.5: question.scale_to_fit_width(11.5)
        if question.height > 5.5: question.scale_to_fit_height(5.5)
        question.move_to(ORIGIN)
        self.play(FadeIn(question), run_time=0.6)
        opening_audio = PLAN.get("opening_audio")
        if opening_audio:
            self.add_sound(opening_audio["path"])
            self.wait(float(opening_audio["duration"]) + 0.4)
        else:
            self.wait(2.5)
        self.play(FadeOut(question), run_time=0.4)
        title = Text(PLAN.get("question", "Explanation"), font_size=27).to_edge(UP, buff=0.18)
        if title.width > 11.5: title.scale_to_fit_width(11.5)
        self.play(FadeIn(title), run_time=0.4)

        objects = {}
        graph_edges = {}
        summary_objects = []
        subtitle = None
        previous_scene_ids = set()

        local_objects = {}
        scenes = PLAN.get("scenes", [])
        for scene_index, scene_spec in enumerate(scenes):
            if scene_spec.get('scene_role') == 'subquestion_intro':
                subtitle = show_subtitle(self, '', subtitle)
                # Keep existing narration audio, without drawing question cards.
                for beat in scene_spec.get('beats', []):
                    audio = beat.get('audio')
                    if audio:
                        self.add_sound(audio['path'])
                        self.wait(float(audio['duration']) + 0.2)
                continue
            if scene_spec.get("scene_role") == "summary":
                # A standalone closing card: no graph, local demo or header.
                self.graph_mirror = None
                if self.mobjects:
                    self.play(*[FadeOut(m) for m in list(self.mobjects)], run_time=0.5)
                self.clear()
                objects.clear()
                graph_edges.clear()
                local_objects.clear()
                subtitle = None
                points = scene_spec.get("metadata", {}).get("summary_points", [])
                summary_objects = [Text("\n".join(textwrap.wrap(str(point), width=68 if ENGLISH else 38, break_long_words=not ENGLISH, break_on_hyphens=not ENGLISH)),
                                        font_size=28) for point in points]
                panel = VGroup(*summary_objects).arrange(DOWN, buff=0.4)
                if panel.width > 11.5: panel.scale_to_fit_width(11.5)
                if panel.height > 5.8: panel.scale_to_fit_height(5.8)
                panel.move_to(ORIGIN)
                audio_deadline = None
                for beat in scene_spec.get("beats", []):
                    audio = beat.get("audio")
                    if audio:
                        self.add_sound(audio["path"])
                        audio_deadline = self.time + float(audio["duration"])
                    index = int(beat.get("parameters", {}).get("summary_index", 0))
                    if 0 <= index < len(summary_objects):
                        self.play(FadeIn(summary_objects[index]), run_time=0.4)
                    self.wait(float(beat.get("duration", 3)))
                    if beat.get("audio_end") and audio_deadline is not None:
                        self.wait(max(1 / config.frame_rate, audio_deadline - self.time))
                        audio_deadline = None
                if audio_deadline is not None:
                    self.wait(max(1 / config.frame_rate, audio_deadline - self.time))
                continue
            if (scene_spec.get('layout') == 'persistent_subgraph' or
                    (not scene_spec.get('metadata', {}).get('atomic_semantic_scene')
                     and PLAN.get('metadata', {}).get('presentation') != 'semantic_scenes')):
                scene_spec = panel_spec(scene_spec, -3.3)
            if getattr(self, 'local_links', None):
                invalidate_local_links(self, set(objects))
            persistent = scene_spec.get("layout") == "persistent_subgraph"
            desired = {n.get("knowledge_node_id") for n in scene_spec.get("nodes", [])}
            carry = set(scene_spec.get("carry_over_node_ids", []))

            # Remove stale objects, but keep concepts explicitly carried into the next scene.
            stale = [] if persistent else [nid for nid in list(objects) if nid not in desired and nid not in carry]
            if stale:
                self.play(*[FadeOut(objects[nid]) for nid in stale], run_time=0.28)
                for nid in stale: objects.pop(nid, None)

            # Re-layout carried objects before semantic beats start.
            replacements = {}
            for nid in ([] if persistent else desired & set(objects)):
                spec = scene_spec_by_id(scene_spec, nid)
                if spec:
                    replacements[nid] = make_node(spec)
            if replacements:
                self.play(*[Transform(objects[nid], obj) for nid, obj in replacements.items()], run_time=0.45)
                for nid in replacements:
                    old = objects[nid]
                    self.remove(old, *old.get_family())
                objects.update(replacements)
                self.add(*replacements.values())

            scene_title = None

            audio_deadline = None
            local_spec = scene_spec.get("metadata", {}).get("local_scene")
            prerequisite_scene = bool(scene_spec.get('metadata', {}).get('prerequisite'))
            self.local_links = []
            local_archive = {}
            self.event_tokens = {}
            self.structure_states = {}
            self.causal_states = {}
            self.processor_traces = {}
            self.memory_traces = {}
            local_stage_id = None
            self.graph_mirror = (scene_spec, objects) if local_spec and not prerequisite_scene else None
            if local_spec:
                # Locate this evidence on the overview, then use independent
                # semantic objects without modifying the persistent graph.
                active = set(scene_spec.get("metadata", {}).get("active_relation_ids", []))
                for rid, edge in graph_edges.items():
                    emphasize_graph_edge(edge, rid in active)
                highlights = [Indicate(objects[nid], scale_factor=1.05)
                              for nid in scene_spec.get("metadata", {}).get("active_node_ids", []) if nid in objects]
                if highlights:
                    self.play(*highlights, run_time=0.6)
            for beat_index, beat in enumerate(scene_spec.get("beats", [])):
                subtitle = show_subtitle(self, beat.get("narration", ""), subtitle)
                audio = beat.get("audio")
                if audio:
                    self.add_sound(audio["path"])
                    audio_deadline = self.time + float(audio["duration"])
                if persistent and not local_spec:
                    for nid in beat.get("node_ids", []):
                        ensure_node(self, scene_spec, objects, nid)
                    active = set(beat.get("relation_ids", []))
                    for rid, mob in graph_edges.items():
                        emphasize_graph_edge(mob, rid in active)
                    for rid in active:
                        rel = relation_by_id(scene_spec, rid)
                        if rel and rid not in graph_edges:
                            for nid in (rel["stored_source_node_id"], rel["stored_target_node_id"]):
                                ensure_node(self, scene_spec, objects, nid)
                            graph_edges[rid] = graph_relation(self, rel, objects)
                if beat.get("template_id") == "summary":
                    index = int(beat.get("parameters", {}).get("summary_index", 0))
                    self.play(FadeIn(summary_objects[index]), run_time=0.4)
                    self.wait(float(beat.get("duration", 3)))
                else:
                    stage = (local_spec or {}).get("metadata", {}).get("local_stages", {}).get(beat.get("beat_id"), local_spec)
                    if stage:
                        stage = prerequisite_panel_spec(stage) if prerequisite_scene else panel_spec(stage, 3.2)
                    if stage:
                        keep = recent_local_nodes(scenes, scene_index, beat_index)
                        keep.update(upcoming_local_nodes(scenes, scene_index, beat_index, limit=1))
                        stale = set(local_objects) - keep
                        if stale:
                            invalidate_local_links(self, stale)
                            self.play(*[FadeOut(local_objects[nid]) for nid in stale], run_time=.2)
                            for nid in stale:
                                local_archive[nid] = local_objects.pop(nid)
                    if stage and stage.get("scene_id") != local_stage_id:
                        invalidate_local_links(self, set(local_objects))
                        stage_ids = {n["knowledge_node_id"] for n in stage.get("nodes", [])}
                        upcoming = recent_local_nodes(scenes, scene_index, beat_index)
                        stale_local = [nid for nid in local_objects
                                       if nid not in stage_ids and nid not in upcoming]
                        if stale_local:
                            self.play(*[FadeOut(local_objects[nid]) for nid in stale_local], run_time=0.2)
                            for nid in stale_local:
                                local_archive[nid] = local_objects.pop(nid)
                        for nid in stage_ids & set(local_archive):
                            obj = local_archive.pop(nid)
                            target_spec = scene_spec_by_id(stage, nid)
                            if target_spec:
                                obj.become(make_node(target_spec))
                            local_objects[nid] = obj
                            self.play(FadeIn(obj), run_time=0.25)
                        for nid in stage_ids & set(local_objects):
                            transform_to_final(self, stage, local_objects, nid, 0.35)
                        local_stage_id = stage.get("scene_id")
                    animate_beat(self, stage or scene_spec,
                                 local_objects if local_spec else objects, beat)
                    if local_spec:
                        active = set(beat.get("relation_ids", []))
                        for rid, edge in graph_edges.items():
                            emphasize_graph_edge(edge, rid in active)
                        phase = beat.get("phase_id", "")
                        introduction = phase.startswith(("show_", "establish_", "introduce_", "create_", "select_"))
                        for rid in active:
                            rel = relation_by_id(scene_spec, rid)
                            if rel and not introduction and rid not in graph_edges:
                                endpoints = (rel["stored_source_node_id"], rel["stored_target_node_id"])
                                if all(nid in objects for nid in endpoints):
                                    graph_edges[rid] = graph_relation(self, rel, objects)
                if beat.get("audio_end") and audio_deadline is not None:
                    remaining = audio_deadline - self.time
                    if remaining > 0:
                        self.wait(remaining)
                    audio_deadline = None

            if local_spec:
                # Keep visible components needed immediately after this subquestion.
                # Connectors, labels and clones remain scene-local.
                upcoming = next_scene_carry_nodes(scenes, scene_index + 1, local_objects)
                local_objects = {nid: obj for nid, obj in local_objects.items() if nid in upcoming}
                protected = {id(m) for obj in [title, scene_title, subtitle, *objects.values(), *graph_edges.values(), *local_objects.values()] if obj is not None for m in obj.get_family()}
                temporary = [m for m in list(self.mobjects) if id(m) not in protected]
                if temporary:
                    self.play(*[FadeOut(m) for m in temporary], run_time=0.3)
                    self.remove(*temporary)
                self.wait(0.5)

            # Guarantee a stable final state even if a semantic grammar omitted
            # an optional reveal phase.
            missing=[] if local_spec or scene_spec.get("scene_role") == "summary" else [nid for nid in desired if nid not in objects]
            if missing:
                new_objects=[]
                for nid in missing:
                    spec=scene_spec_by_id(scene_spec,nid)
                    if spec:
                        obj=make_node(spec)
                        objects[nid]=obj
                        new_objects.append(obj)
                if new_objects:
                    self.play(*[FadeIn(obj) for obj in new_objects], run_time=0.4)

            if not local_spec and not persistent:
                carry = next_scene_carry_nodes(scenes, scene_index + 1, objects)
                stale = set(objects) - carry
                if stale:
                    invalidate_local_links(self, stale)
                    self.play(*[FadeOut(objects[nid]) for nid in stale], run_time=0.3)
                    for nid in stale:
                        obj = objects.pop(nid)
                        self.remove(*obj.get_family())
            self.wait(0.35)
            subtitle = show_subtitle(self, "", subtitle)
            # Remove scene-local connectors and labels as well as temporary copies.
            keep = {id(m) for obj in [title, *objects.values(), *graph_edges.values(), *summary_objects, *local_objects.values()] for m in obj.get_family()}
            self.remove(*[m for m in list(self.mobjects) if id(m) not in keep])
            previous_scene_ids = desired

        if subtitle is not None:
            self.play(FadeOut(subtitle), run_time=0.2)
        for edge in graph_edges.values():
            emphasize_graph_edge(edge, True)
        self.wait(2 if graph_edges else 0.35)
'''
