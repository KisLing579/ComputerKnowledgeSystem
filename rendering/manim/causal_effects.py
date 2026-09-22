"""Workbook causal and problem/solution animations, embedded into generated scenes."""

SOURCE = r'''
def causal_endpoints(spec, beat):
    rel = relation_by_id(spec, (beat.get("relation_ids") or [None])[0])
    if not rel:
        return None
    source, target = rel["stored_source_node_id"], rel["stored_target_node_id"]
    # REQUIRES: operation -> prerequisite. SOLVES: solution -> problem.
    if beat["template_id"] in {"dependency_gate", "problem_solution_bridge"}:
        return target, source
    return source, target


def animate_causal_relation(scene, spec, objects, beat):
    endpoints = causal_endpoints(spec, beat)
    if endpoints is None:
        fallback_relation(scene, spec, objects, beat)
        return
    first, second = endpoints
    template, phase = beat["template_id"], beat["phase_id"]
    duration = float(beat.get("duration", 0.7))
    if not hasattr(scene, "causal_states"):
        scene.causal_states = {}
    key = (spec.get("scene_id"), template, tuple(beat.get("relation_ids", [])))
    state = scene.causal_states.setdefault(key, {})
    if phase == "establish":
        nid = second if template in {"dependency_gate", "capability_unlock"} else first
        obj = ensure_node(scene, spec, objects, nid)
        if obj is None:
            return
        if template in {"dependency_gate", "capability_unlock"}:
            frame = SurroundingRectangle(obj, color=RED, buff=0.12)
            bar = Line(frame.get_corner(UL), frame.get_corner(DR), color=RED)
            state["lock"] = VGroup(frame, bar)
            scene.play(Create(state["lock"]), run_time=duration)
            remember_local_link(scene, endpoints, state["lock"])
        elif template == "problem_solution_bridge":
            frame = SurroundingRectangle(obj, color=RED, buff=0.12)
            state["problem"] = frame
            scene.play(Create(frame), run_time=duration)
            remember_local_link(scene, endpoints, frame)
        else:
            scene.play(Indicate(obj, color=YELLOW), run_time=duration)
        return
    a = ensure_node(scene, spec, objects, first)
    b = ensure_node(scene, spec, objects, second)
    if a is None or b is None:
        return
    if phase == "prepare":
        if template == "problem_solution_bridge":
            # The problem precedes its solution visually, regardless of traversal.
            if a.get_center()[0] > b.get_center()[0]:
                left, right = b.get_center().copy(), a.get_center().copy()
                animations = [a.animate.move_to(left), b.animate.move_to(right)]
                if "problem" in state:
                    animations.append(state["problem"].animate.move_to(left))
                scene.play(*animations, run_time=duration)
            scene.play(Indicate(b, color=BLUE), run_time=duration)
        else:
            scene.play(Indicate(a, color=BLUE), run_time=duration)
        return
    if phase == "activate":
        lock = state.pop("lock", None)
        if lock is not None:
            scene.play(lock.animate.shift(UP * 0.35), run_time=duration * 0.3)
            scene.play(FadeOut(lock), run_time=duration * 0.2)
            scene.remove(lock, *lock.get_family())
        if template == "problem_solution_bridge":
            bridge = Line(a.get_bottom() + DOWN * 0.18, b.get_bottom() + DOWN * 0.18, color=BLUE)
            caption = Text("解决 / 缓解", font_size=16).next_to(bridge, DOWN, buff=0.08)
            scene.play(Create(bridge), FadeIn(caption), run_time=duration)
            remember_local_link(scene, endpoints, bridge, caption)
            # Preserve the problem: SOLVES can mean mitigation, not elimination.
            if "problem" in state:
                scene.play(state["problem"].animate.set_color(BLUE), run_time=0.25)
        else:
            arrow = Arrow(a.get_center(), b.get_center(), buff=0.3, color=BLUE)
            scene.play(Create(arrow), run_time=duration * 0.35)
            caption = Text({"dependency_gate": "必要条件", "capability_unlock": "使之成为可能",
                            "cause_chain": "导致"}[template], font_size=16).next_to(arrow, DOWN, buff=0.1)
            scene.play(FadeIn(caption), run_time=0.2)
            token = Dot(radius=0.06, color=YELLOW).move_to(arrow.get_start())
            scene.add(token)
            scene.play(MoveAlongPath(token, Line(arrow.get_start(), arrow.get_end())), run_time=duration * 0.65)
            scene.remove(token)
            remember_local_link(scene, endpoints, arrow, caption)
        return
    if phase == "settle":
        scene.play(Indicate(b, color=GREEN, scale_factor=1.05), run_time=duration)
'''
