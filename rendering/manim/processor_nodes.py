"""Processor diagrams and bounded illustrative execution traces (batch 05)."""
import inspect

PROCESSOR_ARCHETYPES = frozenset({
    'timing_state', 'control_fsm', 'control_table', 'microcode_flow',
    'pipeline_timeline', 'hazard_dependency', 'branch_predictor',
    'issue_bundle', 'dynamic_schedule'})


def pipeline_rows(cycles=7, stall=False, flush=False):
    """Three instructions in an illustrative five-stage pipeline, not a timing oracle."""
    if type(cycles) is not int or not 1 <= cycles <= 20:
        raise ValueError('cycles must be an integer from 1 to 20')
    rows = []
    for i in range(3):
        row = [''] * cycles
        for j, stage in enumerate(('IF', 'ID', 'EX', 'MEM', 'WB')):
            cycle = i + j
            if stall and i > 0 and cycle >= 3:
                cycle += 1
            if cycle < cycles:
                row[cycle] = stage
        if stall and i > 0 and 3 < cycles:
            row[3] = 'hold ID' if i == 1 else 'hold IF'
        if flush and i > 0:
            for c in range(3, cycles):
                if row[c]: row[c] = 'flush'
        rows.append(row)
    return rows


def predictor_update(state, taken):
    """Saturating two-bit direction counter: 0/1 predict NT, 2/3 predict T."""
    if type(state) is not int or not 0 <= state <= 3 or type(taken) is not bool:
        raise ValueError('expected counter 0..3 and Boolean outcome')
    return min(3, state + 1) if taken else max(0, state - 1)


def processor_design(spec, english=False):
    kind = spec['archetype']
    req = set(spec.get('metadata', {}).get('render_requirements', []))
    if kind not in PROCESSOR_ARCHETYPES:
        raise ValueError('Unsupported processor archetype')
    caption = 'Illustrative structure; not measured timing' if english else '结构示例；非实测时序'
    layout = 'flow'
    if kind == 'timing_state':
        labels = ['D input', 'Enable', 'Clock edge', 'Q state']
        caption = 'Q updates on an enabled edge; stable between edges' if english else '使能时在时钟边沿更新Q；边沿之间保持'
    elif kind == 'control_fsm':
        labels = ['State', 'Input', 'Next state', 'Outputs']
        if 'output_from_state_only' in req:
            labels = ['State', 'Next state', 'State outputs']
        elif 'output_from_state_and_input' in req:
            labels = ['State + input', 'Next state', 'Combined outputs']
    elif kind == 'control_table':
        layout = 'table'
        labels = [['Input', 'Control', 'Target'], ['opcode', 'decode', 'datapath'], ['enable', '0 / 1', 'hold / write']]
        if '00_add' in req or 'aluop' in req:
            labels = [['ALUOp', 'Function', 'Operation'], ['00', '-', 'add'], ['01', '-', 'subtract'], ['10', 'funct', 'decode']]
        elif 'EX_group' in req:
            labels = [['Stage', 'Control group'], ['EX', 'ALU / operands'], ['MEM', 'read / write'], ['WB', 'destination / enable']]
    elif kind == 'microcode_flow':
        labels = ['Opcode', 'Dispatch', 'Control ROM', 'Control bits']
    elif kind == 'pipeline_timeline':
        layout = 'table'
        labels = [['Instruction'] + [str(i) for i in range(1, 8)]]
        labels += [[f'I{i+1}'] + row for i, row in enumerate(pipeline_rows(
            stall=bool(req & {'freeze', 'repeat_ID', 'PC_hold'}),
            flush=bool(req & {'wrong_path', 'faulting_instruction', 'younger_flushed'})))]
    elif kind == 'hazard_dependency':
        labels = ['Producer', 'Result available', 'Consumer']
        if 'resource_conflict' in req:
            labels = ['Request A', 'Shared resource', 'Request B waits']
        elif 'late_data' in req:
            labels = ['Load MEM', 'Wait / bubble', 'Consumer EX']
        elif 'name_reuse' in req:
            labels = ['Name dependency', 'Rename', 'Independent names']
        elif req & {'bypass', 'forward'}:
            labels = ['Producer result', 'Bypass', 'Consumer operand']
    elif kind == 'branch_predictor':
        if 'four_states' in req or 'saturating_counter' in req:
            labels = ['00: strong NT', '01: weak NT', '10: weak T', '11: strong T']
            caption = 'Taken increments; not-taken decrements; endpoints saturate' if english else '实际跳转则递增；不跳转则递减；端点饱和'
        elif 'last_outcome' in req:
            labels = ['Previous outcome', 'Predict T / NT', 'Actual outcome', 'Update bit']
        elif req & {'chooser', 'selector'}:
            labels = ['Local history', 'Global history', 'Chooser', 'Prediction']
        else:
            labels = ['Branch PC', 'Prediction', 'Resolve', 'Recover if wrong']
    elif kind == 'issue_bundle':
        layout = 'table'
        labels = [['Cycle', 'Slot 0', 'Slot 1', 'Slot 2'], ['1', 'I1', 'I2', '-'], ['2', 'I3', '-', 'I4']]
        caption = 'Example slots; eligibility depends on dependencies and resources' if english else '发射槽示例；能否发射取决于依赖及资源'
    else:
        labels = ['Issue in order', 'Ready operands', 'Execute when ready', 'Commit in order']
        if req & {'rollback', 'checkpoint_or_buffer'}:
            labels = ['Checkpoint', 'Speculate', 'Validate', 'Commit / rollback']
        elif 'architectural_register' in req or 'latest_mapping' in req:
            labels = ['Architectural name', 'Rename map', 'Physical register', 'Restore checkpoint']
    return {'layout': layout, 'labels': labels, 'caption': caption}


SOURCE = 'PROCESSOR_ARCHETYPES = ' + repr(set(PROCESSOR_ARCHETYPES)) + '\n'
SOURCE += inspect.getsource(pipeline_rows) + '\n' + inspect.getsource(predictor_update) + '\n' + inspect.getsource(processor_design)
SOURCE += r'''

def make_processor_node(spec):
    design = processor_design(spec, ENGLISH)
    w, h = float(spec.get('width', 4.8)), float(spec.get('height', 2.8))
    title = fitted_text(spec.get('name', ''), 22, w*.94, h*.16).move_to([0,h*.41,0])
    caption = fitted_text(design['caption'], 12, w*.94, h*.12).move_to([0,-h*.43,0])
    parts, links = VGroup(), VGroup()
    rows = design['labels'] if design['layout'] == 'table' else [design['labels']]
    columns = max(len(row) for row in rows)
    cw, ch = w*.94/columns, h*.56/len(rows)
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            cell = RoundedRectangle(width=cw*.92, height=ch*.84, corner_radius=min(.05,ch*.1))
            cell.set_stroke(TEAL_C,width=1.3).set_fill(TEAL_C,opacity=.12)
            cell.move_to([-w*.47+(j+.5)*cw, h*.28-(i+.5)*ch,0])
            text = fitted_text(str(value), 15, cell.width*.86, cell.height*.7).move_to(cell)
            parts.add(VGroup(cell,text))
    if design['layout'] == 'flow':
        for a,b in zip(parts, list(parts)[1:]):
            links.add(Arrow(a.get_right(),b.get_left(),buff=.01,stroke_width=1.4,max_tip_length_to_length_ratio=.2))
    result = VGroup(title,links,parts,caption)
    result.visual_parts = parts
    return result
'''
