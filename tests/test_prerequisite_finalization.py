from dataclasses import dataclass, field
import unittest
from student_model.finalize import finalize_prerequisites


@dataclass
class Item:
    segment_id: str = ''
    metadata: dict = field(default_factory=dict)
    children: tuple = ()
    scenes: tuple = ()
    node_ids: tuple = ()
    beats: tuple = ()
    story_scene_id: str = ''
    title: str = ''
    root_segment: object = None
    representation_plan: object = None
    estimated_duration: float = 0


class FinalizationTests(unittest.TestCase):
    def test_unselected_core_pruned_shared_ancestor_kept(self):
        pre = [Item(segment_id=n, metadata={'prerequisite': True}, node_ids=(n,)) for n in ('shared', 'unused')]
        answer = Item(node_ids=('chosen',), story_scene_id='Q1', title='question')
        story = Item(scenes=tuple(pre + [answer]), representation_plan=Item(root_segment=Item(children=tuple(pre))))
        report = {'subquestions': [{'subgraphs': [
            {'core_node_id': 'chosen', 'subgraph_id': 'G1', 'nodes': [{'node_id': 'shared'}]},
            {'core_node_id': 'discarded', 'subgraph_id': 'G2', 'nodes': [{'node_id': 'shared'}, {'node_id': 'unused'}]}]}]}
        result, audit = finalize_prerequisites(story, report)
        self.assertEqual([s.segment_id for s in result.scenes], ['shared', ''])
        self.assertEqual(audit['teaching_node_ids'], ['shared'])
        self.assertEqual(result.scenes[0].metadata['supports_final_answer'][0]['core_node_id'], 'chosen')
        self.assertEqual(len(result.representation_plan.root_segment.children), 1)
        self.assertEqual(len(story.scenes), 3)
        self.assertNotIn('final_selection', report)

    def test_no_selected_dependency_removes_all_prerequisites(self):
        pre = Item(segment_id='P', metadata={'prerequisite': True}, node_ids=('P',))
        story = Item(scenes=(pre,), representation_plan=Item(root_segment=Item(children=(pre,))))
        result, audit = finalize_prerequisites(story, {})
        self.assertEqual(result.scenes, ())
        self.assertEqual(audit['teaching_node_ids'], [])
