"""Batch 3: cache and virtual-memory node schematics, with explicit example assumptions."""
import inspect

MEMORY_ARCHETYPES = frozenset({"cache_lookup", "cache_address_decode", "cache_set_lookup",
                              "tlb_translation", "page_table_map", "address_translation"})


def memory_design(spec, english=False):
    req = set(spec.get("metadata", {}).get("render_requirements", ()))
    kind = spec["archetype"]
    def tr(en, zh):
        return en if english else zh
    result = {"layout": "table", "selected": None}
    if kind == "cache_address_decode":
        address, offset_bits, index_bits = 0x1234, 4, 2
        result.update(layout="fields", fields=[("Tag", 26), ("Index", 2), ("Offset", 4)],
                      values=[hex(address >> 6), str((address >> 4) & 3), str(address & 15)],
                      caption=tr("Example: 32-bit address, 16-byte blocks, 4 sets", "示例：32位地址、16字节块、4组"))
        if "word_alignment" in req or "byte_vs_word_vs_block" in req:
            result.update(fields=[("Tag", 26), ("Index", 2), ("Word", 2), ("Byte", 2)],
                          values=[hex(address >> 6), str((address >> 4) & 3), str((address >> 2) & 3), str(address & 3)],
                          caption=tr("Example: 32-bit address, 16B block, 4 sets, 4B word", "示例：32位地址、16B块、4组、4B字"))
        result["selected"] = 0 if "high_address_bits" in req else 1 if "index_bits" in req else 2 if "within_block" in req else None
    elif kind == "cache_lookup":
        result.update(headers=["Line", "V", "Tag", "Data"], rows=[["0", "1", "0x12", "A"], ["1", "1", "0x48", "B"], ["2", "0", "--", "--"]],
                      selected=1, caption=tr("Example query: tag=0x48; hit = valid AND tag match", "示例查询tag=0x48；命中=有效且标记相同"))
        if "miss" in req:
            result.update(selected=None, caption=tr("Example tag=0x99: miss -> lower level -> fill", "示例tag=0x99：缺失→下层读取→填充"))
        elif "TLB_then_cache" in req:
            result["caption"] = tr("PIPT: TLB -> physical index + physical tag", "PIPT：TLB→物理索引与物理标记")
        elif "parallel_TLB_cache" in req:
            result["caption"] = tr("VIPT: virtual index / physical tag; TLB in parallel", "VIPT：虚拟索引/物理标记；TLB并行")
        elif "virtual_index_or_tag" in req:
            result["caption"] = tr("Virtual indexing/tagging; aliases need handling", "虚拟索引或标记；需处理别名")
        elif "multiple_ports" in req:
            result["caption"] = tr("Multiple request ports; array organization abstracted", "多请求端口；阵列组织已抽象")
    elif kind == "cache_set_lookup":
        full = "one_set" in req
        result.update(headers=["Set", "Way 0 tag", "Way 1 tag"],
                      rows=[["0", "0x12", "0x48"]] if full else [["0", "0x12", "0x48"], ["1", "0x21", "0x51"], ["2", "0x31", "0x62"]],
                      selected=0 if full else 1,
                      caption=tr("Example: one set, compare all ways", "示例：仅一组，比较全部路") if full else tr("2-way example: index selects set; tags compared in parallel", "2路示例：索引选组，组内标记并行比较"))
    elif kind == "tlb_translation":
        result.update(headers=["V", "VPN", "PPN", "ASID"], rows=[["1", "0x1", "0x9", "A"], ["1", "0x2", "0x5", "A"], ["0", "--", "--", "--"]],
                      selected=0, caption=tr("Example: VPN 1 -> PPN 9; offset unchanged", "示例：虚页1→物理页9；页内偏移不变"))
        if "no_entry" in req:
            result.update(selected=None, caption=tr("TLB miss -> page table; does not imply page fault", "TLB缺失→查询页表；不等于缺页异常"))
        elif "new_tlb_entry" in req:
            result["caption"] = tr("Resolve PTE -> fill TLB -> retry translation", "解析页表项→填充TLB→重试转换")
        elif "process_id" in req:
            result["caption"] = tr("Match ASID + VPN for address-space isolation", "匹配ASID与VPN以区分地址空间")
        elif "TLB_reach" in req:
            result["caption"] = tr("Uniform-page example: reach = entries * page size", "等大页面示例：覆盖范围=条目数×页大小")
    elif kind == "page_table_map":
        if "multi_level_index" in req:
            result.update(layout="translation", source=["VPN index 1", "VPN index 2", "Offset"],
                          target=["Level 1 -> Level 2 PTE", "PPN + Offset"],
                          caption=tr("Multilevel lookup; allocate lower tables on demand", "多级查表；下级页表按需分配"))
        elif "hash_or_search" in req:
            result.update(headers=["Frame", "ASID", "VPN"], rows=[["0", "A", "7"], ["1", "B", "2"], ["2", "A", "1"]],
                          caption=tr("Inverted table: physical frame indexes entries", "倒排页表：表项按物理页框组织"))
        else:
            result.update(headers=["VPN", "PPN", "Present", "R / D / Perm"],
                          rows=[["1", "9", "1", "1 / 0 / RW"], ["2", "5", "1", "0 / 1 / R"], ["3", "--", "0", "--"]],
                          caption=tr("Example PTE fields; actual format is ISA/OS-dependent", "示例页表项；实际格式取决于指令集/操作系统"))
            if "page_table_base" in req:
                result["caption"] = tr("Current process page-table base + VPN selects PTE", "当前进程页表基址与VPN用于定位页表项")
            elif "recent_access" in req:
                result["caption"] = tr("Reference bit records access, not an exact LRU order", "引用位记录访问，不等于精确LRU顺序")
    elif kind == "address_translation":
        result.update(layout="translation", source=["VPN = 0x1", "Offset = 0x234"], target=["PPN = 0x9", "Offset = 0x234"],
                      caption=tr("4 KiB page example: VA 0x1234 -> PA 0x9234", "4KiB页示例：虚址0x1234→物理址0x9234"))
    else:
        raise ValueError("Unsupported memory archetype: " + kind)
    return result


SOURCE = inspect.getsource(memory_design) + r'''

def make_memory_node(spec):
    design = memory_design(spec, ENGLISH)
    w, h = float(spec.get("width", 4.5)), float(spec.get("height", 2.7))
    parts = VGroup()
    colors = [BLUE_C, TEAL_C, GOLD_C, PURPLE_C]
    def cell(text, x, y, cw, ch, i, selected=False):
        rect = Rectangle(width=cw, height=ch, stroke_width=1.3,
                         color=YELLOW if selected else colors[i % len(colors)])
        rect.set_fill(YELLOW if selected else colors[i % len(colors)], opacity=.2 if selected else .08)
        rect.move_to([x, y, 0])
        label = fitted_text(text, 16, cw*.9, ch*.78).move_to(rect)
        return VGroup(rect, label)
    if design["layout"] == "fields":
        fields = design["fields"]
        cw = w*.94 / len(fields)
        # Equal display widths keep narrow fields legible; numeric widths are explicit.
        for i, ((label, bits), value) in enumerate(zip(fields, design["values"])):
            parts.add(cell(label + "\n" + str(bits) + " bits\n" + value,
                           -w*.47 + (i+.5)*cw, 0, cw, h*.48, i, design["selected"] == i))
    elif design["layout"] == "translation":
        for row, labels in enumerate([design["source"], design["target"]]):
            cw = w*.94 / len(labels)
            for i, label in enumerate(labels):
                parts.add(cell(label, -w*.47+(i+.5)*cw, h*(.16 if row == 0 else -.16), cw, h*.2, i))
        parts.add(Arrow([0, h*.055, 0], [0, -h*.055, 0], buff=.01, color=YELLOW,
                        max_tip_length_to_length_ratio=.3))
    else:
        rows = [design["headers"]] + design["rows"]
        ch = h*.56 / len(rows)
        cw = w*.94 / len(rows[0])
        for row, labels in enumerate(rows):
            cells = VGroup()
            for col, label in enumerate(labels):
                cells.add(cell(label, -w*.47+(col+.5)*cw, h*.25-(row+.5)*ch, cw, ch, col,
                               row > 0 and row-1 == design["selected"]))
            parts.add(cells)
    title = fitted_text(spec.get("name", ""), 22, w*.94, h*.18).move_to([0, h*.4, 0])
    caption = fitted_text(design["caption"], 13, w*.94, h*.14).move_to([0, -h*.41, 0])
    obj = VGroup(title, parts, caption)
    obj.visual_parts = parts
    return obj
'''
