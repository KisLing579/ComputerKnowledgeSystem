"""Batch 2: address formation, control-flow graphs and processor datapaths."""
import inspect

EXECUTION_ARCHETYPES = frozenset({"addressing", "control_flow", "datapath_graph"})


def address_calculation(mode, values=None):
    """Deterministic teaching examples; branch32 explicitly models a 32-bit PC+4 ISA."""
    defaults = {"base_offset": {"base": 4096, "offset": 12},
                "indexed": {"base": 4096, "index": 3, "stride": 4},
                "pc_relative": {"pc": 4096, "offset": 12},
                "branch32": {"pc": 4096, "immediate": 65534}}
    if mode not in defaults:
        raise ValueError("Unsupported address calculation: " + mode)
    data = dict(defaults[mode])
    if values:
        if set(values) - set(data):
            raise ValueError("Unexpected address operands")
        data.update(values)
    if any(type(v) is not int for v in data.values()):
        raise ValueError("Address operands must be integers")
    if mode == "branch32":
        if not 0 <= data["pc"] <= 0xffffffff or not 0 <= data["immediate"] <= 0xffff:
            raise ValueError("branch32 requires unsigned 32-bit PC and 16-bit immediate")
        signed = data["immediate"] if data["immediate"] < 0x8000 else data["immediate"] - 0x10000
        result = (data["pc"] + 4 + signed * 4) & 0xffffffff
        inputs = f'PC={data["pc"]}; imm16=0x{data["immediate"]:04X}'
        formula = f'{data["pc"]} + 4 + ({signed} * 4)'
    elif mode == "indexed":
        if data["stride"] <= 0:
            raise ValueError("Element stride must be positive")
        result = data["base"] + data["index"] * data["stride"]
        inputs = f'base={data["base"]}; i={data["index"]}; size={data["stride"]}'
        formula = f'{data["base"]} + {data["index"]} * {data["stride"]}'
    else:
        base_key = "pc" if mode == "pc_relative" else "base"
        result = data[base_key] + data["offset"]
        inputs = f'{base_key}={data[base_key]}; offset={data["offset"]}'
        formula = f'{data[base_key]} + ({data["offset"]})'
    return {"inputs": inputs, "formula": formula, "result": result}


def execution_design(spec, english=False):
    req = set(spec.get("metadata", {}).get("render_requirements", ()))
    kind = spec["archetype"]
    def tr(en, zh):
        return en if english else zh
    caption = tr("Schematic; not to scale", "结构示意；非实际比例")
    mode = None
    layout = "chain"
    edge_labels = []
    if kind == "addressing":
        if "constant_in_instruction" in req:
            labels = [tr("Instruction", "指令"), tr("Immediate", "立即数"), tr("Operand", "操作数")]
        elif "register_operand" in req:
            labels = [tr("Register ID", "寄存器号"), tr("Register", "寄存器"), tr("Operand", "操作数")]
            caption = tr("Register operand; no memory read", "寄存器操作数；不读取内存")
        elif "26bit_target_shift2" in req:
            labels = ["(PC+4)[31:28]", "target26 << 2", "next PC"]
            layout = "merge"
            caption = tr("32-bit example: concatenate, not add", "32位示例：拼接，不是相加")
        elif "pc_plus_4" in req:
            labels, mode = ["PC + 4", "sext(imm16) * 4", "next PC"], "branch32"
            layout = "merge"
            caption = tr("32-bit PC+4 branch model", "32位 PC+4 分支模型")
        elif "pc_plus_offset" in req:
            labels, mode = ["PC", tr("Offset", "偏移"), tr("Target", "目标地址")], "pc_relative"
            layout = "merge"
            caption = tr("PC reference and displacement depend on ISA", "PC基准与位移单位取决于指令集")
        elif "base_plus_scaled_index" in req:
            labels, mode = ["base", "index * size", "EA"], "indexed"
            layout = "merge"
        elif "saved_pc" in req:
            labels = [tr("Call", "调用"), tr("Saved return PC", "保存返回地址"), tr("Resume", "继续执行")]
        elif "handler_address" in req:
            labels = [tr("Exception", "异常"), tr("Handler entry", "处理程序入口"), "PC"]
        elif "byte_cells" in req:
            labels = ["B+0", "B+1", "B+2", "B+3"]
            caption = tr("Four consecutive bytes; word example", "连续四字节；字的示例")
        elif "address_in_register" in req:
            labels = [tr("Pointer register", "指针寄存器"), tr("Address", "地址"), tr("Memory cell", "存储单元")]
            caption = tr("Pointer increment depends on element size", "指针步长取决于元素大小")
        elif req & {"base_plus_offset", "base_plus_displacement", "numeric_delta"}:
            labels, mode = ["base", tr("Offset", "偏移"), "EA"], "base_offset"
            layout = "merge"
        else:
            labels = ["B", "B+1", "B+2", "B+3"]
            caption = tr("Addressed cells; B marks the base", "带地址的单元；B为基址")
    elif kind == "control_flow":
        if "predicate" in req:
            labels = [tr("Predicate", "谓词"), tr("Apply effect", "执行效果"), tr("Suppress effect", "抑制效果")]
            layout, edge_labels = "fork", [tr("true", "真"), tr("false", "假")]
            caption = tr("Conditional effect, not a PC branch", "条件生效，不表示PC分支")
        elif "single_entry_single_exit" in req:
            labels = ["I1", "I2", "I3"]
            caption = tr("Single entry / single exit", "单入口 / 单出口")
        elif "nested_calls" in req:
            labels, layout = ["caller", "callee A", "callee B"], "return"
            caption = tr("Nested calls: save / restore return state", "嵌套调用：保存/恢复返回状态")
        elif "self_call" in req:
            labels, layout = ["f(n)", "f(n-1)", "f(n-2)"], "return"
            caption = tr("Separate recursive activations; base case omitted", "不同递归调用帧；省略终止分支")
        elif "save_return_address" in req:
            labels, layout = [tr("Caller", "调用者"), tr("Callee", "被调用者"), tr("Resume PC", "返回位置")], "call"
        elif "register_target" in req:
            labels = [tr("Jump register", "跳转寄存器"), tr("Target PC", "目标PC")]
        elif req & {"single_jump_path", "jump_target"}:
            labels = ["PC", tr("Jump target", "跳转目标")]
        elif "cause_to_vector" in req:
            labels = [tr("Cause / vector", "原因/向量"), tr("Handler A", "处理程序A"), tr("Handler B", "处理程序B")]
            layout, edge_labels = "fork", ["A", "B"]
        elif req & {"handler", "fsm_to_exception_state"}:
            labels = [tr("Current PC", "当前PC"), tr("Save context", "保存现场"), tr("Handler", "处理程序")]
            caption = tr("Exception / interrupt transfer; resume is conditional", "异常/中断转移；能否恢复取决于处理结果")
        else:
            condition = "rs == rt?" if "compare_equal" in req else "rs != rt?" if "compare_not_equal" in req else tr("Condition?", "条件？")
            labels, layout = [condition, tr("Target PC", "目标PC"), "PC + 4"], "fork"
            edge_labels = [tr("true", "真"), tr("false", "假")]
            caption = tr("PC+4 schematic; delay slots omitted", "PC+4示意；省略延迟槽")
            if "condition_true" in req:
                caption = tr("Taken path highlighted", "高亮跳转路径")
            elif "condition_false" in req:
                caption = tr("Fall-through path highlighted", "高亮顺序路径")
    elif kind == "datapath_graph":
        if "select_signal" in req:
            labels, layout = ["in 0", "in 1", "MUX", "out"], "mux"
            caption = tr("Select chooses one input", "选择信号决定一个输入")
        elif "two_read_ports" in req:
            labels, layout = [tr("Register file", "寄存器堆"), "read A", "read B"], "fork"
            edge_labels = ["rs", "rt"]
        elif "pc_to_instruction_memory" in req or "IF_ID" in req:
            labels = ["PC", "I-Mem", "IF/ID" if "IF_ID" in req else "Instruction"]
        elif "ID_stage" in req:
            labels, layout = ["ID compare", "Branch adder", "next PC"], "merge"
        elif "target_address" in req:
            labels, layout = ["Compare", "Target", "next PC"], "merge"
        elif "five_stages" in req:
            labels = ["IF", "ID", "EX", "MEM", "WB"]
            caption = tr("Pipeline registers separate stages", "流水线寄存器分隔各阶段")
        elif req & {"destination_field", "control_bits"}:
            labels = ["ID/EX", "EX/MEM", "MEM/WB", "WB"]
            caption = tr("Aligned destination / control fields", "目的字段/控制位随指令对齐传递")
        elif "result_paths" in req:
            labels, layout = ["EX/MEM", "MEM/WB", "Forward MUX", "ALU"], "mux"
            caption = tr("Forward results to consumer inputs", "结果旁路到使用者输入")
        elif "ID_EX" in req:
            labels = ["Decode", "RegFile", "ID/EX"]
        elif "EX_MEM" in req or "alu_inputs" in req:
            labels, layout = ["A", "B", "ALU", "EX/MEM" if "EX_MEM" in req else "Result / Zero"], "alu"
        elif "MEM_WB" in req or "read_write" in req:
            labels = ["Address", "D-Mem", "MEM/WB" if "MEM_WB" in req else "Read / Write"]
        elif "destination_register" in req:
            labels, layout = ["ALU result", "Memory data", "WB MUX", "RegFile"], "mux"
            caption = "RegWrite"
        elif "multi_bit_signal" in req:
            labels = ["Source", "Bus / n bits", "Destination"]
        elif "lw_path" in req:
            labels = ["I-Mem", "RegFile", "ALU", "D-Mem", "WB"]
            caption = tr("Load critical-path schematic", "Load关键路径示意")
        elif req & {"resource_reuse", "different_cycles"}:
            labels, layout = ["Cycle 1", "Shared ALU", "Cycle 2"], "return"
            caption = tr("Shared resource across cycles", "跨周期复用功能单元")
        else:
            labels = ["PC", "RegFile", "ALU", "Memory", "WB"]
            caption = tr("Functional topology; control and timing abstracted", "功能拓扑；控制与时序已抽象")
    else:
        raise ValueError("Unsupported execution archetype: " + kind)
    return {"layout": layout, "labels": labels, "caption": caption, "mode": mode,
            "edge_labels": edge_labels, "selected": 0 if "condition_true" in req else 1 if "condition_false" in req else None}


SOURCE = inspect.getsource(address_calculation) + "\n" + inspect.getsource(execution_design) + r'''

def make_execution_node(spec):
    design = execution_design(spec, ENGLISH)
    w, h = float(spec.get("width", 4.0)), float(spec.get("height", 2.4))
    labels, layout = design["labels"], design["layout"]
    if layout in {"fork", "merge"}:
        coords = [(-.31, 0), (.25, .14), (.25, -.17)] if layout == "fork" else [(-.31, .14), (-.31, -.17), (.25, 0)]
        edges = [(0, 1), (0, 2)] if layout == "fork" else [(0, 2), (1, 2)]
    elif layout in {"mux", "alu"}:
        coords, edges = [(-.37, .15), (-.37, -.17), (0, 0), (.37, 0)], [(0, 2), (1, 2), (2, 3)]
    else:
        coords = [(-.34 + i * .68 / max(1, len(labels)-1), 0) for i in range(len(labels))]
        edges = [(i, i+1) for i in range(len(labels)-1)]
    parts, links = VGroup(), VGroup()
    cw = w * (.19 if len(labels) > 3 else .27)
    ch = h * .23
    for i, (text, (x, y)) in enumerate(zip(labels, coords)):
        if (layout == "mux" and i == 2):
            shape = Polygon([-cw/2, -ch/2, 0], [cw/2, -ch*.3, 0], [cw/2, ch*.3, 0], [-cw/2, ch/2, 0])
        elif (layout == "alu" and i == 2) or text == "ALU":
            shape = Polygon([-cw/2, ch/2, 0], [cw/2, ch*.3, 0], [cw/2, -ch*.3, 0], [-cw/2, -ch/2, 0], [-cw*.3, 0, 0])
        elif layout == "fork" and i == 0 and spec["archetype"] == "control_flow":
            shape = Polygon([0, ch*.65, 0], [cw*.6, 0, 0], [0, -ch*.65, 0], [-cw*.6, 0, 0])
        else:
            shape = Rectangle(width=cw, height=ch)
        shape.set_stroke(TEAL_C, width=1.5).set_fill(TEAL_C, opacity=.12).move_to([w*x, h*y, 0])
        # Polygon corners and the ALU notch leave less room than their bounding box.
        safe_w, safe_h = (cw*.42, ch*.4) if isinstance(shape, Polygon) and not isinstance(shape, Rectangle) else (cw*.82, ch*.65)
        label = fitted_text(text, 16, safe_w, safe_h).move_to(shape)
        parts.add(VGroup(shape, label))
    for i, (a, b) in enumerate(edges):
        arrow = Arrow(parts[a].get_right(), parts[b].get_left(), buff=.025,
                      color=YELLOW if design["selected"] == i else BLUE_C,
                      stroke_width=2, max_tip_length_to_length_ratio=.2)
        links.add(arrow)
        if i < len(design["edge_labels"]):
            label = fitted_text(design["edge_labels"][i], 12, w*.13, h*.08)
            label.move_to(arrow.get_center() + UP * h * (.065 if i == 0 else -.065))
            links.add(label)
    if layout == "return":
        for i in range(len(parts)-1, 0, -1):
            back = VGroup(Line(parts[i].get_bottom(), [parts[i].get_x(), -h*.25, 0]),
                          Arrow([parts[i].get_x(), -h*.25, 0], [parts[i-1].get_x(), -h*.25, 0], buff=0),
                          Line([parts[i-1].get_x(), -h*.25, 0], parts[i-1].get_bottom()))
            back.set_color(GOLD_C)
            links.add(back)
    if layout == "mux":
        links.add(Arrow([0, h*.27, 0], parts[2].get_top(), buff=.02, color=GOLD_C))
    title = fitted_text(spec.get("name", ""), 22, w*.95, h*.19).move_to([0, h*.4, 0])
    caption = fitted_text(design["caption"], 13, w*.95, h*.13).move_to([0, -h*.41, 0])
    obj = VGroup(title, links, parts, caption)
    obj.visual_parts = parts
    return obj


def animate_address_calculation(scene, spec, objects, beat):
    phase = beat.get("phase_id", "")
    duration = float(beat.get("duration", .7))
    if phase not in {"show_inputs", "calculate", "show_result"}:
        scene.wait(duration)
        return
    for nid in beat.get("node_ids", []):
        node_spec = scene_spec_by_id(spec, nid)
        if not node_spec or node_spec.get("archetype") != "addressing":
            continue
        obj = ensure_node(scene, spec, objects, nid)
        mode = execution_design(node_spec, ENGLISH)["mode"]
        if mode is None:
            continue
        if not hasattr(scene, "address_examples"):
            scene.address_examples = {}
        key = (spec.get("scene_id"), nid, tuple(beat.get("relation_ids", ())))
        if phase == "show_inputs" or key not in scene.address_examples:
            scene.address_examples[key] = address_calculation(mode, beat.get("parameters", {}).get("address_values"))
        example = scene.address_examples[key]
        text = example["inputs"] if phase == "show_inputs" else example["formula"] if phase == "calculate" else str(example["result"])
        text = ("Example: " if ENGLISH else "示例：") + text
        # Replace the node's caption in place: no detached overlays or stale state.
        caption = obj[1][-1]
        replacement = fitted_text(text, 15, obj.width*.92, obj.height*.14).move_to(caption)
        scene.play(Transform(caption, replacement), run_time=duration)
        return
    # Unsupported profiles retain their truthful schematic instead of a made-up calculation.
    scene.wait(duration)
'''
