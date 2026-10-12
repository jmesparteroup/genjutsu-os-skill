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
        payload = g.seedance_payload('https://fal.media/p.mp4', 'https://fal.media/c.png', 'prompt', 4)
        self.assertEqual(payload['resolution'], '480p')
        self.assertFalse(payload['draft'])
        self.assertEqual(payload['task'], 'reference')
        self.assertEqual(payload['duration'], '4')
        for duration in [3, 4.2, 16]:
            with self.assertRaises(g.WorkflowError):
                g.seedance_payload('p', 'c', 'prompt', duration)

    def test_review_is_invalid_after_media_or_prompt_change(self):
        for name in g.REVIEW_FILES:
            (self.run / name).write_bytes(name.encode())
        state = {'source_sha256': 'abc', 'character_sha256': 'def', 'prompt': 'first'}
        fingerprint = g.review_fingerprint(self.run, state)
        state['review'] = {'fingerprint': fingerprint, 'reviewer': 'human', 'evidence': 'message-1'}
        g.require_review(self.run, state)
        (self.run / 'mask.mp4').write_bytes(b'changed')
        with self.assertRaises(g.WorkflowError):
            g.require_review(self.run, state)
        (self.run / 'mask.mp4').write_bytes(b'mask.mp4')
        state['prompt'] = 'second'
        with self.assertRaises(g.WorkflowError):
            g.require_review(self.run, state)

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
