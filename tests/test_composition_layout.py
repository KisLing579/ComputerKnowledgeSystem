import unittest
from types import SimpleNamespace as NS
from rendering.layout.engine import LayoutEngine


class CompositionLayoutTests(unittest.TestCase):
    def positions(self, kind='PART_OF'):
        nodes = [NS(knowledge_node_id=n) for n in ('hardware', 'system', 'software')]
        edges = [NS(relation_type=kind,
                    stored_source_node_id=part if kind == 'PART_OF' else 'system',
                    stored_target_node_id='system' if kind == 'PART_OF' else part)
                 for part in ('hardware', 'software')]
        return LayoutEngine()._inside_container(NS(focus_node_ids=('hardware',)), nodes, edges)

    def test_stored_direction_overrides_focus(self):
        for kind in ('PART_OF', 'CONTAINS'):
            positions = self.positions(kind)
            self.assertTrue(positions['system'][3]['container_root'])
            self.assertEqual(positions['hardware'][3]['semantic_role'], 'part')
            self.assertEqual(positions['software'][3]['semantic_role'], 'part')
            self.assertEqual(positions['hardware'][3]['layout_width'], positions['software'][3]['layout_width'])
            whole = positions['system'][3]
            for node in ('hardware', 'software'):
                x, y, _, meta = positions[node]
                self.assertLess(abs(x)+meta['layout_width']/2, whole['layout_width']/2)
                self.assertLess(abs(y)+meta['layout_height']/2, whole['layout_height']/2)

    def test_no_relation_does_not_invent_container(self):
        positions = LayoutEngine()._inside_container(NS(focus_node_ids=('A',)),
                    [NS(knowledge_node_id='A'), NS(knowledge_node_id='B')], [])
        self.assertFalse(any(p[3].get('container_root') for p in positions.values()))
