import ast
import unittest
from types import SimpleNamespace

from rendering.manim.script_generator import _SCRIPT_TEMPLATE


class Object:
    def __init__(self, text="", **kwargs):
        self.text = text
        self.width = 1
        self.glyph = object()

    def get_family(self):
        return [self, self.glyph]

    def to_edge(self, *args, **kwargs):
        return self


class Scene:
    def __init__(self):
        self.visible = set()

    def add(self, obj):
        self.visible.update(obj.get_family())

    def remove(self, *objects):
        self.visible.difference_update(objects)

    def play(self, animation, **kwargs):
        kind, obj = animation
        if kind == "in":
            # Old component glyphs must be gone before new ones appear.
            assert not self.visible
            self.add(obj)


class RenderLifecycleTests(unittest.TestCase):
    def test_revisit_returns_before_original_animation_dispatch(self):
        from unittest.mock import Mock
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'animate_beat')
        objects = {}
        def ensure(scene, spec, current, nid, **kwargs):
            self.assertFalse(kwargs['fade'])
            current[nid] = nid
        env = {'ensure_node': ensure, 'Indicate': lambda obj, **kwargs: obj}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'revisit', 'exec'), env)
        scene = Mock()
        env['animate_beat'](scene, {'layout': 'persistent_subgraph', 'relations': []}, objects,
                            {'template_id': 'evidence_revisit', 'node_ids': ['A'], 'relation_ids': []})
        scene.play.assert_called_once_with('A', run_time=1.2)
        self.assertEqual(objects, {'A': 'A'})

    def test_scene_carry_is_capped_and_only_uses_the_next_scene(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'next_scene_carry_nodes')
        env = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'carry', 'exec'), env)
        carry = env['next_scene_carry_nodes']
        scenes = [{'scene_role': 'subquestion_intro'},
                  {'beats': [{'node_ids': ['new', 'B', 'A', 'C']}]},
                  {'beats': [{'node_ids': ['later']}]}]
        visible = {'A', 'B', 'C', 'old', 'later'}
        self.assertEqual(carry(scenes, 0, visible), {'B', 'A'})
        self.assertEqual(carry(scenes, 0, {'later'}), set())
        self.assertEqual(carry(scenes, 3, visible), set())
        self.assertEqual(carry([{'scene_role': 'summary'}], 0, visible), set())
        stage = {'relations': [{'relation_id': 'r', 'source_node_id': 'A',
                               'target_node_id': 'B', 'mediator_node_id': 'C'}]}
        scenes = [{'beats': [{'beat_id': 'b', 'relation_ids': ['r']}],
                   'metadata': {'local_scene': {'metadata': {'local_stages': {'b': stage}}}}}]
        self.assertEqual(carry(scenes, 0, visible), {'A', 'B'})

    def test_question_cards_and_scene_heading_are_not_drawn(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace('__PLAN_JSON__', "'{}'"))
        construct = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                         and n.name == 'GeneratedExplanation').body[0]
        text_calls = [ast.unparse(n) for n in ast.walk(construct) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == 'Text']
        self.assertFalse(any('scene_spec' in call for call in text_calls))

    def test_lookahead_crosses_subquestions_and_stops_after_two_beats(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "upcoming_local_nodes")
        env = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "lookahead", "exec"), env)
        def local(beats, relations=()):
            return {"beats": beats, "metadata": {"local_scene": {"relations": relations}}}
        scenes = [local([{"node_ids": ["old"]}]),
                  local([{"node_ids": ["A"]}]),
                  local([{"node_ids": ["B"], "relation_ids": ["R"]},
                         {"node_ids": ["too_late"]}],
                        [{"relation_id": "R", "source_node_id": "B",
                          "target_node_id": "C", "mediator_node_id": "M"}])]
        lookahead = env["upcoming_local_nodes"]
        self.assertEqual(lookahead(scenes, 1), {"A", "B", "C", "M"})
        self.assertEqual(lookahead(scenes, 2, 1), {"too_late"})
        self.assertEqual(lookahead(scenes, 3), set())
        scenes.insert(2, {"scene_role": "summary", "beats": [{"node_ids": ["B"]}]})
        self.assertEqual(lookahead(scenes, 1), {"A"})

    def test_lookahead_uses_per_beat_local_relations(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "upcoming_local_nodes")
        env = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "lookahead", "exec"), env)
        stage = {"relations": [{"relation_id": "R", "source_node_id": "A", "target_node_id": "B"}]}
        scenes = [{"beats": [{"beat_id": "b", "relation_ids": ["R"]}],
                   "metadata": {"local_scene": {"metadata": {"local_stages": {"b": stage}}}}}]
        self.assertEqual(env["upcoming_local_nodes"](scenes, 0), {"A", "B"})

    def test_endpoint_change_removes_link_and_label_but_keeps_other_edges(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name in {"remember_local_link", "invalidate_local_links"}]
        env = {}
        exec(compile(ast.Module(body=helpers, type_ignores=[]), "links", "exec"), env)
        scene = Scene()
        edge, label, other = Object(), Object(), Object()
        for obj in (edge, label, other): scene.add(obj)
        env["remember_local_link"](scene, ["A", "B"], edge, label)
        env["remember_local_link"](scene, ["C", "D"], other)
        env["invalidate_local_links"](scene, {"B"})
        self.assertEqual(scene.visible, set(other.get_family()))
        self.assertEqual(len(scene.local_links), 1)
        env["invalidate_local_links"](scene, {"C", "D"})
        self.assertFalse(scene.visible)

    def test_local_reveal_mirrors_only_that_node_in_same_play(self):
        from unittest.mock import Mock
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "ensure_node")
        env = {"make_node": lambda spec: object(), "FadeIn": lambda obj: obj,
               "scene_spec_by_id": lambda spec, nid: {"id": nid} if nid in spec else None}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "reveal", "exec"), env)
        graph, local = {}, {}
        scene = Mock(graph_mirror=(["A", "B"], graph))
        env["ensure_node"](scene, ["A", "B"], local, "A")
        self.assertEqual(set(graph), {"A"})
        self.assertEqual(set(local), {"A"})
        self.assertEqual(len(scene.play.call_args.args), 2)
        env["ensure_node"](scene, ["A", "B"], local, "A")
        scene.play.assert_called_once()

    def test_panel_layout_maps_final_and_initial_positions_without_mutation(self):
        import copy
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "panel_spec")
        env = {"copy": copy}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "panel", "exec"), env)
        original = {"nodes": [{"x": 2, "y": 1, "scale": 1,
                               "metadata": {"initial_x": -2, "initial_y": 0}}]}
        right = env["panel_spec"](original, 3.2)
        left = env["panel_spec"](original, -3.3)
        self.assertGreater(right["nodes"][0]["metadata"]["initial_x"], 0)
        self.assertLess(left["nodes"][0]["x"], 0)
        self.assertEqual(original["nodes"][0]["x"], 2)

    def test_pulse_uses_continuous_path_and_handles_coincident_nodes(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pulse_between")
        calls = []
        class Path:
            def __init__(self, start, end, **kwargs):
                self.start, self.end = start, end
            def get_start(self): return self.start
            def get_end(self): return self.end
        class Dashed(Path): pass
        def move(dot, path):
            self.assertIs(type(path), Path)
            calls.append(path)
        env = dict(Line=Path, Arrow=Path, DashedLine=Dashed,
                   Dot=lambda **kw: SimpleNamespace(move_to=lambda p: object()),
                   Create=lambda x: x, FadeOut=lambda x: x,
                   MoveAlongPath=move, Indicate=lambda x: calls.append("indicate"))
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "pulse", "exec"), env)
        scene = SimpleNamespace(play=lambda *a, **kw: None, add=lambda x: None)
        a = SimpleNamespace(get_center=lambda: (0, 0, 0))
        b = SimpleNamespace(get_center=lambda: (0.1, 0, 0))
        for dashed in (False, True):
            env["pulse_between"](scene, a, b, dashed=dashed)
        self.assertEqual(len(calls), 2)
        env["pulse_between"](scene, a, a)
        self.assertEqual(calls[-1], "indicate")

    def setUp(self):
        tree = ast.parse(_SCRIPT_TEMPLATE.replace("__PLAN_JSON__", "'{}'"))
        helpers = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                                  and n.name in {"replace_component", "show_subtitle"}],
                             type_ignores=[])
        self.env = dict(Text=Object, ENGLISH=False, DOWN=0, Transform=lambda old, new: ("transform", old),
                        FadeOut=lambda obj: ("out", obj), FadeIn=lambda obj: ("in", obj))
        exec(compile(helpers, "generated_helpers", "exec"), self.env)

    def test_component_replacement_removes_old_glyph_family(self):
        scene = Scene()
        old, new = Object("old"), Object("new")
        scene.add(old)
        result = self.env["replace_component"](scene, old, new)
        self.assertIs(result, new)
        self.assertEqual(scene.visible, set(new.get_family()))

    def test_subtitle_updates_reuse_identical_text_and_clear_empty_text(self):
        scene = Scene()
        show = self.env["show_subtitle"]
        first = show(scene, "first fact", None)
        self.assertIs(show(scene, "first fact", first), first)
        second = show(scene, "second fact", first)
        self.assertEqual(scene.visible, set(second.get_family()))
        self.assertIsNone(show(scene, "", second))
        self.assertFalse(scene.visible)
