"""Source embedded in generated scripts; operates on the Manim runtime globals."""

SOURCE = r'''
def animate_data_structure(scene, spec, objects, beat):
    template, phase = beat["template_id"], beat["phase_id"]
    duration = float(beat.get("duration", 0.8))
    rid = (beat.get("relation_ids") or [beat["beat_id"]])[0]
    key = (template, rid)
    if not hasattr(scene, "structure_states"):
        scene.structure_states = {}
    states = scene.structure_states
    if key not in states:
        for nid in beat.get("node_ids", []):
            ensure_node(scene, spec, objects, nid)
        header = Text("映射表示意" if template == "table_highlight" else "栈操作示意（非实际地址）", font_size=18).move_to([3.2, 1.5, 0])
        cells = VGroup(*[Rectangle(width=1.8, height=0.42).move_to([3.2, 0.8-i*0.42, 0]) for i in range(3)])
        for i, nid in enumerate(beat.get("node_ids", [])):
            if nid in objects:
                scene.play(objects[nid].animate.move_to([2.0+(i%3)*1.2, -1.3-(i//3)*0.6, 0]), run_time=0.2)
        scene.play(FadeIn(header), Create(cells), run_time=0.4)
        state = {"cells": cells}
        if template == "table_highlight":
            labels = VGroup(*[Text(f"键{i+1} → 值{i+1}", font_size=15).move_to(cells[i]) for i in range(3)])
            scene.play(FadeIn(labels), run_time=0.25)
        else:
            base = box_label("已有数据", width=1.5, height=0.33).move_to(cells[2])
            sp = Text("SP →", font_size=16).next_to(cells[2], LEFT, buff=0.1)
            state["sp"] = sp
            frame = Rectangle(width=2.05, height=0.5, color=BLUE).move_to(cells[2])
            state["frame"] = frame
            scene.play(FadeIn(base), FadeIn(sp), Create(frame), run_time=0.25)
        states[key] = state
    state = states[key]
    cells = state["cells"]
    if template == "table_highlight":
        if phase == "locate_entry":
            focus = SurroundingRectangle(cells[1], color=YELLOW, buff=0.02)
            label_in = Text("输入：键2", font_size=15).move_to([1.55, 1.05, 0])
            arrow = Arrow(label_in.get_bottom(), cells[1].get_left(), buff=0.08, color=YELLOW)
            scene.play(FadeIn(label_in), Create(arrow), Create(focus), run_time=duration)
            remember_local_link(scene, beat.get("node_ids", []), arrow, label_in, focus)
        elif phase == "resolve_output":
            output = Text("输出：值2", font_size=15).move_to([5.0, -0.3, 0])
            arrow = Arrow(cells[1].get_right(), output.get_top(), buff=0.08, color=YELLOW)
            scene.play(Create(arrow), FadeIn(output), run_time=duration)
            remember_local_link(scene, beat.get("node_ids", []), arrow, output)
        else:
            scene.wait(duration)
    elif phase == "push_value":
        value = box_label("待保存数据", width=1.5, height=0.33).move_to([5.0, 1.0, 0])
        state["value"] = value
        scene.play(FadeIn(value), run_time=0.2)
        frame = Rectangle(width=2.05, height=0.92, color=BLUE).move_to((cells[1].get_center()+cells[2].get_center())/2)
        scene.play(value.animate.move_to(cells[1]), state["sp"].animate.next_to(cells[1], LEFT, buff=0.1), Transform(state["frame"], frame), run_time=duration)
    elif phase == "pop_value" and "value" in state:
        frame = Rectangle(width=2.05, height=0.5, color=BLUE).move_to(cells[2])
        scene.play(state["value"].animate.move_to([5.0, 1.0, 0]), state["sp"].animate.next_to(cells[2], LEFT, buff=0.1), Transform(state["frame"], frame), run_time=duration)
        scene.play(FadeOut(state.pop("value")), run_time=0.2)
    else:
        scene.wait(duration)
'''
