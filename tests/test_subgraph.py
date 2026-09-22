import unittest

from rendering.subgraph import prepare_subgraph, group_subquestions


class SubgraphTests(unittest.TestCase):
    def test_revisit_keeps_narration_audio_and_evidence_without_replay(self):
        from rendering.subgraph import compact_revisits
        import copy
        def scene(name, narration):
            return {'scene_id': name, 'metadata': {'source_beat_ids': ['a', 'b']},
                    'beats': [{'beat_id': name+'a', 'template_id': 'transform',
                               'node_ids': ['A'], 'relation_ids': ['r'], 'narration': narration,
                               'audio': {'path': name+'.wav', 'duration': 9}},
                              {'beat_id': name+'b', 'template_id': 'transform',
                               'node_ids': ['B'], 'relation_ids': ['r'], 'narration': narration,
                               'audio_end': True}]}
        payload = {'scenes': [scene('first', 'First explanation'), scene('second', 'New explanation')]}
        original = copy.deepcopy(payload)
        result = compact_revisits(payload)
        self.assertEqual(result['scenes'][0], payload['scenes'][0])
        beats = result['scenes'][1]['beats']
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0]['template_id'], 'evidence_revisit')
        self.assertEqual(beats[0]['node_ids'], ['A', 'B'])
        self.assertEqual(beats[0]['relation_ids'], ['r'])
        self.assertEqual(beats[0]['narration'], 'New explanation')
        self.assertEqual(beats[0]['audio']['path'], 'second.wav')
        self.assertTrue(beats[0]['audio_end'])
        self.assertEqual(compact_revisits(result), result)
        self.assertEqual(payload, original)

    def test_graph_panel_modes_preserve_atomic_layout_and_audio(self):
        import copy
        payload = {'scenes': [{'scene_id': 'S1', 'layout': 'interface_layers',
            'metadata': {'atomic_semantic_scene': True},
            'nodes': [{'knowledge_node_id': 'A', 'archetype': 'hardware_icon', 'x': 1, 'y': 0}],
            'relations': [], 'beats': [{'beat_id': 'B1', 'node_ids': ['A'],
                                      'audio': {'path': 'voice.wav', 'duration': 2}}]}]}
        original = copy.deepcopy(payload)
        automatic = prepare_subgraph(payload, graph_panel='auto')
        self.assertEqual(automatic['metadata']['presentation'], 'semantic_scenes')
        shown = prepare_subgraph(payload, graph_panel='on')
        self.assertEqual(shown['scenes'][0]['layout'], 'persistent_subgraph')
        self.assertEqual(shown['scenes'][0]['metadata']['local_scene'], payload['scenes'][0])
        self.assertEqual(prepare_subgraph(group_subquestions(shown)), shown)
        hidden = prepare_subgraph(shown, graph_panel='off')
        self.assertEqual(hidden['scenes'][0]['layout'], 'interface_layers')
        self.assertEqual(hidden['scenes'][0]['nodes'], original['scenes'][0]['nodes'])
        self.assertEqual(hidden['scenes'][0]['beats'], original['scenes'][0]['beats'])
        self.assertEqual(prepare_subgraph(group_subquestions(hidden)), hidden)
        self.assertEqual(payload, original)
        with self.assertRaises(ValueError):
            prepare_subgraph(payload, graph_panel='invalid')

    def test_graph_panel_off_restores_separate_grouped_stages(self):
        payload = {'metadata': {'graph_panel': 'off'}, 'scenes': [
            {'scene_id': f'S{i}', 'metadata': {'subquestion_id': 'Q1'},
             'nodes': [{'knowledge_node_id': str(i), 'x': i, 'y': 0}],
             'relations': [], 'beats': [{'beat_id': f'B{i}'}]} for i in range(2)]}
        result = prepare_subgraph(group_subquestions(payload))
        self.assertEqual(len(result['scenes']), 2)
        self.assertEqual([s['nodes'][0]['x'] for s in result['scenes']], [0, 1])
        self.assertEqual(result['metadata']['presentation'], 'semantic_scenes')

    def test_grouping_tuple_and_json_inputs_match_across_three_steps(self):
        import json
        payload = {"scenes": tuple({
            "scene_id": f"S{i}", "metadata": {"subquestion_id": "Q1"},
            "nodes": ({"knowledge_node_id": "A", "name": "A"},),
            "relations": ({"relation_id": f"R{i}", "stored_source_node_id": "A",
                           "stored_target_node_id": "A"},),
            "beats": ({"beat_id": f"B{i}", "audio": {"path": "test.wav"}},)
        } for i in range(3))}
        result = group_subquestions(payload)
        self.assertEqual(len(result["scenes"]), 1)
        scene = result["scenes"][0]
        self.assertEqual([b["beat_id"] for b in scene["beats"]], ["B0", "B1", "B2"])
        self.assertEqual(len(scene["nodes"]), 1)
        self.assertEqual(len(scene["relations"]), 3)
        self.assertEqual(len(scene["metadata"]["local_stages"]), 3)
        self.assertEqual(json.loads(json.dumps(result)),
                         group_subquestions(json.loads(json.dumps(payload))))
        self.assertIsInstance(payload["scenes"][0]["beats"], tuple)
        prepare_subgraph(result)

    def test_cumulative_identity_layout_and_parallel_edges(self):
        def node(n): return {"knowledge_node_id": n, "name": n}
        def edge(r, a, b):
            return {"relation_id": r, "stored_source_node_id": a, "stored_target_node_id": b}
        payload = {"scenes": [
            {"nodes": [node("A"), node("B")], "relations": [edge("r1", "A", "B")]},
            {"nodes": [node("B"), node("C")], "relations": [edge("r2", "B", "C")]},
            {"nodes": [node("B"), node("A")], "relations": [edge("r3", "B", "A")]},
        ]}
        graph = prepare_subgraph(payload)
        scenes = graph["scenes"]
        self.assertEqual([len(s["nodes"]) for s in scenes], [2, 3, 3])
        self.assertEqual([len(s["relations"]) for s in scenes], [1, 2, 3])
        self.assertEqual(scenes[0]["nodes"][0], scenes[2]["nodes"][0])
        relations = {r["relation_id"]: r for r in scenes[-1]["relations"]}
        self.assertNotEqual(relations["r1"]["metadata"]["lane"], relations["r3"]["metadata"]["lane"])
        self.assertEqual(prepare_subgraph(graph), graph)
        self.assertNotIn("layout", payload["scenes"][0])

    def test_local_scene_keeps_semantic_profile_and_coordinates(self):
        original = {"scenes": [{"nodes": [{"knowledge_node_id": "A", "name": "A",
            "archetype": "storage_block", "x": 1, "y": 2, "metadata": {"semantic_role": "storage"}}],
            "relations": [], "beats": [{"phase_id": "show_storage"}], "layout": "storage_write"}]}
        result = prepare_subgraph(original)
        scene = result["scenes"][0]
        self.assertEqual(scene["nodes"][0]["archetype"], "graph_node")
        self.assertEqual(scene["metadata"]["local_scene"], original["scenes"][0])
