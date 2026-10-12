import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(os.environ.get('GENJUTSU_SKILL_ROOT', Path(__file__).resolve().parents[2] / '.claude/skills/genjutsu-fal-cma'))
spec = importlib.util.spec_from_file_location('genjutsu', ROOT / 'scripts/genjutsu.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class FakeTransport:
    def __init__(self):
        self.submissions = []
        self.status_value = {'status': 'COMPLETED'}
        self.fail_submit = False

    def submit(self, endpoint, payload):
        self.submissions.append((endpoint, payload))
        if self.fail_submit:
            raise TimeoutError('ambiguous response')
        base = 'https://queue.fal.run/' + '/'.join(endpoint.split('/')[:2]) + '/requests/test-123'
        return {'request_id': 'test-123', 'status_url': base + '/status',
                'response_url': base, 'cancel_url': base + '/cancel'}

    def get(self, url):
        if url.endswith('/status'):
            return self.status_value
        return {'video': {'url': 'https://fal.media/test.mp4'}}


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        self.state = {'jobs': {}}
        self.transport = FakeTransport()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_paid_permission_means_no_submit(self):
        with self.assertRaises(g.WorkflowError):
            g.job(self.run, self.state, 'seedance', g.SEEDANCE, {}, False, self.transport)
        self.assertEqual(self.transport.submissions, [])

    def test_restart_collects_existing_request_without_resubmitting(self):
        self.transport.status_value = {'status': 'IN_PROGRESS'}
        self.assertIsNone(g.job(self.run, self.state, 'depth', g.DEPTH, {'video_url': 'x'}, True, self.transport))
        reloaded = json.loads((self.run / 'state.json').read_text())
        self.transport.status_value = {'status': 'COMPLETED'}
        result = g.job(self.run, reloaded, 'depth', g.DEPTH, {'video_url': 'x'}, False, self.transport)
        self.assertEqual(result['video']['url'], 'https://fal.media/test.mp4')
        self.assertEqual(len(self.transport.submissions), 1)

    def test_ambiguous_submit_is_not_retried(self):
        self.transport.fail_submit = True
        with self.assertRaises(TimeoutError):
            g.job(self.run, self.state, 'depth', g.DEPTH, {}, True, self.transport)
        reloaded = json.loads((self.run / 'state.json').read_text())
        with self.assertRaises(g.WorkflowError):
            g.job(self.run, reloaded, 'depth', g.DEPTH, {}, True, self.transport)
        self.assertEqual(len(self.transport.submissions), 1)

    def test_failure_result_cannot_start_another_job(self):
        self.transport.status_value = {'status': 'COMPLETED', 'error': 'model failed'}
        with self.assertRaises(g.WorkflowError):
            g.job(self.run, self.state, 'sam', g.SAM, {}, True, self.transport)
        with self.assertRaises(g.WorkflowError):
            g.job(self.run, self.state, 'sam', g.SAM, {}, True, self.transport)
        self.assertEqual(len(self.transport.submissions), 1)

    def test_payload_change_does_not_reuse_old_job(self):
        self.transport.status_value = {'status': 'IN_PROGRESS'}
        g.job(self.run, self.state, 'depth', g.DEPTH, {'video_url': 'old'}, True, self.transport)
        with self.assertRaises(g.WorkflowError):
            g.job(self.run, self.state, 'depth', g.DEPTH, {'video_url': 'new'}, True, self.transport)

    def test_seedance_invariants_and_whole_second_duration(self):
        for duration in [4, 15, 16, 29, 30]:
            with self.subTest(duration=duration):
                payload = g.seedance_payload('https://fal.media/p.mp4', 'https://fal.media/c.png', 'prompt', duration)
                self.assertEqual(payload['resolution'], '480p')
                self.assertFalse(payload['draft'])
                self.assertEqual(payload['task'], 'reference')
                self.assertEqual(payload['duration'], str(duration))
        for duration in [3, 4.2, 24.75, 30.1, 31]:
            with self.subTest(duration=duration), self.assertRaises(g.WorkflowError):
                g.seedance_payload('p', 'c', 'prompt', duration)

    def test_preparation_is_invalid_after_media_or_prompt_change(self):
        for name in g.REVIEW_FILES:
            (self.run / name).write_bytes(name.encode())
        state = {'source_sha256': 'abc', 'character_sha256': 'def', 'prompt': 'first'}
        fingerprint = g.review_fingerprint(self.run, state)
        state['preparation'] = {'fingerprint': fingerprint}
        g.require_preparation(self.run, state)
        (self.run / 'mask.mp4').write_bytes(b'changed')
        with self.assertRaises(g.WorkflowError):
            g.require_preparation(self.run, state)
        (self.run / 'mask.mp4').write_bytes(b'mask.mp4')
        state['prompt'] = 'second'
        with self.assertRaises(g.WorkflowError):
            g.require_preparation(self.run, state)

    def test_preparation_required_without_human_review(self):
        with self.assertRaisesRegex(g.WorkflowError, 'build-review'):
            g.require_preparation(self.run, {})

    def test_legacy_validated_run_remains_resumable(self):
        for name in g.REVIEW_FILES:
            (self.run / name).write_bytes(name.encode())
        state = {'source_sha256': 'abc', 'character_sha256': 'def', 'prompt': 'first'}
        state['review'] = {'fingerprint': g.review_fingerprint(self.run, state),
                           'reviewer': 'legacy user', 'evidence': 'existing review'}
        g.require_preparation(self.run, state)
        (self.run / 'mask.mp4').write_bytes(b'changed')
        with self.assertRaises(g.WorkflowError):
            g.require_preparation(self.run, state)

    def test_saved_sam_rle_is_collected_without_another_submission(self):
        for name in ('vocals.wav', 'depth.mp4'):
            (self.run / name).write_bytes(b'fixture')
        rle = {'rle': ['1 3', '2 2'], 'metadata': [{'index': 0}, {'index': 1}]}
        state = {'subject': 'person', 'jobs': {
            'vocals': {'phase': 'completed', 'result': {'vocals': {'url': 'https://fal.media/v.wav'}}},
            'depth': {'phase': 'completed', 'result': {'video': {'url': 'https://fal.media/d.mp4'}}},
            'sam': {'phase': 'completed', 'request_id': 'sam-done', 'result': rle}}}
        with patch.object(g, 'originals'), patch.object(g, 'download'), \
             patch.object(g, 'Transport', return_value=self.transport), \
             patch.object(g, 'upload', side_effect=AssertionError('Unexpected upload')), \
             patch.object(g, 'job', side_effect=AssertionError('Completed RLE should be collected locally')):
            result = g.prepare(self.run, state, types.SimpleNamespace(execute=True, allow_paid=False))
        self.assertEqual(result['stage'], 'mask-required')
        self.assertEqual(json.loads(Path(result['rle']).read_text()), rle)
        self.assertEqual(self.transport.submissions, [])

    def test_two_reference_payload_preserves_order(self):
        payload = g.seedance_payload('video', ['luca', 'thomas'], 'prompt', 15)
        self.assertEqual(payload['image_urls'], ['luca', 'thomas'])
        self.assertEqual(payload['resolution'], '480p')
        for images in ([], ['one', 'two', 'three']):
            with self.assertRaises(g.WorkflowError):
                g.seedance_payload('video', images, 'prompt', 15)

    def test_second_reference_is_bound_to_originals_and_preparation(self):
        for name in (*g.REVIEW_FILES, 'source.mp4', 'character.png', 'character2.png'):
            (self.run / name).write_bytes(name.encode())
        state = {'source': 'source.mp4', 'character': 'character.png',
                 'source_sha256': g.sha(self.run / 'source.mp4'),
                 'character_sha256': g.sha(self.run / 'character.png'),
                 'character2': 'character2.png', 'character2_sha256': g.sha(self.run / 'character2.png'),
                 'prompt': '@Image1 left @Image2 right'}
        state['preparation'] = {'fingerprint': g.review_fingerprint(self.run, state)}
        g.originals(self.run, state)
        g.require_preparation(self.run, state)
        (self.run / 'character2.png').write_bytes(b'changed second portrait')
        with self.assertRaises(g.WorkflowError):
            g.originals(self.run, state)
        state['character2_sha256'] = g.sha(self.run / 'character2.png')
        with self.assertRaises(g.WorkflowError):
            g.require_preparation(self.run, state)

    def test_generate_uploads_both_portraits_in_order(self):
        state = {'jobs': {}, 'character': 'luca.png', 'character2': 'thomas.png',
                 'prompt': '@Image1 left @Image2 right', 'duration': 15}
        with patch.object(g, 'originals'), patch.object(g, 'require_preparation'), patch.object(g, 'reference_check'), \
             patch.object(g, 'Transport'), patch.object(g, 'upload', side_effect=lambda r,s,n,t:n), \
             patch.object(g, 'job', side_effect=lambda r,s,n,e,p,a,t: s['jobs'].update(seedance={'request_id':'test'})) as job:
            g.generate(self.run, state, types.SimpleNamespace(execute=True, allow_paid=True))
        self.assertEqual(job.call_args.args[4]['image_urls'], ['luca.png', 'thomas.png'])

    def test_queue_auth_cannot_be_sent_to_other_hosts(self):
        for url in ['http://queue.fal.run/x', 'https://evil.test/x', 'https://queue.fal.run.evil.test/x']:
            with self.assertRaises(g.WorkflowError):
                g.queue_url(url)

    def test_adoption_record_cannot_mix_request_ids(self):
        record = self.transport.submit(g.DEPTH, {})
        record['request_id'] = 'different'
        with self.assertRaises(g.WorkflowError):
            g.request_record(record, g.DEPTH)

    def test_authenticated_redirects_stop(self):
        with self.assertRaises(g.WorkflowError):
            g.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')

    def test_upload_uses_verbatim_runtime_placeholder(self):
        sdk = types.SimpleNamespace(SyncClient=Mock())
        sdk.SyncClient.return_value.upload_file.return_value = 'https://fal.media/upload.wav'
        with patch.dict(os.environ, {'FAL_KEY': 'opaque-placeholder'}), patch.dict('sys.modules', {'fal_client': sdk}):
            transport = g.Transport()
            self.assertEqual(transport.upload(Path('fixture.wav')), 'https://fal.media/upload.wav')
        sdk.SyncClient.assert_called_once_with(key='opaque-placeholder', default_timeout=30)


if __name__ == '__main__':
    unittest.main()
