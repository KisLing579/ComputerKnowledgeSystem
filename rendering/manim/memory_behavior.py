"""Deterministic teaching examples for cache, banking and address translation."""
import inspect

MEMORY_BEHAVIOR_ARCHETYPES = frozenset({
    'cache_map', 'banked_memory', 'locality_trace', 'access_pattern',
    'miss_taxonomy', 'protection_boundary', 'process_switch', 'queue_flow'})


def cache_example(addresses=(0, 16, 0, 64), *, sets=4, ways=1, block_bytes=16,
                  writes=(), write_back=True):
    """Write-allocate LRU example; each step records a fresh state snapshot."""
    if any(type(n) is not int or n < 1 or n & (n-1) for n in (sets, ways, block_bytes)):
        raise ValueError('sets, ways and block size must be positive powers of two')
    if any(type(a) is not int or a < 0 for a in addresses):
        raise ValueError('addresses must be nonnegative integers')
    if any(type(i) is not int or not 0 <= i < len(addresses) for i in writes):
        raise ValueError('write indices must reference accesses')
    cache = [[{'valid': False, 'tag': None, 'dirty': False, 'last': -1}
              for _ in range(ways)] for _ in range(sets)]
    frames = []
    for clock, address in enumerate(addresses):
        block, offset = divmod(address, block_bytes)
        tag, index = divmod(block, sets)
        hit = next((i for i, entry in enumerate(cache[index]) if entry['valid'] and entry['tag'] == tag), None)
        way = hit if hit is not None else min(range(ways), key=lambda i: (cache[index][i]['valid'], cache[index][i]['last']))
        entry = cache[index][way]
        writeback = hit is None and entry['valid'] and entry['dirty']
        entry.update(valid=True, tag=tag, last=clock,
                     dirty=(entry['dirty'] if hit is not None else False) or (clock in writes and write_back))
        frames.append({'address': address, 'tag': tag, 'index': index, 'offset': offset,
                       'way': way, 'hit': hit is not None, 'writeback': writeback,
                       'memory_write': writeback or (clock in writes and not write_back),
                       'cache': [[dict(x) for x in row] for row in cache]})
    return frames


def translate_address(address, page_table, *, page_bytes=4096):
    if type(address) is not int or address < 0 or type(page_bytes) is not int or page_bytes < 1 or page_bytes & (page_bytes-1):
        raise ValueError('nonnegative address and power-of-two page size required')
    vpn, offset = divmod(address, page_bytes)
    ppn = page_table.get(vpn)
    if ppn is not None and (type(ppn) is not int or ppn < 0):
        raise ValueError('physical page must be a nonnegative integer')
    return {'vpn': vpn, 'offset': offset, 'ppn': ppn, 'page_fault': ppn is None,
            'physical_address': None if ppn is None else ppn*page_bytes+offset}


def memory_behavior_design(spec, english=False):
    kind = spec['archetype']
    req = set(spec.get('metadata', {}).get('render_requirements', []))
    caption = 'Illustrative example; not measured timing' if english else '机制示例；非实测时序'
    if kind == 'cache_map':
        rows = [['Block', 'Set (block mod 4)'], ['0 / 4 / 8', '0'], ['1 / 5 / 9', '1'], ['2 / 6 / 10', '2'], ['3 / 7 / 11', '3']]
        caption = 'Example: four sets; tags distinguish blocks' if english else '示例：四个组；标记区分映射到同组的块'
    elif kind == 'banked_memory':
        rows = [['Word address', 'Bank', 'Row'], ['0', '0', '0'], ['1', '1', '0'], ['4', '0', '1'], ['5', '1', '1']]
        caption = 'Example: bank = word address mod 4' if english else '示例：存储体编号＝字地址模4'
    elif kind in ('locality_trace', 'access_pattern'):
        temporal = bool(req & {'temporal', 'temporal_locality', 'reuse', 'repeat'})
        rows = [['Access', 'Address'], ['1', 'A'], ['2', 'B' if temporal else 'A+4'], ['3', 'A' if temporal else 'A+8'], ['4', 'B' if temporal else 'A+12']]
        caption = ('Repeated addresses: temporal locality' if temporal else 'Nearby addresses: spatial locality') if english else ('重复访问：时间局部性' if temporal else '相邻访问：空间局部性')
    elif kind == 'miss_taxonomy':
        rows = [['Test after a miss', 'Class'], ['First block access?', 'Compulsory'], ['Same-capacity fully associative also misses?', 'Capacity'], ['Otherwise', 'Conflict']]
    elif kind == 'protection_boundary':
        rows = [['User mode', 'Kernel mode'], ['Restricted access', 'Privileged access'], ['Trap / system call', 'Validate + handle'], ['Resume user', 'Return from trap']]
    elif kind == 'process_switch':
        rows = [['Process A', 'OS', 'Process B'], ['Running', 'Interrupt', 'Saved'], ['Save PC + registers', 'Schedule', 'Restore PC + registers'], ['Saved', 'Return', 'Running']]
    elif kind == 'queue_flow':
        rows = [['Arrival', 'FIFO waiting', 'Service'], ['New request', 'Tail', ''], ['', 'Head request', 'Dispatch'], ['', 'Next request', 'Complete']]
    else:
        raise ValueError('Unsupported memory behavior archetype')
    return {'rows': rows, 'caption': caption}


MEMORY_TRACE_PATTERNS = frozenset({
    'CACHE_ADDRESS_DECODE', 'CACHE_LOOKUP_HIT_MISS', 'CACHE_MISS_REFILL',
    'CACHE_WRITE_POLICY', 'ASSOCIATIVITY_LOOKUP', 'REPLACEMENT_SELECT',
    'ADDRESS_TRANSLATE', 'TLB_LOOKUP_REFILL', 'PAGE_FAULT_SWAP',
    'BANK_INTERLEAVE_TRANSFER', 'LOCALITY_REUSE_TRACE', 'HIERARCHY_DESCENT',
    'PROTECTION_MODE_SWITCH', 'MISS_3C_CLASSIFY'})


def memory_trace_frames(pattern):
    if pattern not in MEMORY_TRACE_PATTERNS:
        raise ValueError('Unsupported memory trace')
    if pattern in {'CACHE_LOOKUP_HIT_MISS', 'CACHE_MISS_REFILL', 'CACHE_WRITE_POLICY', 'ASSOCIATIVITY_LOOKUP', 'REPLACEMENT_SELECT', 'LOCALITY_REUSE_TRACE'}:
        associative = pattern in {'ASSOCIATIVITY_LOOKUP', 'REPLACEMENT_SELECT'}
        states = cache_example((0, 64, 0, 128) if associative else (0,16,0,64),
                               ways=2 if associative else 1, writes=(0,) if pattern == 'CACHE_WRITE_POLICY' else ())
        frames = []
        for state in states:
            rows = [['Set / way', 'Valid', 'Tag', 'Dirty']]
            rows += [[f'{i}/{j}', str(int(e['valid'])), '-' if e['tag'] is None else str(e['tag']), str(int(e['dirty']))]
                     for i,row in enumerate(state['cache']) for j,e in enumerate(row)]
            note = f"Example: 4 sets, {2 if associative else 1} way(s), 16B blocks. Address {state['address']}: {'HIT' if state['hit'] else 'MISS + refill'}"
            if state['writeback']: note += '; dirty victim written back first'
            frames.append({'rows':rows, 'caption':note, 'active_row':1+state['index']*(2 if associative else 1)+state['way']})
        return frames
    if pattern in {'CACHE_ADDRESS_DECODE', 'ADDRESS_TRANSLATE'}:
        if pattern == 'CACHE_ADDRESS_DECODE':
            address=0x123
            state=cache_example((address,))[0]
            rows=[['Address',hex(address)],['Tag',str(state['tag'])],['Set index',str(state['index'])],['Byte offset',str(state['offset'])]]
            caption='Example: four sets, 16-byte blocks'
        else:
            state=translate_address(0x1234,{1:9})
            rows=[['VA','0x1234'],['VPN / offset',f"{state['vpn']} / {hex(state['offset'])}"],['PPN',str(state['ppn'])],['PA',hex(state['physical_address'])]]
            caption='Example: 4 KiB pages; offset unchanged'
        return [{'rows':rows,'active_row':i,'caption':caption} for i in range(4)]
    sequences = {
        'TLB_LOOKUP_REFILL': ['VPN lookup: TLB miss', 'Page table: present PTE', 'Refill VPN to PPN mapping', 'Retry translation; preserve offset'],
        'PAGE_FAULT_SWAP': ['PTE not present: page fault', 'OS selects frame; dirty victim needs writeback', 'Read page; update PTE and translation state', 'Restart faulting instruction'],
        'BANK_INTERLEAVE_TRANSFER': ['Word 0 -> bank 0', 'Word 1 -> bank 1', 'Word 2 -> bank 2', 'Word 3 -> bank 3'],
        'HIERARCHY_DESCENT': ['Probe L1: miss', 'Probe L2: miss', 'Read memory', 'Refill cache; resume request'],
        'PROTECTION_MODE_SWITCH': ['User instruction', 'Trap / system call', 'Kernel validates and handles request', 'Return to user mode'],
        'MISS_3C_CLASSIFY': ['Observe a cache miss', 'First reference? compulsory', 'Same-capacity fully associative miss? capacity', 'Otherwise: conflict'],
    }
    rows=[[str(i+1),s] for i,s in enumerate(sequences[pattern])]
    return [{'rows':rows,'active_row':i,'caption':'Illustrative mechanism; not measured timing'} for i in range(4)]


SOURCE = 'MEMORY_BEHAVIOR_ARCHETYPES = ' + repr(set(MEMORY_BEHAVIOR_ARCHETYPES)) + '\n'
SOURCE += 'MEMORY_TRACE_PATTERNS = ' + repr(set(MEMORY_TRACE_PATTERNS)) + '\n'
for function in (cache_example, translate_address, memory_behavior_design, memory_trace_frames):
    SOURCE += inspect.getsource(function) + '\n'
SOURCE += r'''

def memory_table_panel(rows, title, caption, w, h, active=-1):
    parts = VGroup()
    columns = max(len(row) for row in rows)
    cw,ch = w*.94/columns,h*.64/len(rows)
    for i,row in enumerate(rows):
        for j,text in enumerate(row):
            cell = Rectangle(width=cw*.96,height=ch*.94).set_stroke(TEAL_C,width=1)
            cell.set_fill(YELLOW if i==active else TEAL_C,opacity=.23 if i==active else .08)
            cell.move_to([-w*.47+(j+.5)*cw,h*.30-(i+.5)*ch,0])
            parts.add(VGroup(cell,fitted_text(str(text),14,cell.width*.87,cell.height*.7).move_to(cell)))
    header = fitted_text(title,20,w*.94,h*.13).move_to([0,h*.42,0])
    note = fitted_text(caption,12,w*.94,h*.12).move_to([0,-h*.43,0])
    panel = VGroup(header,parts,note)
    panel.visual_parts = parts
    return panel

def make_memory_behavior_node(spec):
    d=memory_behavior_design(spec,ENGLISH)
    return memory_table_panel(d['rows'],spec.get('name',''),d['caption'],
                              float(spec.get('width',4.8)),float(spec.get('height',3.0)))

def animate_memory_trace(scene,spec,objects,beat):
    pattern=beat['pattern_id']
    frames=memory_trace_frames(pattern)
    index=int(beat.get('parameters',{}).get('trace_frame',0))
    if not 0 <= index < len(frames): raise ValueError('Memory trace frame out of range')
    ids=beat.get('node_ids',[])
    for nid in ids: ensure_node(scene,spec,objects,nid)
    if not hasattr(scene,'memory_traces'): scene.memory_traces={}
    key=(spec.get('scene_id'),pattern,tuple(beat.get('relation_ids',[])))
    frame=frames[index]
    specs=[n for n in spec.get('nodes',[]) if n.get('knowledge_node_id') in ids]
    cx=max(-3.1,min(3.1,sum(float(n.get('x',0)) for n in specs)/max(1,len(specs))))
    table=memory_table_panel(frame['rows'],pattern.replace('_',' '),frame['caption'],4.6,3.0,frame['active_row'])
    background=RoundedRectangle(width=4.75,height=3.15,corner_radius=.1).set_fill(config.background_color,opacity=1)
    panel=VGroup(background,table).move_to([cx,0,0])
    previous=scene.memory_traces.get(key)
    if previous is None:
        scene.play(FadeIn(panel),run_time=float(beat.get('duration',.8)))
        scene.memory_traces[key]=panel
        remember_local_link(scene,ids,panel)
    else:
        scene.play(Transform(previous,panel),run_time=float(beat.get('duration',.8)))
'''
