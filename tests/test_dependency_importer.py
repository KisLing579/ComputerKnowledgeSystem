from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from kg.config import load_settings
from kg.importer import ImportValidationError, load_excel, _prepare_relations


class DependencyImporterTests(unittest.TestCase):
    def load_fixture(self, dependencies=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        workbook = Path(directory.name) / 'kg.xlsx'
        with pd.ExcelWriter(workbook) as writer:
            pd.DataFrame([
                {'node_id:ID': n, 'name': n, 'labels:LABEL': 'KnowledgeNode'}
                for n in ('A', 'B')
            ]).to_excel(writer, sheet_name='KG_Nodes', index=False)
            pd.DataFrame(columns=['rel_id', ':START_ID', ':END_ID', ':TYPE']).to_excel(
                writer, sheet_name='KG_Relations', index=False)
            if dependencies is not None:
                pd.DataFrame(dependencies).to_excel(
                    writer, sheet_name='Knowledge_Dependencies', index=False)
        settings = load_settings()
        return load_excel(replace(settings, data=replace(settings.data, workbook=workbook)))

    def dependency(self, **changes):
        return {'dependency_id': 'KD1', ':START_ID': 'A', ':END_ID': 'B',
                ':TYPE': 'PREREQUISITE_OF', 'strength': 'required',
                'weight:float': 0.94, 'review_status': 'review_recommended', **changes}

    def test_direction_and_properties_are_preserved(self):
        _, relations = self.load_fixture([self.dependency()])
        row = _prepare_relations(relations, {'A', 'B'})['PREREQUISITE_OF'][0]
        self.assertEqual((row['start_id'], row['end_id']), ('A', 'B'))
        self.assertEqual(row['props']['weight'], 0.94)
        self.assertEqual(row['props']['dependency_id'], 'KD1')
        self.assertEqual(row['props']['relation_layer'], 'teaching')
        self.assertEqual(row['props']['review_status'], 'review_recommended')

    def test_legacy_workbook(self):
        _, relations = self.load_fixture()
        self.assertTrue(relations.empty)

    def test_inactive_dependencies_excluded(self):
        _, relations = self.load_fixture([self.dependency(status='inactive')])
        self.assertTrue(relations.empty)

    def test_missing_endpoint_rejected(self):
        _, relations = self.load_fixture([self.dependency(**{':END_ID': 'missing'})])
        with self.assertRaises(ImportValidationError):
            _prepare_relations(relations, {'A', 'B'})

    def test_self_dependency_rejected(self):
        with self.assertRaises(ImportValidationError):
            self.load_fixture([self.dependency(**{':END_ID': 'A'})])

    def test_duplicate_dependency_id_rejected(self):
        _, relations = self.load_fixture([self.dependency(), self.dependency()])
        with self.assertRaises(ImportValidationError):
            _prepare_relations(relations, {'A', 'B'})
