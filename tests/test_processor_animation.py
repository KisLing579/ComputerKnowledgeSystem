import ast
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock
from rendering.manim.processor_nodes import PROCESSOR_ARCHETYPES, SOURCE, pipeline_rows, predictor_update, processor_design
from rendering.manim.processor_effects import PROCESSOR_TRACES, SOURCE as EFFECTS, processor_trace
from rendering.manim.script_generator import _SCRIPT_TEMPLATE
from representation.animation_grammar import TEMPLATES
from representation.registry import RepresentationRegistry
from rendering.layout.engine import LayoutEngine


class ProcessorAnimationTests(unittest.TestCase):
    def test_counter_saturates_and_has_hysteresis(self):
        self.assertEqual(predictor_update(3,True),3)
        self.assertEqual(predictor_update(0,False),0)
        state=predictor_update(3,False)
        self.assertGreaterEqual(state,2)
        self.assertLess(predictor_update(state,False),2)
        with self.assertRaises(ValueError): predictor_update(4,True)

    def test_pipeline_overlap_stall_and_flush(self):
        rows=pipeline_rows()
        self.assertEqual(rows[0],['IF','ID','EX','MEM','WB','',''])
        self.assertEqual(rows[2][2:7],['IF','ID','EX','MEM','WB'])
        stalled=pipeline_rows(stall=True)
        self.assertEqual(stalled[1][3],'hold ID')
        self.assertEqual(stalled[2][3],'hold IF')
        self.assertEqual(stalled[2][4],'ID')
        self.assertIn('flush',pipeline_rows(flush=True)[1])

    def test_every_profile_and_trace_has_a_design(self):
        registry=RepresentationRegistry('data/computer_core_kg_ch1_ch9_master_v0_6_dependencies.xlsx')
        profiles=[p for p in registry.profiles.values() if p.visual_archetype in PROCESSOR_ARCHETYPES]
        self.assertGreater(len(profiles),100)
        for p in profiles:
            design=processor_design({'archetype':p.visual_archetype,'metadata':{'render_requirements':p.render_requirements}})
            self.assertTrue(design['labels'])
        for pattern in PROCESSOR_TRACES:
            template=TEMPLATES[pattern]
            self.assertEqual(template.template_id,'processor_trace')
            self.assertEqual([p.parameters['trace_frame'] for p in template.phases],[0,1,2,3])
            frames=processor_trace(pattern)
            self.assertEqual(len(frames),4)
            self.assertNotEqual(frames[0],frames[-1])
        compile(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__',repr('{}'))+'\n'+SOURCE+'\n'+EFFECTS,'processor','exec')

    def test_renderer_dispatches_trace(self):
        tree=ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__',repr('{}')))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='animate_beat')
        effect=Mock(); env={'animate_processor_trace':effect}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'dispatch','exec'),env)
        env['animate_beat'](None,{}, {}, {'template_id':'processor_trace'})
        effect.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec('manim'),'Manim optional')
    def test_bilingual_geometry_and_runtime_frames(self):
        from manim import tempconfig, Text
        registry=RepresentationRegistry('data/computer_core_kg_ch1_ch9_master_v0_6_dependencies.xlsx')
        with tempconfig({'media_dir':'out_archetypes/batch05/test_media'}):
            for language in ('en','zh'):
                env={}
                exec(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__',repr(json.dumps({'metadata':{'language':language}})))+'\n'+SOURCE+'\n'+EFFECTS,env)
                for kind in PROCESSOR_ARCHETYPES:
                    w,h=LayoutEngine.BASE_SIZE[kind]
                    obj=env['make_node']({'archetype':kind,'name':'Processor execution structure','width':w,'height':h})
                    self.assertLessEqual(obj.width,w+.081)
                    self.assertLessEqual(obj.height,h+.081)
                for pattern in PROCESSOR_TRACES:
                    scene=Mock(); scene.processor_traces={}; scene.local_links=[]
                    for i in range(4):
                        env['animate_processor_trace'](scene,{'scene_id':pattern,'nodes':[]},{},
                            {'pattern_id':pattern,'parameters':{'trace_frame':i}})
                    self.assertEqual(scene.play.call_count,4)
