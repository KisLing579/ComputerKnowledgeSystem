"""Batch 1: workbook-driven structures, embedded into standalone Manim scripts."""
import inspect

STRUCTURED_ARCHETYPES = frozenset({
    "instruction_format", "stack_frame", "memory_map", "character_table", "table_mapping",
})


def structured_design(spec, english=False):
    """Return semantic content independently of Manim; examples are explicitly marked."""
    kind = spec["archetype"]
    requirements = set(spec.get("metadata", {}).get("render_requirements", ()))
    def tr(en, zh):
        return en if english else zh
    example = tr("Schematic example", "示意示例")
    if kind == "instruction_format":
        if "op_rs_rt_rd_shamt_funct" in requirements:
            fields = [("op", 6), ("rs", 5), ("rt", 5), ("rd", 5), ("shamt", 5), ("funct", 6)]
        elif "op_rs_rt_16bit_immediate" in requirements:
            fields = [("op", 6), ("rs", 5), ("rt", 5), ("immediate", 16)]
        elif "op_26bit_target" in requirements:
            fields = [("op", 6), ("target", 26)]
        elif "variable_bytes" in requirements or "prefix_opcode_operands" in requirements:
            return {"layout": "fields", "fields": [("prefix?", 1), ("opcode", 1), ("operands...", 3)],
                    "caption": tr("Variable length; schematic proportions", "变长编码；宽度仅为示意"), "bits": False}
        else:
            return {"layout": "fields", "fields": [("opcode", 1), ("operands", 2)],
                    "caption": tr("Field widths depend on the ISA", "字段宽度取决于指令集"), "bits": False}
        return {"layout": "fields", "fields": fields, "caption": "32 bits", "bits": True}
    if kind == "stack_frame":
        if "fp_stack" in requirements:
            rows = [("ST(0)", tr("top", "栈顶")), ("ST(1)", "..."), ("ST(i)", "...")]
            caption = tr("Logical register stack / LIFO", "逻辑寄存器栈 / 后进先出")
        elif "frame_boundaries" in requirements:
            rows = [(tr("caller frame", "调用者栈帧"), "..."),
                    (tr("saved state", "保存的状态"), "..."), (tr("locals", "局部变量"), "...")]
            caption = tr("Frame layout is ABI-dependent", "栈帧布局取决于 ABI")
        else:
            rows = [("A", tr("earlier", "先入栈")), ("B", ""), ("C", tr("top", "栈顶"))]
            caption = tr("LIFO; downward growth example", "后进先出；向下增长示例")
        return {"layout": "stack", "rows": rows, "caption": caption, "top": 0 if "fp_stack" in requirements else 2}
    if kind == "memory_map":
        return {"layout": "regions", "rows": [(tr("Stack", "栈"), ""), (tr("Free", "空闲区"), ""),
                (tr("Heap", "堆"), ""), (tr("Data", "数据"), ""), (tr("Code", "代码"), "")],
                "caption": tr("High to low addresses; schematic", "地址从高到低；布局示意"),
                "highlight": 2 if "dynamic_allocation" in requirements else None}
    if kind == "character_table":
        unicode_mode = "codepoints" in requirements or "multilingual_characters" in requirements
        return {"layout": "table", "rows": [("A", "U+0041"), (chr(0x03A9), "U+03A9"), (chr(0x4E2D), "U+4E2D")] if unicode_mode
                else [("A", "1000001"), ("B", "1000010"), ("0", "0110000")],
                "headers": [tr("Character", "字符"), tr("Code point", "码点") if unicode_mode else "ASCII (7 bits)"],
                "caption": example}
    if kind == "table_mapping":
        if "variables_to_registers" in requirements:
            headers, rows = [tr("Variable", "变量"), tr("Location", "位置")], [("x", "r1"), ("y", "r2"), ("z", "spill slot")]
        elif "patch_locations" in requirements:
            headers, rows = [tr("Patch site", "修补位置"), tr("Symbol", "符号")], [("0x10", "foo"), ("0x24", "bar")]
        elif "settings" in requirements:
            headers, rows = [tr("Setting", "配置项"), tr("Value", "取值")], [("CPU", "..."), ("OS", "..."), ("Compiler", "...")]
        else:
            headers, rows = [tr("Symbol", "符号"), tr("Address", "地址")], [("foo", "0x1000"), ("bar", "0x1020"), ("data", "0x2000")]
        return {"layout": "table", "rows": rows, "headers": headers, "caption": example}
    raise ValueError("Unsupported structured archetype: " + kind)


SOURCE = inspect.getsource(structured_design) + r'''

def make_structured_node(spec):
    design = structured_design(spec, ENGLISH)
    w, h = float(spec.get("width", 3.6)), float(spec.get("height", 2.0))
    group = VGroup()
    title = fitted_text(spec.get("name", ""), 22, w * .94, h * .2)
    title.move_to([0, h * .39, 0])
    group.add(title)
    parts = VGroup()
    colors = [BLUE_C, TEAL_C, GREEN_C, GOLD_C, PURPLE_C, RED_C]

    def cell(text, x, y, cw, ch, index, highlighted=False):
        border = Rectangle(width=cw, height=ch, color=colors[index % len(colors)], stroke_width=1.5)
        border.set_fill(colors[index % len(colors)], opacity=.3 if highlighted else .1)
        border.move_to([x, y, 0])
        caption = fitted_text(text, 16, cw * .9, ch * .78).move_to(border)
        return VGroup(border, caption)

    if design["layout"] == "fields":
        fields = design["fields"]
        total = sum(size for _, size in fields)
        left = -w * .47
        for i, (name, size) in enumerate(fields):
            cw = w * .94 * size / total
            text = name + ("\n" + str(size) + " b" if design["bits"] else "")
            parts.add(cell(text, left + cw / 2, 0, cw, h * .38, i))
            left += cw
    else:
        rows = list(design["rows"])
        headers = design.get("headers")
        if headers:
            rows.insert(0, headers)
        ch = h * .54 / len(rows)
        for i, row in enumerate(rows):
            y = h * .23 - (i + .5) * ch
            if design["layout"] == "table":
                parts.add(VGroup(cell(row[0], -w * .235, y, w * .47, ch, i),
                                 cell(row[1], w * .235, y, w * .47, ch, i)))
            else:
                parts.add(cell("  ".join(t for t in row if t), w * .04, y, w * .76, ch, i,
                               i == design.get("highlight")))
        if design["layout"] == "stack":
            target = parts[design["top"]]
            arrow = Arrow([-w*.49, target.get_y(), 0], [-w*.35, target.get_y(), 0], buff=0, color=YELLOW)
            parts.add(arrow)
        elif design["layout"] == "regions":
            parts.add(Arrow([-w*.45, -h*.29, 0], [-w*.45, h*.22, 0], buff=0, color=YELLOW))
    group.add(parts)
    caption = fitted_text(design["caption"], 13, w * .94, h * .14)
    caption.move_to([0, -h * .41, 0])
    group.add(caption)
    # Keep semantic parts available for previews and future dedicated transitions.
    group.visual_parts = parts
    return group
'''
