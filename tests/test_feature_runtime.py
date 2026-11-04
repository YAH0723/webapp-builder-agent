"""Optional helper publication preserves custom and accepted application code."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from infrastructure.shared.project.features import prepare_features, runtime_context, CLIENT
from infrastructure.utils.files import save_json, save_text


class FeatureRuntime(unittest.TestCase):
    def setUp(self):
        context = patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b2'}, clear=True)
        context.start()
        self.addCleanup(context.stop)

    def test_fresh_install_uses_arbitrary_contract_ids_and_routes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_json(root / '.arc/backend_apis.json', {'apis': {'CUSTOM': {'signature': {'method': 'PATCH', 'path': '/api/things/:id'}}}})
            prepare_features(root)
            self.assertIn('CUSTOM', (root / CLIENT).read_text())
            self.assertIn('/api/things/:id', (root / CLIENT).read_text())
            self.assertEqual(len(runtime_context(root)['helpers']), 4)

    def test_contract_updates_regenerate_only_unchanged_managed_client(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_features(root)
            save_json(root / '.arc/backend_apis.json', {'apis': {'NEW': {'signature': {'method': 'GET', 'path': '/api/new'}}}})
            prepare_features(root)
            self.assertIn('NEW', (root / CLIENT).read_text())
            save_text(root / CLIENT, '// custom client\n')
            prepare_features(root)
            self.assertEqual((root / CLIENT).read_text(), '// custom client\n')
            self.assertNotIn(CLIENT, runtime_context(root)['helpers'])

    def test_existing_application_and_custom_helpers_are_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_text(root / 'frontend/src/App.tsx', 'existing application')
            path = 'frontend/src/arc-lib/http.ts'
            save_text(root / path, '// custom transport\n')
            prepare_features(root)
            self.assertEqual((root / path).read_text(), '// custom transport\n')
            self.assertEqual((root / 'frontend/src/App.tsx').read_text(), 'existing application')
            self.assertNotIn(path, runtime_context(root)['helpers'])
            self.assertNotIn(CLIENT, runtime_context(root)['helpers'])

    def test_edited_helpers_are_no_longer_advertised_as_known_interfaces(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_features(root)
            path = 'frontend/src/arc-lib/useSubmit.ts'
            save_text(root / path, '// changed interface')
            self.assertNotIn(path, runtime_context(root)['helpers'])

    def test_disabled_profile_does_not_install_helpers(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ', {'ARC_AGENT_PROFILE': 'b1'}, clear=True):
            root = Path(directory)
            prepare_features(root)
            self.assertEqual(list(root.iterdir()), [])
            self.assertIsNone(runtime_context(root))


if __name__ == '__main__':
    unittest.main()
