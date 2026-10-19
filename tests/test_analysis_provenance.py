import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from activity_inspect import analysis_provenance
from analysis import SavedActivity
from prepare_training_analysis_eval import snapshot_case

ROOT = Path(__file__).resolve().parents[1]


class ProvenanceTests(unittest.TestCase):
    def test_raw_change_and_options_are_traceable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'activity.json').write_text('{}')
            (p/'streams.csv').write_text('time,watts\n0,200\n')
            extra = p/'garmin.json'; extra.write_text('{}')
            activity = SavedActivity(p, {}, [])
            args = argparse.Namespace(vt2_watts=295, garmin_json=extra, output='ignored.json')
            first = analysis_provenance(activity, args)
            (p/'streams.csv').write_text('time,watts\n0,250\n')
            args.vt2_watts = None
            second = analysis_provenance(activity, args)
            self.assertNotEqual(first['inputs'][1]['sha256'], second['inputs'][1]['sha256'])
            self.assertEqual(first['inputs'][2]['sha256'], hashlib.sha256(extra.read_bytes()).hexdigest())
            self.assertEqual(first['options']['vt2_watts'], 295)
            self.assertIsNone(second['options']['vt2_watts'])
            self.assertNotIn('output', first['options'])
            self.assertEqual({Path(x['path']).name for x in first['scripts']},
                             {'activity_inspect.py', 'analysis.py', 'physiological_evidence.py', 'outdoor_evidence.py'})

    def test_provenance_survives_all_cli_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'activity.json').write_text('{"id":"test","type":"Ride"}')
            (p/'streams.csv').write_text('time,watts,heartrate\n'+''.join(f'{t},200,120\n' for t in range(300)))
            for flags in ([], ['--compact'], ['--brief']):
                output = p/'result.json'
                subprocess.run([sys.executable,'-B',str(ROOT/'scripts/activity_inspect.py'),str(p),*flags,'--output',str(output)],check=True,capture_output=True)
                result = json.loads(output.read_text())
                self.assertEqual(result['provenance']['format_version'], 1)
                self.assertEqual(result['provenance']['inputs'][0]['sha256'], hashlib.sha256((p/'activity.json').read_bytes()).hexdigest())

    def test_case_snapshot_excludes_legacy_analyses(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp);source=p/'source';source.mkdir();case=p/'case';case.mkdir()
            for name in ('activity.json','streams.csv','analysis.json','old-report.md'):
                (source/name).write_text(name)
            repo=p/'repo';(repo/'scripts').mkdir(parents=True);(repo/'config').mkdir()
            for name in ('activity_inspect.py','analysis.py','physiological_evidence.py','outdoor_evidence.py','analysis_packet.py'):
                (repo/'scripts'/name).write_text('test')
            for name in ('coaching-preferences.md','practical-context.md'):
                (repo/'config'/name).write_text('test')
            skill=p/'skill';skill.mkdir();(skill/'SKILL.md').write_text('test')
            with patch('prepare_training_analysis_eval.ROOT',repo):
                activity,local_skill,scripts=snapshot_case(case,source,skill)
            self.assertEqual({f.name for f in activity.iterdir()}, {'activity.json','streams.csv'})
            self.assertTrue((local_skill/'SKILL.md').is_file())
            (source/'streams.csv').write_text('changed')
            self.assertEqual((activity/'streams.csv').read_text(),'streams.csv')
            self.assertFalse((activity/'streams.csv').is_symlink())


if __name__ == '__main__':
    unittest.main()
