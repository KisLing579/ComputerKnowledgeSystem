"""Evidence-directed effects used by the ISA neighborhood, embedded in scripts.

Only existing graph endpoints are depicted. In particular, AFFECTS never invents
a numerical gain, an improvement direction, or a performance measurement.
"""

SOURCE = r'''
def isa_endpoints(spec, beat):
    rel = relation_by_id(spec, (beat.get("relation_ids") or [None])[0])
    if not rel:
        return None
    source, target = rel["stored_source_node_id"], rel["stored_target_node_id"]
    # IMPLEMENTS and BASED_ON point from implementation/design to its basis.
    if beat["template_id"] in {"abstract_to_concrete", "principle_to_mechanism"}:
        return target, source
    return source, target


def animate_isa_relation(scene, spec, objects, beat):
    endpoints = isa_endpoints(spec, beat)
    if endpoints is None:
        fallback_relation(scene, spec, objects, beat)
        return
    first, second = endpoints
    template, phase = beat["template_id"], beat["phase_id"]
    duration = float(beat.get("duration", 0.7))
    initial = {"show_abstraction", "show_principle", "show_subject", "show_metric", "establish_endpoints"}
    reveal = {"reveal_implementation", "show_mechanism", "reveal_purpose", "show_factors", "create_payload"}
    if phase in initial:
        # Metric is the target of AFFECTS, even for reverse graph traversal.
        ensure_node(scene, spec, objects, second if template == "factor_to_metric" else first)
        if template == "resource_flow":
            ensure_node(scene, spec, objects, second)
        scene.wait(duration)
        return
    a = ensure_node(scene, spec, objects, first)
    b = ensure_node(scene, spec, objects, second)
    if a is None or b is None:
        return
    if phase in reveal:
        if template in {"abstract_to_concrete", "principle_to_mechanism"}:
            frame = SurroundingRectangle(b, color=BLUE, buff=0.09)
            scene.play(Create(frame), run_time=duration)
            remember_local_link(scene, endpoints, frame)
        elif template == "purpose_reveal":
            halo = SurroundingRectangle(b, color=GREEN, buff=0.09)
            scene.play(Create(halo), run_time=duration)
            remember_local_link(scene, endpoints, halo)
        else:
            scene.play(Indicate(a, color=BLUE), run_time=duration)
        return
    if template == "resource_flow":
        # USES is a dependency, not proof that data physically flows to the used object.
        if phase == "move_payload":
            link = DashedLine(a.get_center(), b.get_center(), color=BLUE)
            scene.play(Create(link), run_time=duration)
            scene.play(FadeOut(link), Indicate(b), run_time=0.3)
        else:
            scene.play(Indicate(b), run_time=duration)
        return
    scene_mode = bool(beat.get('parameters', {}).get('scene_pattern'))
    start, end = a.get_center(), b.get_center()
    if scene_mode:
        # Support relations use the outer edges of the shared interface scene;
        # center-to-center links would draw directly across the ISA label.
        start, end = ((a.get_right().copy(), b.get_left().copy()) if start[0] <= end[0]
                      else (a.get_left().copy(), b.get_right().copy()))
    if template in {"abstract_to_concrete", "principle_to_mechanism"}:
        # A correspondence is not a transformation: preserve both objects.
        link = DashedLine(start, end, color=BLUE)
        caption = "实现对应" if template == "abstract_to_concrete" else "设计依据"
    else:
        link = Arrow(start, end, buff=.08 if scene_mode else .25, color=YELLOW)
        caption = "功能" if template == "purpose_reveal" else "影响（不表示增减）"
    if scene_mode:
        scene.play(Create(link), run_time=duration)
        scene.play(Indicate(b, scale_factor=1.04), run_time=0.35)
        remember_local_link(scene, endpoints, link)
        return
    text = Text(caption, font_size=16)
    # Keep the caption below both objects, clear of abstraction-layer titles.
    text.move_to([(a.get_center()[0] + b.get_center()[0]) / 2,
                  min(a.get_bottom()[1], b.get_bottom()[1]) - 0.3, 0])
    if text.width > 2.7:
        text.scale_to_fit_width(2.7)
    scene.play(Create(link), FadeIn(text), run_time=duration)
    scene.play(Indicate(b, scale_factor=1.04), run_time=0.35)
    remember_local_link(scene, endpoints, link, text)
'''
