"""Batch 4: memory policy, residency, hierarchy and request schematics."""
import inspect

MEMORY_SYSTEM_ARCHETYPES = frozenset({"cache_write_policy", "replacement_choice", "memory_hierarchy_stack",
                                    "virtual_memory_map", "page_fault_flow", "memory_request_timeline"})


def memory_system_design(spec, english=False):
    req = set(spec.get("metadata", {}).get("render_requirements", ()))
    kind = spec["archetype"]
    def tr(en, zh):
        return en if english else zh
    d = {"layout": "steps", "caption": tr("Schematic example; timing not to scale", "示意示例；时序非实际比例"), "selected": None}
    if kind == "cache_write_policy":
        if "bypass_allocation" in req or "bypass_cache" in req:
            d["labels"] = [tr("Write miss", "写缺失"), tr("No cache allocation", "不分配缓存块"), tr("Write lower level", "写入下层")]
            d["caption"] = tr("No-write-allocate example", "不写分配示例")
        elif "fetch_block" in req:
            d["labels"] = [tr("Write miss", "写缺失"), tr("Fetch / allocate", "取块/分配"), tr("Write cache", "写入缓存")]
            d["caption"] = tr("Write allocation is separate from write-through/back", "写分配与写通过/写回是不同维度的策略")
        elif req & {"cache_only_write", "writeback_required"}:
            d["labels"] = [tr("Write cache", "写入缓存"), "Dirty = 1", tr("Evict dirty line", "替换脏行"), tr("Write lower level", "写回下层")]
            d["caption"] = tr("Clean eviction needs no data writeback", "干净行被替换时无需写回数据")
        elif "buffer" in req:
            d["labels"] = [tr("CPU store", "CPU写入"), tr("Cache / write buffer", "缓存/写缓冲"), tr("Lower level", "下层存储")]
            d["caption"] = tr("Buffer decouples writes; ordering/full-buffer stalls omitted", "缓冲分离写入过程；省略顺序约束和缓冲满停顿")
        else:
            d["labels"] = [tr("CPU store", "CPU写入"), tr("Update cache", "更新缓存"), tr("Update lower level", "更新下层")]
            d["caption"] = tr("Write-through hit example; buffering may defer lower write", "写通过命中示例；写缓冲可推迟下层写入")
    elif kind == "replacement_choice":
        d.update(layout="replacement", labels=["A", "B", "C", "D"], selected=0)
        if "recency" in req:
            d["caption"] = tr("LRU example: last-use order A,B,C,D; replace A", "LRU示例：从旧到新A、B、C、D；替换A")
        elif "random" in req and "LRU" not in req:
            d["selected"] = 2
            d["caption"] = tr("Illustrative random choice: C; not based on recency", "随机选择示例：C；不依据最近访问顺序")
        elif "physical_pages" in req:
            d["labels"] = ["Frame 0", "Frame 1", "Frame 2", "Frame 3"]
            d["caption"] = tr("OS chooses a frame; dirty victim may need page-out", "操作系统选择页框；脏牺牲页可能需要换出")
        elif "tlb_entries" in req:
            d["labels"] = ["VPN 1", "VPN 2", "VPN 3", "VPN 4"]
            d["caption"] = tr("Replace a translation entry, not physical-page contents", "替换地址转换条目，不替换物理页内容")
        else:
            d["selected"] = None
            d["caption"] = tr("Candidate entries; policy determines victim", "候选条目；由替换策略决定牺牲项")
    elif kind == "memory_hierarchy_stack":
        d.update(layout="hierarchy", labels=["CPU", "L1", "L2", "DRAM", tr("Backing storage", "后备存储")])
        if "L3" in req:
            d["labels"] = ["CPU", "L1", "L2", "L3", "DRAM"]
        elif "instruction_cache" in req:
            d["labels"] = ["CPU", "L1 I-Cache | D-Cache", "L2", "DRAM"]
            d["caption"] = tr("Split instruction/data L1; lower sharing is schematic", "L1指令/数据分离；下层共享关系为示意")
        elif "upper_level" in req and not req & {"found", "not_found"}:
            d["labels"] = [tr("Upper level", "上层"), tr("Transfer unit", "传输单位"), tr("Lower level", "下层")]
            d["caption"] = tr("Transfer unit depends on the adjacent levels", "传输单位取决于相邻层次")
        elif "found" in req:
            d.update(selected=1, caption=tr("Upper-level hit serves the request", "上层命中即可服务请求"))
        elif "not_found" in req:
            d.update(selected=2, caption=tr("Upper-level miss requests the next level", "上层缺失后请求下层"))
        elif "wide_bus" in req:
            d["caption"] = tr("Wider transfers move multiple words; bandwidth not quantified", "宽传输可同时移动多个字；未量化带宽")
        elif "physical_pages" in req:
            d.update(selected=3, caption=tr("DRAM holds resident physical pages", "DRAM存放驻留物理页"))
        elif "closest_to_cpu" in req:
            d.update(selected=1, caption=tr("L1: close to CPU; capacity/latency are design-dependent", "L1靠近CPU；容量和延迟取决于设计"))
        elif "after_L1" in req:
            d.update(selected=2, caption=tr("L2 backs L1; size and miss rate depend on workload/design", "L2承接L1；容量与缺失率依赖设计和负载"))
        elif "set_associative" in req:
            d["labels"] = [tr("Direct mapped", "直接映像"), tr("Set associative", "组相联"), tr("Fully associative", "全相联")]
            d["caption"] = tr("Placement alternatives; these are not serial cache levels", "放置策略的备选项；不是串联缓存层次")
            d["layout"] = "alternatives"
    elif kind == "virtual_memory_map":
        d.update(layout="residency", left=["VPN 0", "VPN 1", "VPN 2"],
                 right=["Frame 9", "Frame 5", tr("Backing page", "后备页")], pairs=[(0, 0), (1, 1), (2, 2)])
        d["caption"] = tr("Example: two resident pages, one backed nonresident page", "示例：两页驻留，一页有后备存储但未驻留")
        if "two_virtual_addresses" in req:
            d.update(pairs=[(0, 0), (1, 0)], left=["VA alias A", "VA alias B"], right=["Physical page"])
            d["caption"] = tr("Two virtual aliases share one physical page", "两个虚拟别名映射同一物理页")
        elif "isolation" in req:
            d.update(left=["Process A: VPN 1", "Process B: VPN 1"], right=["Frame 9", "Frame 5"], pairs=[(0, 0), (1, 1)])
            d["caption"] = tr("Same VPN in different address spaces can map differently", "不同地址空间的相同VPN可映射不同页框")
        elif "direct_physical_mapping" in req:
            d.update(left=[tr("Resident direct-map VA", "驻留直接映射虚址")], right=[tr("Physical address", "物理地址")], pairs=[(0, 0)])
            d["caption"] = tr("Resident direct-map region; not a guarantee for all kernel memory", "驻留直接映射区域；不代表所有内核内存均不缺页")
        elif "page_location" in req:
            d["caption"] = tr("Backing locations are schematic; file/swap policy is OS-dependent", "后备位置为示意；文件/交换区策略取决于操作系统")
    elif kind == "page_fault_flow":
        if "working_set_too_large" in req:
            d["labels"] = [tr("Memory pressure", "内存压力"), tr("Frequent faults", "频繁缺页"), tr("Paging I/O", "页面输入输出"), tr("Little progress", "执行进展缓慢")]
            d["caption"] = tr("Thrashing scenario; not every fault causes disk I/O", "抖动场景；并非每次缺页都需要磁盘IO")
        elif "no_partial_state" in req:
            d["labels"] = [tr("Faulting instruction", "触发缺页的指令"), tr("Preserve precise state", "保持精确状态"), tr("Resolve fault", "处理缺页"), tr("Retry", "重试")]
            d["caption"] = tr("Restartable instruction model; resolution must succeed", "可重启指令模型；以缺页成功处理为前提")
        else:
            d["labels"] = [tr("Not present", "页面未驻留"), tr("OS checks access", "OS检查访问"), tr("Choose frame", "选择页框"), tr("Write dirty victim?", "脏页需写回？"), tr("Page in / initialize", "调入或初始化"), tr("PTE / TLB + retry", "更新PTE/TLB并重试")]
            d["caption"] = tr("Valid recoverable fault; invalid access instead raises an error", "合法且可恢复的缺页；非法访问走错误处理")
    elif kind == "memory_request_timeline":
        d.update(layout="timeline", labels=[tr("Request", "请求"), tr("Miss / stall", "缺失/停顿"), tr("Fetch block", "读取块"), tr("Refill", "填充"), tr("Retry", "重试")])
        if "critical_word" in req:
            d["labels"] = [tr("Miss", "缺失"), tr("Critical word first", "关键字优先"), tr("Resume", "恢复执行"), tr("Remaining words", "传输剩余字")]
            d["caption"] = tr("Critical-word-first example; wraparound transfer abstracted", "关键字优先示例；回绕传输细节已抽象")
        elif "requested_word" in req:
            d["labels"] = [tr("Miss", "缺失"), tr("Requested word arrives", "所需字到达"), tr("Resume early", "提前恢复"), tr("Finish refill", "完成填充")]
        elif req & {"overlap", "multiple_outstanding_misses"}:
            d.update(layout="overlap", labels=[tr("Miss A", "缺失A"), tr("Lower-level access", "下层访问"), tr("Return A", "A返回")])
            d["second"] = [tr("Miss B", "缺失B") if "multiple_outstanding_misses" in req else tr("Independent hit", "独立命中"), tr("Complete", "完成")]
            d["caption"] = tr("Overlapping requests; requires nonblocking resources", "请求重叠示意；需要非阻塞资源支持")
        elif req & {"prefetch", "early_fetch"}:
            d["labels"] = [tr("Predict", "预测"), tr("Prefetch", "预取"), tr("Demand access", "实际请求"), tr("Possible hit", "可能命中")]
            d["caption"] = tr("Useful prefetch example; correctness/timeliness not guaranteed", "有效预取示例；预测正确性和及时性不保证")
    else:
        raise ValueError("Unsupported memory-system archetype: " + kind)
    return d


SOURCE = inspect.getsource(memory_system_design) + r'''

def make_memory_system_node(spec):
    d = memory_system_design(spec, ENGLISH)
    w, h = float(spec.get("width", 4.6)), float(spec.get("height", 3.0))
    parts, links = VGroup(), VGroup()
    def box(text, x, y, cw, ch, selected=False):
        shape = RoundedRectangle(width=cw, height=ch, corner_radius=min(.07, ch*.15), stroke_width=1.4)
        shape.set_stroke(YELLOW if selected else TEAL_C).set_fill(TEAL_C, opacity=.12)
        shape.move_to([x, y, 0])
        return VGroup(shape, fitted_text(text, 16, cw*.9, ch*.78).move_to(shape))
    def connect(a, b, vertical=False):
        links.add(Arrow(a.get_bottom() if vertical else a.get_right(), b.get_top() if vertical else b.get_left(),
                        buff=.025, color=BLUE_C, stroke_width=1.5, max_tip_length_to_length_ratio=.18))
    layout = d["layout"]
    if layout == "residency":
        columns = []
        for col, texts in enumerate([d["left"], d["right"]]):
            column = VGroup()
            for i, text in enumerate(texts):
                column.add(box(text, w*(-.29 if col == 0 else .29), h*(.19-i*.2), w*.36, h*.15))
            columns.append(column)
            parts.add(column)
        for a, b in d["pairs"]:
            connect(columns[0][a], columns[1][b])
    elif layout in {"hierarchy", "alternatives"}:
        texts = d["labels"]
        stride = h*.57 / len(texts)
        for i, text in enumerate(texts):
            cw = w*(.43 + .43*i/max(1,len(texts)-1)) if layout == "hierarchy" else w*.85
            parts.add(box(text, 0, h*.23-i*stride, cw, stride*.75, d["selected"] == i))
            if i and layout == "hierarchy":
                connect(parts[i-1], parts[i], True)
    elif layout == "replacement":
        for i, text in enumerate(d["labels"]):
            parts.add(box(text, w*(-.36 + .24*i), h*.07, w*.2, h*.25, d["selected"] == i))
        if d["selected"] is not None:
            incoming = box("New" if ENGLISH else "新项", parts[d["selected"]].get_x(), -h*.23, w*.2, h*.15)
            links.add(Arrow(incoming.get_top(), parts[d["selected"]].get_bottom(), buff=.02, color=YELLOW))
            parts.add(incoming)
    elif layout in {"timeline", "overlap"}:
        for row, texts in enumerate([d["labels"]] + ([d["second"]] if layout == "overlap" else [])):
            y = h*(.14 if row == 0 and layout == "overlap" else -.17 if row else 0)
            cw = w*.9/len(texts)
            lane = VGroup()
            for i, text in enumerate(texts):
                lane.add(box(text, -w*.45+(i+.5)*cw, y, cw*.82, h*.17))
                if i:
                    connect(lane[i-1], lane[i])
            parts.add(lane)
        links.add(Arrow([-w*.46,-h*.31,0],[w*.46,-h*.31,0],buff=0,color=GOLD_C))
    else:
        texts = d["labels"]
        # A vertical sequence makes conditional maintenance steps readable.
        stride = h*.58/len(texts)
        for i,text in enumerate(texts):
            parts.add(box(text, 0, h*.24-i*stride, w*.85, stride*.73))
            if i:
                connect(parts[i-1], parts[i], True)
    title = fitted_text(spec.get("name", ""), 22, w*.94, h*.17).move_to([0,h*.41,0])
    caption = fitted_text(d["caption"], 13, w*.94, h*.12).move_to([0,-h*.43,0])
    obj = VGroup(title, links, parts, caption)
    obj.visual_parts = parts
    return obj
'''
