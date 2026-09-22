import ast
import unittest
from unittest.mock import Mock
from rendering.manim.memory_behavior import (
    cache_example, translate_address, memory_trace_frames, memory_behavior_design,
    MEMORY_TRACE_PATTERNS, MEMORY_BEHAVIOR_ARCHETYPES, SOURCE)
from rendering.manim.script_generator import _SCRIPT_TEMPLATE
from representation.animation_grammar import TEMPLATES


class MemoryBehaviorTests(unittest.TestCase):
    def test_cache_tags_hits_and_dirty_writeback(self):
        frames = cache_example(writes=(0,))
        self.assertEqual([f['hit'] for f in frames], [False, False, True, False])
        self.assertTrue(frames[-1]['writeback'])
        self.assertEqual(frames[0]['cache'][0][0]['tag'], 0)
        self.assertEqual(frames[-1]['cache'][0][0]['tag'], 1)
        self.assertTrue(frames[0]['cache'][0][0]['dirty'])
        self.assertFalse(frames[-1]['cache'][0][0]['dirty'])

    def test_lru_evicts_least_recent_way(self):
        frames = cache_example((0, 64, 0, 128), ways=2)
        self.assertEqual(frames[-1]['way'], 1)
        self.assertEqual([e['tag'] for e in frames[-1]['cache'][0]], [0, 2])

    def test_write_through_never_leaves_dirty_line(self):
        frames = cache_example((0, 0), writes=(0, 1), write_back=False)
        self.assertTrue(all(f['memory_write'] for f in frames))
        self.assertTrue(all(not f['cache'][0][0]['dirty'] for f in frames))

    def test_translation_preserves_offset_and_missing_page_faults(self):
        state = translate_address(0x1234, {1: 9})
        self.assertEqual(state['physical_address'], 0x9234)
        self.assertEqual(state['offset'], 0x234)
        self.assertTrue(translate_address(0x1234, {})['page_fault'])
        with self.assertRaises(ValueError): cache_example(sets=3)
        with self.assertRaises(ValueError): translate_address(-1, {})

    def test_all_patterns_have_distinct_frames_and_runtime_dispatch(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', repr('{}')))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'animate_beat')
        effect = Mock()
        env = {'animate_memory_trace': effect}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'dispatch', 'exec'), env)
        for pattern in MEMORY_TRACE_PATTERNS:
            self.assertEqual(TEMPLATES[pattern].template_id, 'memory_trace')
            frames = memory_trace_frames(pattern)
            self.assertEqual(len(frames), 4)
            self.assertNotEqual(frames[0], frames[-1])
            for frame in frames:
                self.assertLess(frame['active_row'], len(frame['rows']))
            env['animate_beat'](None, {}, {}, {'template_id': 'memory_trace', 'pattern_id': pattern})
        self.assertEqual(effect.call_count, len(MEMORY_TRACE_PATTERNS))
        for kind in MEMORY_BEHAVIOR_ARCHETYPES:
            self.assertTrue(memory_behavior_design({'archetype': kind})['rows'])
        compile(SOURCE, 'memory_behavior', 'exec')
