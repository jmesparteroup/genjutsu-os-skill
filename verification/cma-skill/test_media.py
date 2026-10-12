"""Offline Linux media + staged pipeline integration; FAL is replaced by local fixtures."""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(os.environ.get('GENJUTSU_SKILL_ROOT', Path(__file__).resolve().parents[2] / '.claude/skills/genjutsu-fal-cma'))
spec = importlib.util.spec_from_file_location('genjutsu', ROOT / 'scripts/genjutsu.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
spec = importlib.util.spec_from_file_location('mask', ROOT / 'scripts/validate_mask.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def ff(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1', *map(str, args)], check=True)


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        ff('-f', 'lavfi', '-i', 'color=red:s=640x480:r=24:d=4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
           '-c:v', 'libx264', '-c:a', 'aac', cls.base / 'source.mp4')
        ff('-f', 'lavfi', '-i', 'color=blue:s=640x480:r=24:d=4', '-c:v', 'libx264', cls.base / 'depth.mp4')
        ff('-f', 'lavfi', '-i', 'color=black:s=640x480:r=24:d=4', '-vf', 'drawbox=x=0:y=0:w=320:h=480:color=white:t=fill',
           '-c:v', 'libx264', '-crf', '0', cls.base / 'mask.mp4')
        ff('-f', 'lavfi', '-i', 'color=red:s=640x480:r=24:d=4', '-c:v', 'libx264', cls.base / 'colored.mp4')
        ff('-f', 'lavfi', '-i', 'color=gray:s=640x480:r=24:d=4', '-c:v', 'libx264', cls.base / 'gray.mp4')
        ff('-f', 'lavfi', '-i', 'color=blue:s=640x480:r=24:d=3', '-c:v', 'libx264', cls.base / 'short.mp4')
        ff('-f', 'lavfi', '-i', 'color=white:s=640x480', '-frames:v', '1', '-update', '1', cls.base / 'character.png')
        ff('-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-c:a', 'pcm_s16le', cls.base / 'vocals.wav')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_mask_frames_and_colored_gray_misaligned_rejections(self):
        report = m.validate(self.base / 'source.mp4', self.base / 'mask.mp4', self.base / 'depth.mp4')
        self.assertEqual(report['frames_checked'], 96)
        self.assertAlmostEqual(report['white_fraction_per_frame'][0], 0.5, places=2)
        for name in ['colored.mp4', 'gray.mp4', 'short.mp4']:
            with self.assertRaises(ValueError):
                m.validate(self.base / 'source.mp4', self.base / name)

    def test_restore_rejects_duration_difference_before_export(self):
        output = self.base / 'must-not-exist.mp4'
        with self.assertRaises(subprocess.CalledProcessError):
            g.media('restore', self.base / 'short.mp4', self.base / 'source.mp4', output)
        self.assertFalse(output.exists())

    def test_full_staged_pipeline_with_fake_fal_and_real_media(self):
        run = self.base / 'run'
        original_sha = g.sha(self.base / 'source.mp4')
        g.init(argparse.Namespace(run=str(run), source=str(self.base / 'source.mp4'), character=str(self.base / 'character.png'),
                                  subject='person', prompt_file=None))
        state = json.loads((run / 'state.json').read_text())
        fixtures = {'vocals': 'vocals.wav', 'depth': 'depth.mp4', 'sam': 'mask.mp4', 'seedance': 'depth.mp4'}

        class FakeFal:
            def __init__(self): self.calls = []
            def upload(self, path): return 'https://fal.media/' + Path(path).name
            def submit(self, endpoint, payload):
                name = {g.DEMUCS: 'vocals', g.DEPTH: 'depth', g.SAM: 'sam', g.SEEDANCE: 'seedance'}[endpoint]
                self.calls.append((endpoint, payload))
                base = 'https://queue.fal.run/' + '/'.join(endpoint.split('/')[:2]) + '/requests/' + name
                return {'request_id': name, 'status_url': base + '/status', 'response_url': base, 'cancel_url': base + '/cancel'}
            def get(self, url):
                if url.endswith('/status'): return {'status': 'COMPLETED'}
                name = url.rsplit('/', 1)[1]
                return {'vocals' if name == 'vocals' else 'video': {'url': 'https://fal.media/' + fixtures[name]}}

        def local_download(run, state, name, url):
            import shutil
            shutil.copy2(self.base / url.rsplit('/', 1)[1], run / name)

        fal = FakeFal()
        plan = argparse.Namespace(execute=False, allow_paid=False)
        execute = argparse.Namespace(execute=True, allow_paid=True)
        with patch.object(g, 'Transport', return_value=fal), patch.object(g, 'download', side_effect=local_download):
            self.assertEqual(g.prepare(run, state, plan)['submits'], 0)
            self.assertEqual(fal.calls, [])
            for _ in range(3): g.prepare(run, state, execute)
            self.assertEqual(len(fal.calls), 3)
            built = g.build_review(run, state, argparse.Namespace(mask=str(self.base / 'mask.mp4')))
            self.assertEqual(built['stage'], 'ready-for-generation')
            self.assertNotIn('review', state)
            review_exports = json.loads(subprocess.check_output([sys.executable, str(ROOT / 'scripts/genjutsu.py'),
                'export', '--run', str(run), '--output-dir', str(self.base / 'exports')]))
            self.assertEqual(len(review_exports['exported']), 3)
            self.assertTrue(all(Path(p).exists() for p in review_exports['exported']))
            with self.assertRaisesRegex(g.WorkflowError, 'allow-paid'):
                g.generate(run, state, argparse.Namespace(execute=True, allow_paid=False))
            self.assertEqual(len(fal.calls), 3)  # paid gate still blocks generation
            original_mask = (run / 'mask.mp4').read_bytes()
            (run / 'mask.mp4').write_bytes(b'changed mask')
            with self.assertRaises(g.WorkflowError): g.generate(run, state, execute)
            self.assertEqual(len(fal.calls), 3)
            (run / 'mask.mp4').write_bytes(original_mask)
            self.assertEqual(g.generate(run, state, plan)['submits'], 0)
            result = g.generate(run, state, execute)
            self.assertEqual(result['stage'], 'awaiting-final-visual-review')
            self.assertEqual(len(fal.calls), 4)
            self.assertEqual(fal.calls[-1][0], g.SEEDANCE)
            self.assertEqual(fal.calls[-1][1]['resolution'], '480p')
            g.generate(run, state, execute)
            self.assertEqual(len(fal.calls), 4)  # repeat does not generate again
        final_exports = json.loads(subprocess.check_output([sys.executable, str(ROOT / 'scripts/genjutsu.py'),
            'export', '--run', str(run), '--output-dir', str(self.base / 'exports')]))
        self.assertEqual(len(final_exports['exported']), 1)
        self.assertEqual(g.sha(final_exports['exported'][0]), g.sha(run / 'final-480p.mp4'))
        self.assertEqual(original_sha, g.sha(self.base / 'source.mp4'))
        self.assertEqual(original_sha, g.sha(run / 'source.mp4'))
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(run / 'composite.mp4'), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        left = raw[(240 * 640 + 160) * 3:(240 * 640 + 160) * 3 + 3]
        right = raw[(240 * 640 + 480) * 3:(240 * 640 + 480) * 3 + 3]
        self.assertGreater(left[2], 220)  # white mask selects depth (blue)
        self.assertGreater(right[0], 220)  # black mask selects original (red)
        # Measure the pitched sine, rather than only verifying the command arguments.
        ff('-i', run / 'pitched-vocals.wav', '-ac', '1', '-c:a', 'pcm_s16le', self.base / 'measure.wav')
        with wave.open(str(self.base / 'measure.wav')) as wav:
            import array
            samples = array.array('h', wav.readframes(wav.getnframes()))
            rate = wav.getframerate()
        samples = samples[rate:rate*3]
        crossings = sum(samples[i-1] <= 0 < samples[i] for i in range(1, len(samples)))
        frequency = crossings / (len(samples) / rate)
        self.assertLess(abs(frequency - 440 * 2**(3/12)), 2)
        # Audio copy is checked internally by media.sh; independently confirm both packet hashes.
        def audio_hash(path):
            return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-c', 'copy', '-f', 'hash', '-hash', 'sha256', '-'])
        self.assertEqual(audio_hash(run / 'source.mp4'), audio_hash(run / 'final-480p.mp4'))


if __name__ == '__main__': unittest.main()
