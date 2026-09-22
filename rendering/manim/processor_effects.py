"""Explicit illustrative processor traces, independent of graph fact generation."""
import inspect

# Each pattern has a distinct mechanism trace, not a generic relation arrow.
PROCESSOR_TRACES = {
 'CLOCK_EDGE_UPDATE': [['CLK=0', 'D=1', 'Q=0'], ['CLK rising', 'D=1', 'enable=1'], ['CLK=1', 'Q=1', 'latched'], ['D changes', 'no edge', 'Q holds']],
 'CONTROL_ASSERT': [['opcode', 'decode', 'control=0'], ['opcode matched', 'decode', 'control=1'], ['target enabled', 'operation', 'state update'], ['deassert', 'control=0', 'hold']],
 'FSM_TRANSITION': [['current state', 'input', 'outputs'], ['transition condition', 'next state selected', 'clock pending'], ['clock edge', 'state updated', 'new outputs'], ['new state', 'wait for input', 'stable']],
 'MICROCODE_DISPATCH': [['opcode', 'dispatch address', 'control ROM'], ['micro-PC', 'ROM read', 'microinstruction'], ['control fields', 'datapath action', 'next address'], ['next micro-PC', 'next microinstruction', 'continue / finish']],
 'DATAPATH_TRACE': [['source register', 'operand', 'ALU'], ['operand read', 'ALU input', 'operation'], ['ALU result', 'destination select', 'write enable'], ['writeback', 'destination register', 'result stored']],
 'RESOURCE_REUSE_CYCLE': [['cycle 1', 'ALU: PC increment', 'temporary state'], ['cycle 2', 'ALU: address', 'temporary state'], ['cycle 3', 'memory access', 'temporary state'], ['cycle 4', 'writeback', 'resource released']],
 'PIPELINE_OVERLAP': None,
 'FORWARDING_BYPASS': [['producer EX', 'result ready', 'consumer needs operand'], ['EX/MEM result', 'bypass selected', 'consumer EX input'], ['consumer executes', 'producer continues', 'no wait for WB'], ['producer WB', 'consumer advances', 'dependency respected']],
 'STALL_BUBBLE_INSERT': [['load in EX', 'consumer in ID', 'data not ready'], ['PC holds', 'IF/ID holds', 'EX bubble'], ['load data ready', 'consumer resumes', 'forward operand'], ['normal advance', 'bubble drains', 'one illustrated stall']],
 'PIPELINE_FLUSH': [['branch unresolved', 'speculative fetch', 'younger instructions'], ['wrong path found', 'redirect PC', 'invalidate younger'], ['wrong-path controls=0', 'no architectural write', 'refetch'], ['correct path', 'pipeline refills', 'resume']],
 'BRANCH_PREDICT_RECOVER': [['PC', 'predict taken', 'fetch predicted target'], ['branch executes', 'actual not taken', 'misprediction'], ['discard wrong path', 'redirect fall-through', 'update predictor'], ['correct fetch', 'refill', 'resume']],
 'MULTI_ISSUE_PACK': [['I1 ready', 'I2 ready', 'I3 depends on I1'], ['slot 0: I1', 'slot 1: I2', 'I3 waits'], ['issue packet', 'parallel execution', 'respect dependencies'], ['I1 result ready', 'I3 eligible', 'next packet']],
 'OOO_SCHEDULE_COMMIT': [['I1 waiting', 'I2 independent', 'ROB: I1 then I2'], ['I2 executes first', 'result buffered', 'I2 cannot retire yet'], ['I1 completes', 'retire I1', 'I2 now oldest'], ['retire I2', 'program-order state', 'precise boundary']],
 'SPECULATE_VALIDATE_ROLLBACK': [['checkpoint', 'predict', 'speculate'], ['temporary results', 'not committed', 'validate'], ['validation fails', 'discard results', 'restore checkpoint'], ['restart correct path', 're-execute', 'commit after validation']],
}


def processor_trace(pattern):
    if pattern == 'PIPELINE_OVERLAP':
        from .processor_nodes import pipeline_rows
        rows = pipeline_rows()
        return [[f'I{i+1}: ' + ' '.join(v or '-' for v in row[:cycle]) for i,row in enumerate(rows)] for cycle in (1,3,5,7)]
    if pattern not in PROCESSOR_TRACES:
        raise ValueError('Unsupported processor trace')
    return [list(frame) for frame in PROCESSOR_TRACES[pattern]]


SOURCE = 'PROCESSOR_TRACES = ' + repr(PROCESSOR_TRACES) + '\n'
SOURCE += inspect.getsource(processor_trace).replace('        from .processor_nodes import pipeline_rows\n', '')
SOURCE += r'''

def animate_processor_trace(scene, spec, objects, beat):
    pattern = beat.get('pattern_id')
    frames = processor_trace(pattern)
    phase = int(beat.get('parameters', {}).get('trace_frame', 0))
    if not 0 <= phase < len(frames):
        raise ValueError('Processor trace frame out of range')
    ids = list(beat.get('node_ids', []))
    for nid in ids:
        ensure_node(scene, spec, objects, nid)
    if not hasattr(scene, 'processor_traces'):
        scene.processor_traces = {}
    key = (spec.get('scene_id'), pattern, tuple(beat.get('relation_ids', [])))
    node_specs = [n for n in spec.get('nodes', []) if n.get('knowledge_node_id') in ids]
    cx = sum(float(n.get('x',0)) for n in node_specs)/max(1,len(node_specs))
    cx = max(-3.1,min(3.1,cx))
    rows = frames[phase]
    w,h = 4.5,2.4
    backing = RoundedRectangle(width=w,height=h,corner_radius=.12).set_fill(config.background_color,opacity=1)
    backing.set_stroke(BLUE_C,width=1.5)
    header = fitted_text(pattern.replace('_',' '),16,w*.9,.3).move_to([0,.88,0])
    entries = VGroup()
    for i,text in enumerate(rows):
        box = RoundedRectangle(width=w*.9,height=.43,corner_radius=.05).set_stroke(TEAL_C,width=1)
        box.move_to([0,.4-i*.48,0])
        entries.add(VGroup(box,fitted_text(text,16,box.width*.9,box.height*.7).move_to(box)))
    note = fitted_text('Illustrative execution example' if ENGLISH else '执行过程示例',12,w*.9,.2).move_to([0,-1.02,0])
    panel = VGroup(backing,header,entries,note).move_to([cx,0,0])
    old = scene.processor_traces.get(key)
    if old is None:
        scene.play(FadeIn(panel),run_time=float(beat.get('duration',.7)))
        scene.processor_traces[key] = panel
        remember_local_link(scene, ids, panel)
    else:
        scene.play(Transform(old,panel),run_time=float(beat.get('duration',.7)))
'''
