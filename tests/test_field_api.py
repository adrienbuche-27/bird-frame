"""Field recordings API (avian/api/field.php), alone and end to end."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.helpers import TESTDATA, Settings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAS_PHP = shutil.which('php') is not None
HAS_FFMPEG = shutil.which('ffmpeg') is not None

# Uploads a file through field.php's functions in base64 chunks, the way the
# browser will, then prints the list. AV_FIELD_DIR keeps it in a scratch dir.
UPLOAD = r'''
define('AVIAN_FIELD_LIBRARY_ONLY', true);
require getenv('FIELD_PHP');
$dir = field_dir();
$db = field_open_db($dir);
if (getenv('FIELD_UPLOAD')) {
    $data = file_get_contents(getenv('FIELD_UPLOAD'));
    $b = field_begin($db, $dir, ['name' => 'Magpie walk.wav', 'size' => strlen($data),
        'lat' => 50.0, 'lon' => 5.0, 'recorded_at' => '2024-02-24T16:19', 'place' => 'Test wood']);
    for ($o = 0; $o < strlen($data); $o += $b['chunk_bytes']) {
        field_chunk($db, $dir, ['id' => $b['id'], 'offset' => $o,
            'data' => base64_encode(substr($data, $o, $b['chunk_bytes']))]);
    }
    field_finish($db, $dir, ['id' => $b['id']]);
}
echo json_encode(field_list($db));
'''


@unittest.skipUnless(HAS_PHP, 'needs the php CLI')
class FieldApiTests(unittest.TestCase):

    def test_php_checks(self):
        out = subprocess.run(['php', 'tests/test_field_api.php'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_every_action_needs_the_admin(self):
        source = open(os.path.join(ROOT, 'avian/api/field.php')).read()
        dispatch = source.index("if (defined('AVIAN_FIELD_LIBRARY_ONLY')) return;")
        self.assertLess(dispatch, source.index('avian_require_admin();'))
        self.assertLess(source.index('avian_require_admin();'), source.index("$action = $_GET['action']"))
        self.assertIn('avian_require_json_action();', source)

    def test_caddy_publishes_the_endpoint(self):
        caddy = open(os.path.join(ROOT, 'scripts/update_caddyfile.sh')).read()
        self.assertIn('/avian/api/field.php', caddy)

    @unittest.skipUnless(HAS_FFMPEG, 'analysis decodes audio with ffmpeg')
    def test_upload_analyse_list(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        env = dict(os.environ, AV_FIELD_DIR=tmp, FIELD_PHP=os.path.join(ROOT, 'avian/api/field.php'),
                   FIELD_UPLOAD=os.path.join(TESTDATA, 'Pica pica_30s.wav'))

        def php(**extra):
            out = subprocess.run(['php', '-r', UPLOAD], env=dict(env, **extra), capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout)['recordings']

        queued = php()
        self.assertEqual([r['status'] for r in queued], ['queued'])

        # The worker, loaded the way the station runs it.
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        self.addCleanup(sys.path.remove, os.path.join(ROOT, 'scripts'))
        spec = importlib.util.spec_from_file_location('field_analysis_e2e', os.path.join(ROOT, 'scripts/field_analysis.py'))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with patch('utils.helpers._load_settings', side_effect=lambda *a, **k: Settings.with_defaults()), \
                patch('utils.analysis.loadCustomSpeciesList', return_value=[]), \
                patch('utils.field.loadCustomSpeciesList', return_value=[]):
            self.assertEqual(cli.run(Settings.with_defaults(), tmp), 1)

        rec = php(FIELD_UPLOAD='')[0]
        self.assertEqual(rec['status'], 'done', rec)
        self.assertEqual(rec['place'], 'Test wood')
        self.assertEqual(rec['recorded_at'], '2024-02-24T16:19:00')
        self.assertEqual([s['sci'] for s in rec['species']], ['Pica pica'])
        self.assertGreaterEqual(rec['species'][0]['best'], 0.7)


if __name__ == '__main__':
    unittest.main()
