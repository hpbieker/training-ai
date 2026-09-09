import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'plugins/strava'))
import route_editing as edit


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.points = [(59, 10), (59, 10.001), (59, 10.002), (59, 10.003), (59, 10.004)]
        ds = edit.cumulative(self.points)
        self.path = edit.make_path(self.points, list(zip(ds, [10, 12, 8, 11, 10])))
        self.route = {'id': '3532440438889330932', 'elements': [
            {'waypoint': {'point': dict(zip(('lat','lng'), p))}} for p in (self.points[0],self.points[-1])],
            'legs': [{'paths': [self.path]}]}
        self.geo = {'type': 'LineString', 'coordinates': [[10.001,59,12],[10.002,59.0001,14],[10.003,59,11]]}

    def test_splice_preserves_prefix_suffix_and_source(self):
        before = copy.deepcopy(self.route)
        legs = edit.replace_points(self.route, 0, 1, 3, self.geo)
        path = legs[0]['paths'][0]
        points = edit.decode_polyline(path['polyline']['data'])
        self.assertEqual(points[:2], self.points[:2]); self.assertEqual(points[-2:], self.points[-2:])
        self.assertEqual(points[2], (59.0001,10.002))
        self.assertEqual(len(legs[0]['paths']), 1)
        self.assertAlmostEqual(path['elevationGain'], 4, places=2)
        self.assertAlmostEqual(path['elevationLoss'], 4, places=2)
        self.assertEqual(self.route, before)
        self.assertLess(abs(edit.elevation(path)[-1][0]-path['length']), .11)

    def test_no_invented_heights_or_surfaces(self):
        geo = copy.deepcopy(self.geo)
        for point in geo['coordinates']:point.pop()
        with self.assertRaisesRegex(ValueError, 'elevation-profile'):
            edit.replacement_path(geo)
        profile = [[0,12],[edit.cumulative([(p[1],p[0]) for p in geo['coordinates']])[-1],11]]
        path = edit.replacement_path(geo,profile)
        self.assertEqual(path['surfaceTypeOffsets'][0]['surfaceType'],'Unknown')

    def test_alternatives_are_not_concatenated(self):
        with self.assertRaisesRegex(ValueError, 'one native path'):
            edit.replacement_path({'legs':[{'paths':[self.path,self.path]}]})

    def test_build_results_merge_into_one_path(self):
        a = edit.slice_path(self.path,0,2); b = edit.slice_path(self.path,2,4)
        path = edit.replacement_path({'buildRoute':[{'legs':[{'paths':[a]}]},{'legs':[{'paths':[b]}]}]})
        self.assertEqual(edit.decode_polyline(path['polyline']['data']),self.points)
        self.assertAlmostEqual(path['length'],self.path['length'])

    def test_bad_joins_and_indices_rejected(self):
        with self.assertRaisesRegex(ValueError,'gap'):
            edit.replace_points(self.route,0,0,3,self.geo)
        with self.assertRaises(ValueError): edit.replace_points(self.route,0,3,1,self.geo)
        with self.assertRaisesRegex(ValueError,'gap'):
            edit.merge_paths([self.path,self.path])

    def test_fingerprint_ignores_metadata_but_detects_geometry(self):
        other=copy.deepcopy(self.route);other['title']='New title';other['legs'][0]['startElement']=0
        self.assertEqual(edit.fingerprint(other),edit.fingerprint(self.route))
        other['elements'][0]['waypoint']['point']['lat']+=.001
        self.assertNotEqual(edit.fingerprint(other),edit.fingerprint(self.route))

    def test_batch_uses_original_indices_after_first_edit_grows(self):
        first = {'type':'LineString','coordinates':[[10,59,10],[10.0003,59.0001,11],[10.0007,59.0001,12],[10.001,59,12]]}
        second = {'type':'LineString','coordinates':[[10.003,59,11],[10.0035,59.0001,13],[10.004,59,10]]}
        edits = [{'leg':0,'from_point':3,'to_point':4,'replacement':second},
                 {'leg':0,'from_point':0,'to_point':1,'replacement':first}]
        legs, report = edit.replace_batch(self.route, edits)
        points = edit.decode_polyline(legs[0]['paths'][0]['polyline']['data'])
        self.assertEqual(points[3:6], self.points[1:4])
        self.assertEqual(points[-2], (59.0001,10.0035))
        self.assertEqual([r['from_point'] for r in report], [3,0])
        self.assertEqual(self.route['legs'][0]['paths'][0],self.path)

    def test_batch_two_legs_and_overlap(self):
        route = copy.deepcopy(self.route);route['legs'] *= 2
        row = {'leg':0,'from_point':1,'to_point':3,'replacement':self.geo}
        legs, reports = edit.replace_batch(route, [row,{**row,'leg':1}])
        self.assertEqual(len(reports),2)
        self.assertEqual(legs[0],legs[1])
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            edit.replace_batch(route,[row,{**row,'from_point':2}])

    def test_explicit_endpoint_tolerance_and_audit(self):
        geo = copy.deepcopy(self.geo);geo['coordinates'][0][0] += .00001
        row = {'leg':0,'from_point':1,'to_point':3,'replacement':geo}
        with self.assertRaisesRegex(ValueError,'exceeds'):edit.replace_batch(self.route,[row])
        legs, reports = edit.replace_batch(self.route,[row],1.5)
        points = edit.decode_polyline(legs[0]['paths'][0]['polyline']['data'])
        self.assertEqual(points[:2],self.points[:2])
        change = reports[0]['join_adjustments'][0]
        self.assertGreater(change['gap_m'],0)
        self.assertLess(change['gap_m'],1.5)
        geo['coordinates'][0][0] += .0001
        with self.assertRaisesRegex(ValueError,'exceeds'):edit.replace_batch(self.route,[row],1.5)

    def test_internal_native_join_tolerance(self):
        a = edit.slice_path(self.path,0,2);b = edit.slice_path(self.path,2,4)
        points = edit.decode_polyline(b['polyline']['data']);points[0]=(points[0][0],points[0][1]+.00001)
        b = edit.make_path(points,edit.elevation(b))
        changes=[]
        with self.assertRaises(ValueError):edit.merge_paths([a,b])
        result=edit.merge_paths([a,b],1.5,changes)
        self.assertEqual(edit.decode_polyline(result['polyline']['data']),self.points)
        self.assertEqual(changes[0]['section'],'native_section_1')

    def test_invalid_tolerance_and_indices(self):
        row={'leg':0,'from_point':1,'to_point':3,'replacement':self.geo}
        for value in (-1, float('nan'), float('inf'), True, '1'):
            with self.subTest(value=value),self.assertRaises(ValueError):edit.replace_batch(self.route,[row],value)
        with self.assertRaises(ValueError):edit.replace_batch(self.route,[{**row,'leg':True}])

    def test_manifest_relative_paths_and_failed_batch_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/'route.json').write_text(json.dumps(self.route))
            (base/'new.json').write_text(json.dumps(self.geo))
            manifest={'max_join_gap_m':1.5,'edits':[{'leg':0,'from_point':1,'to_point':3,'replacement_file':'new.json'}]}
            (base/'edits.json').write_text(json.dumps(manifest))
            cmd=[sys.executable,'-B',str(ROOT/'plugins/strava/scripts/prepare_route_update.py'),'--route',str(base/'route.json'),
                 '--edits',str(base/'edits.json'),'--output-dir',str(base/'out')]
            run=subprocess.run(cmd,capture_output=True,text=True,cwd='/private/tmp')
            self.assertEqual(run.returncode,0,run.stderr)
            report=json.loads((base/'out/report.json').read_text())
            self.assertEqual(report['edits'][0]['inputs']['replacement_file']['path'],str((base/'new.json').resolve()))
            self.assertEqual(report['max_join_gap_m'],1.5)
            manifest['edits'].append(manifest['edits'][0]);(base/'edits.json').write_text(json.dumps(manifest))
            cmd[-1]=str(base/'failed')
            run=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0)
            self.assertIn('Overlapping',run.stderr)
            self.assertFalse((base/'failed').exists())

    def test_cli_private_artifacts_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/'route.json').write_text(json.dumps({'route_id':self.route['id'],'route':self.route}))
            (base/'new.json').write_text(json.dumps(self.geo))
            cmd=[sys.executable,'-B',str(ROOT/'plugins/strava/scripts/prepare_route_update.py'),'--route',str(base/'route.json'),
                 '--replacement',str(base/'new.json'),'--leg','0','--from-point','1','--to-point','3','--output-dir',str(base/'out')]
            run=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads((base/'out/update.json').read_text())
            self.assertEqual(result['base_geometry_sha256'],edit.fingerprint(self.route))
            self.assertEqual((base/'out/update.json').stat().st_mode&0o777,0o600)
            self.assertNotIn('polyline',run.stdout)
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)

if __name__=='__main__':unittest.main()
