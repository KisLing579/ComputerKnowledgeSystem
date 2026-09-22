"""Mechanism overlays and an explicitly illustrative cache-miss trace."""

SOURCE = r'''
def animate_cache_mechanism(scene, spec, objects, beat):
    phase = beat['phase_id']
    duration = float(beat.get('duration', .8))
    rel = relation_by_id(spec, (beat.get('relation_ids') or [None])[0])
    if not rel:
        fallback_relation(scene, spec, objects, beat)
        return
    ids = (rel['stored_source_node_id'], rel['stored_target_node_id'])
    a = ensure_node(scene, spec, objects, ids[0])
    b = ensure_node(scene, spec, objects, ids[1])
    if a is None or b is None:
        return
    if beat['template_id'] == 'mechanism_overlay':
        # EXPLOITS: source is the mechanism, target the exploited property.
        if phase == 'show_structure':
            scene.play(Indicate(a, color=BLUE), run_time=duration)
        elif phase == 'show_property':
            shade = SurroundingRectangle(a, buff=.12, color=TEAL,
                                         fill_color=TEAL, fill_opacity=.15)
            badge = b.copy().scale(.55).next_to(a, UP, buff=.15)
            scene.play(TransformFromCopy(b, badge), FadeIn(shade), run_time=duration)
            remember_local_link(scene, ids, VGroup(shade, badge))
        else:
            # Show property activation, without fabricating quantitative gains.
            pulse = SurroundingRectangle(a, buff=.18, color=YELLOW)
            link = DashedLine(b.get_center(), a.get_center(), color=TEAL)
            scene.play(Create(link), Create(pulse), run_time=duration / 2)
            scene.play(Indicate(a, color=TEAL), FadeOut(pulse), FadeOut(link), run_time=duration / 2)
        return

    if not hasattr(scene, 'cache_traces'):
        scene.cache_traces = {}
    key = (rel['relation_id'], tuple(ids))
    if phase == 'show_levels' or key not in scene.cache_traces:
        if key in scene.cache_traces:
            scene.remove(scene.cache_traces[key]['group'])
        center_x = (a.get_center()[0] + b.get_center()[0]) / 2
        center_x = min(3.5, max(-3.5, center_x))
        boxes = VGroup(*[VGroup(RoundedRectangle(width=.95, height=.55, corner_radius=.08),
                                fitted_text(name, 18, .95*.82, .55*.7)) for name in ['L1', 'L2', 'L3', '主存']])
        boxes.arrange(RIGHT, buff=.3).move_to([center_x, -.5, 0])
        caption = Text('示例：含L3，单次请求逐级未命中（非实测）', font_size=16).next_to(boxes, UP, buff=.25)
        token = Dot(radius=.07, color=YELLOW).next_to(boxes[0], UP, buff=.08)
        stats = Text('等待请求', font_size=16).next_to(boxes, DOWN, buff=.3)
        group = VGroup(boxes, caption, token, stats)
        scene.cache_traces[key] = dict(group=group, boxes=boxes, token=token, stats=stats)
        scene.play(FadeIn(group), run_time=.4)
        remember_local_link(scene, ids, group)
    state = scene.cache_traces[key]
    indices = {'probe_l1': 0, 'fallback_l2': 1, 'fallback_l3': 2, 'access_memory': 3}
    if phase in indices:
        i = indices[phase]
        if i:
            scene.play(Indicate(state['boxes'][i-1], color=RED), run_time=.25)
        scene.play(state['token'].animate.next_to(state['boxes'][i], UP, buff=.08),
                   Indicate(state['boxes'][i], color=YELLOW), run_time=duration)
        delay = ' + '.join(['tL1', 'tL2', 'tL3', 'tMem'][:i+1])
        misses = min(i, 3)
        text = f'累计延迟 = {delay}\n已发生缺失：{misses}；本例各已缺失层 Local=1/1，Global=1/1'
    elif phase == 'show_accounting':
        text = 'Local Miss = 本层缺失 / 到达本层请求\nGlobal Miss = 本层缺失 / CPU请求总数\n逐级访问延迟 = tL1 + tL2 + tL3 + tMem'
    else:
        return
    replacement = Text(text, font_size=15)
    if replacement.width > 5.5: replacement.scale_to_fit_width(5.5)
    replacement.move_to(state['stats'].get_center())
    scene.play(Transform(state['stats'], replacement), run_time=.3)
'''
