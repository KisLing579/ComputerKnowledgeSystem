import json
import unittest
from types import SimpleNamespace as NS
from resource_planning.summary import narration_conclusion


class NarrationConclusionTests(unittest.TestCase):
    def story(self):
        return NS(question='How?', metadata={'answer_summary': 'Old graph answer'}, scenes=[
            NS(scene_role='fact', beats=[NS(narration=t), NS(narration=t)], narration_summary=t)
            for t in ('First step.', 'Middle step.', 'Final result.')])

    def test_model_receives_all_narration_without_graph(self):
        prompts = []
        def invoke(prompt):
            prompts.append(prompt)
            return {'points': [{'text': 'Steps lead to the result.', 'narration_ids': [0, 1, 2]}]}
        points, report = narration_conclusion(self.story(), NS(invoke=invoke))
        self.assertEqual(points, ['Steps lead to the result.'])
        self.assertEqual(len(report['transcript']), 3)
        self.assertNotIn('Old graph answer', prompts[0])
        for text in ('First step.', 'Middle step.', 'Final result.'):
            self.assertIn(text, prompts[0])

    def test_invalid_references_fall_back_to_narration_not_graph(self):
        model = NS(invoke=lambda _: {'points': [{'text': 'Invented result', 'narration_ids': [999]}]})
        points, report = narration_conclusion(self.story(), model)
        self.assertEqual(points, ['First step.', 'Middle step.', 'Final result.'])
        self.assertEqual(report['mode'], 'extractive_fallback')

