#!/usr/bin/env python3
"""Staged Genjutsu orchestration. No model call without --execute --allow-paid."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DEMUCS = 'fal-ai/demucs'
DEPTH = 'fal-ai/depth-anything-video'
SAM = 'fal-ai/sam-3/video-rle'
SEEDANCE = 'bytedance/seedance-2.5/reference-to-video'
REVIEW_FILES = ('working.mp4', 'vocals.wav', 'depth.mp4', 'mask.mp4',
                'pitched-vocals.wav', 'composite.mp4', 'prepared-review.mp4')
DEFAULT_PROMPT = ('Use @Video1 as exact motion, framing, camera, background and timing guidance. '
                  'Replace the colored-depth subject with the character in @Image1, including '
                  'face, hair, clothing and body. Preserve gestures and lip timing from the '
                  'embedded vocals. Keep the original background. Depth colors are guidance '
                  'only and must disappear completely. Do not add cuts, subtitles, logos or watermarks.')


class WorkflowError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WorkflowError('Authenticated FAL request redirected; inspect before continuing.')


def check(condition, message):
    if not condition:
        raise WorkflowError(message)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(run, state):
    tmp = run / 'state.json.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, run / 'state.json')


def queue_url(url):
    p = urlparse(url)
    check(p.scheme == 'https' and p.netloc == 'queue.fal.run', 'Invalid FAL queue URL.')
    return url


def request_record(reply, endpoint):
    request_id = reply.get('request_id', '')
    check(isinstance(request_id, str) and bool(re.fullmatch(r'[A-Za-z0-9-]+', request_id)), 'Invalid request ID.')
    root = '/' + '/'.join(endpoint.split('/')[:2]) + '/'
    for field, suffix in (('status_url', '/status'), ('response_url', ''), ('cancel_url', '/cancel')):
        url = queue_url(reply[field])
        path = urlparse(url).path
        expected = '/requests/' + request_id + suffix
        valid = path.endswith(expected)
        if field == 'response_url':
            valid |= path.endswith(expected + '/response')
        check(path.startswith(root) and valid, 'Queue URLs do not match the endpoint and request ID.')
    return {k: reply[k] for k in ('request_id', 'status_url', 'response_url', 'cancel_url')}


class Transport:
    def __init__(self):
        key = os.environ.get('FAL_KEY')
        check(bool(key), 'FAL_KEY is not supplied by the runtime. Do not paste it into prompts.')
        self.key = key

    def request(self, url, payload=None):
        queue_url(url)
        req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={'Authorization': 'Key ' + self.key, 'Content-Type': 'application/json'})
        # No POST retries. A network error can mean the job was accepted.
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            return json.load(response)

    def submit(self, endpoint, payload):
        return self.request('https://queue.fal.run/' + endpoint, payload)

    def get(self, url):
        return self.request(url)

    def upload(self, path):
        import fal_client
        return fal_client.SyncClient(key=self.key, default_timeout=30).upload_file(path)


def job(run, state, name, endpoint, payload, allow_paid, transport):
    jobs = state.setdefault('jobs', {})
    signature = digest({'endpoint': endpoint, 'input': payload})
    entry = jobs.get(name)
    if entry:
        check(entry['signature'] == signature, 'Job inputs changed; create a fresh run instead of reusing a request.')
        check(entry['phase'] != 'submitting', 'Submission outcome unknown. Reconcile in FAL and use adopt; do not resubmit.')
        check(entry['phase'] != 'failed', 'Job failed. No automatic paid retry; inspect FAL and use a fresh run if authorized.')
        if 'result' in entry:
            return entry['result']
    else:
        check(allow_paid, 'A new model request requires explicit --allow-paid authorization.')
        entry = {'endpoint': endpoint, 'signature': signature, 'phase': 'submitting'}
        jobs[name] = entry
        save(run, state)  # Write intent before sending the paid POST.
        reply = transport.submit(endpoint, payload)
        entry.update(request_record(reply, endpoint))
        entry['phase'] = 'submitted'
        save(run, state)
    status = transport.get(entry['status_url'])
    entry['status'] = status.get('status')
    if status.get('error'):
        entry['phase'] = 'failed'
        save(run, state)
        raise WorkflowError('FAL job failed. Request ID: ' + entry['request_id'])
    if status.get('status') != 'COMPLETED':
        save(run, state)
        return None
    try:
        result = transport.get(entry['response_url'])
    except urllib.error.HTTPError as e:
        if e.code in (400, 422):
            entry['phase'] = 'failed'
            save(run, state)
        raise
    if result.get('error'):
        entry['phase'] = 'failed'
        save(run, state)
        raise WorkflowError('FAL returned an error result; inspect the saved request.')
    entry.update(phase='completed', result=result)
    save(run, state)
    return result


def upload(run, state, name, transport):
    path = run / name
    signature = sha(path)
    cached = state.setdefault('uploads', {}).get(name)
    if cached and cached['sha256'] == signature:
        return cached['url']
    url = transport.upload(path)
    check(urlparse(url).scheme == 'https', 'FAL upload did not return HTTPS.')
    state['uploads'][name] = {'sha256': signature, 'url': url}
    save(run, state)
    return url


def output_url(result, field):
    value = result[field]
    return value if isinstance(value, str) else value['url']


def download(run, state, name, url):
    path = run / name
    cached = state.setdefault('downloads', {}).get(name)
    if cached and path.exists() and cached['url'] == url and sha(path) == cached['sha256']:
        return
    check(urlparse(url).scheme == 'https', 'Media download must use HTTPS.')
    part = run / (name + '.part')
    try:
        with urllib.request.urlopen(url, timeout=30) as response, open(part, 'wb') as f:
            size = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                check(size <= 1024**3, 'Download exceeds 1 GiB; stop and inspect output.')
                f.write(block)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    state['downloads'][name] = {'url': url, 'sha256': sha(path)}
    save(run, state)


def media(*args):
    subprocess.run(['bash', str(HERE / 'media.sh'), *map(str, args)], check=True)


def probe(path):
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                                   '-show_format', '-of', 'json', str(path)])
    data = json.loads(out)
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
    return data, video, audio


def seedance_payload(video_url, character_url, prompt, duration):
    check(float(duration).is_integer() and 4 <= float(duration) <= 15,
          'This skill supports exact whole-second clips from 4 to 15 seconds; do not trim or round silently.')
    return {'video_urls': [video_url], 'image_urls': [character_url], 'prompt': prompt,
            'task': 'reference', 'resolution': '480p', 'draft': False, 'duration': str(int(duration)),
            'aspect_ratio': 'auto', 'generate_audio': True, 'codec': 'H264'}


def reference_check(path):
    data, v, a = probe(path)
    check(v is not None, 'Reference video is missing.')
    from fractions import Fraction
    check(300 <= v['width'] <= 6000 and 300 <= v['height'] <= 6000,
          'Reference dimensions must be 300–6000 per side. Supply a suitable source.')
    check(0.4 <= v['width'] / v['height'] <= 2.5, 'Reference aspect ratio is outside 0.4–2.5.')
    check(24 <= float(Fraction(v['r_frame_rate'])) <= 60, 'Reference fps must be 24–60.')
    check(path.stat().st_size <= 200 * 1024**2, 'Reference video exceeds 200 MB.')
    return data, v, a


def originals(run, state):
    for name, field in ((state['source'], 'source_sha256'), (state['character'], 'character_sha256')):
        check(sha(run / name) == state[field], 'Original input changed; create a fresh run.')


def review_fingerprint(run, state):
    return digest({'files': {name: sha(run / name) for name in REVIEW_FILES},
                   'source': state['source_sha256'], 'character': state['character_sha256'],
                   'prompt': state['prompt']})


def require_review(run, state):
    approval = state.get('review', {})
    check(bool(approval.get('reviewer') and approval.get('evidence')), 'Human mask and prepared-video review is required.')
    check(approval.get('fingerprint') == review_fingerprint(run, state), 'Review is stale; media or prompt changed.')


def init(args):
    run = Path(args.run).resolve()
    check(not run.exists(), 'Run directory already exists. Choose a fresh directory.')
    source, character = Path(args.source).resolve(), Path(args.character).resolve()
    check(source.is_file() and character.is_file(), 'Source clip and character image are required.')
    check(character.stat().st_size <= 30 * 1024**2, 'Character image exceeds 30 MB.')
    check(character.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif', '.heic', '.heif'),
          'Unsupported character image extension.')
    data, v, a = probe(source)
    check(v is not None and a is not None, 'Source needs video and an audible first audio stream.')
    duration = float(data['format']['duration'])
    check(abs(duration - round(duration)) <= 0.085, 'Source duration is not within 85 ms of a whole second.')
    seedance_payload('', '', '', round(duration))
    check(abs(float(v.get('start_time', 0)) - float(a.get('start_time', 0))) <= 0.085,
          'Source audio/video start times differ; timing needs explicit handling before this workflow.')
    prompt = Path(args.prompt_file).read_text().strip() if args.prompt_file else DEFAULT_PROMPT
    check(bool(prompt), 'Prompt is empty.')
    run.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.genjutsu-init-', dir=run.parent) as tmp:
        work = Path(tmp)
        source_name = 'source' + source.suffix.lower()
        character_name = 'character' + character.suffix.lower()
        shutil.copy2(source, work / source_name)
        shutil.copy2(character, work / character_name)
        media('extract', work / source_name, work / 'working.mp4', work / 'original-audio.wav')
        reference_check(work / 'working.mp4')
        state = {'version': 1, 'source': source_name, 'character': character_name,
                 'source_sha256': sha(work / source_name), 'character_sha256': sha(work / character_name),
                 'duration': round(duration), 'prompt': prompt, 'subject': args.subject, 'jobs': {}}
        save(work, state)
        os.rename(work, run)
    return {'stage': 'initialized', 'run': str(run), 'duration': state['duration'], 'paid_requests': 0}


def prepare(run, state, args):
    originals(run, state)
    plan = [(DEMUCS, 'original-audio.wav → vocals.wav'), (DEPTH, 'working.mp4 → depth.mp4'),
            (SAM, 'depth.mp4 → segmentation-candidate.mp4 (not automatically a mask)')]
    if not args.execute:
        return {'plan': plan, 'submits': 0, 'existing_jobs': {k: v['phase'] for k, v in state['jobs'].items()}}
    # One stage per invocation: submit at most one new paid job, poll once, then return.
    transport = Transport()
    steps = [('vocals', DEMUCS, 'vocals.wav', 'vocals'), ('depth', DEPTH, 'depth.mp4', 'video'),
             ('sam', SAM, 'segmentation-candidate.mp4', 'video')]
    for name, endpoint, target, field in steps:
        entry = state['jobs'].get(name, {})
        if entry.get('phase') == 'completed' and (run / target).exists():
            download(run, state, target, output_url(entry['result'], field))
            continue
        check(name in state['jobs'] or args.allow_paid, 'A new preparation job needs --allow-paid.')
        if name == 'vocals':
            payload = {'audio_url': upload(run, state, 'original-audio.wav', transport),
                       'model': 'htdemucs', 'stems': ['vocals'], 'output_format': 'wav'}
        elif name == 'depth':
            payload = {'video_url': upload(run, state, 'working.mp4', transport),
                       'model': 'VDA-Large', 'colormap': 'turbo', 'resolution': 'auto', 'output_fps': 24}
        else:
            payload = {'video_url': output_url(state['jobs']['depth']['result'], 'video'),
                       'prompt': state['subject'], 'apply_mask': False, 'boundingbox_zip': False}
        result = job(run, state, name, endpoint, payload, args.allow_paid, transport)
        if result is not None:
            download(run, state, target, output_url(result, field))
        return {'stage': name, 'request_id': state['jobs'][name].get('request_id'),
                'status': 'downloaded' if result is not None else 'pending', 'next': 'repeat prepare --execute'}
    return {'stage': 'mask-required', 'candidate': str(run / 'segmentation-candidate.mp4'),
            'next': 'Inspect candidate. Supply a verified binary mask to build-review; do not assume SAM video is a mask.'}


def build_review(run, state, args):
    originals(run, state)
    check('seedance' not in state['jobs'], 'Generation already has an intent/request; use a fresh run for changes.')
    check((run / 'vocals.wav').is_file() and (run / 'depth.mp4').is_file(), 'Preparation outputs are missing.')
    with tempfile.TemporaryDirectory(prefix='review-build-', dir=run) as tmp:
        work = Path(tmp)
        shutil.copy2(args.mask, work / 'mask.mp4')
        subprocess.run([sys.executable, str(HERE / 'validate_mask.py'), '--working', str(run / 'working.mp4'),
                        '--depth', str(run / 'depth.mp4'), '--mask', str(work / 'mask.mp4'),
                        '--report', str(work / 'mask-report.json')], check=True)
        media('pitch', run / 'vocals.wav', work / 'pitched-vocals.wav')
        media('composite', run / 'working.mp4', run / 'depth.mp4', work / 'mask.mp4', work / 'composite.mp4')
        media('embed', work / 'composite.mp4', work / 'pitched-vocals.wav', work / 'prepared-review.mp4')
        reference_check(work / 'prepared-review.mp4')
        for path in work.iterdir():
            os.replace(path, run / path.name)
    state.pop('review', None)
    save(run, state)
    return {'stage': 'awaiting-human-review', 'video': str(run / 'prepared-review.mp4'),
            'mask': str(run / 'mask.mp4'), 'numeric_report': str(run / 'mask-report.json')}


def generate(run, state, args):
    originals(run, state)
    require_review(run, state)
    reference_check(run / 'prepared-review.mp4')
    if not args.execute:
        return {'endpoint': SEEDANCE, 'input': seedance_payload('<reviewed-video>', '<character>', state['prompt'], state['duration']),
                'submits': 0, 'review': state['review']}
    check('seedance' in state['jobs'] or args.allow_paid, 'Generation requires --allow-paid.')
    transport = Transport()
    payload = seedance_payload(upload(run, state, 'prepared-review.mp4', transport),
                               upload(run, state, state['character'], transport), state['prompt'], state['duration'])
    result = job(run, state, 'seedance', SEEDANCE, payload, args.allow_paid, transport)
    if result is None:
        return {'stage': 'seedance-pending', 'request_id': state['jobs']['seedance']['request_id'], 'next': 'repeat generate --execute'}
    download(run, state, 'generated-480p.mp4', output_url(result, 'video'))
    _, v, _ = probe(run / 'generated-480p.mp4')
    check(v is not None and min(v['width'], v['height']) == 480,
          'Returned video does not have a 480-pixel short side; stop and inspect. No HD/downscale fallback.')
    if not (run / 'final-480p.mp4').exists():
        with tempfile.TemporaryDirectory(prefix='restore-', dir=run) as tmp:
            final = Path(tmp) / 'final.mp4'
            media('restore', run / 'generated-480p.mp4', run / state['source'], final)
            os.replace(final, run / 'final-480p.mp4')
        state['final_sha256'] = sha(run / 'final-480p.mp4')
        save(run, state)
    check(sha(run / 'final-480p.mp4') == state.get('final_sha256'), 'Final export changed; inspect instead of overwriting.')
    return {'stage': 'awaiting-final-visual-review', 'video': str(run / 'final-480p.mp4'),
            'audio': 'First original audio stream packet hash verified; other audio tracks are not copied.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('init'); q.add_argument('--run', required=True); q.add_argument('--source', required=True)
    q.add_argument('--character', required=True); q.add_argument('--subject', default='person'); q.add_argument('--prompt-file')
    for command in ('prepare', 'generate'):
        q = sub.add_parser(command); q.add_argument('--run', required=True)
        q.add_argument('--execute', action='store_true'); q.add_argument('--allow-paid', action='store_true')
    q = sub.add_parser('build-review'); q.add_argument('--run', required=True); q.add_argument('--mask', required=True)
    q = sub.add_parser('approve-review'); q.add_argument('--run', required=True); q.add_argument('--reviewer', required=True)
    q.add_argument('--evidence', required=True); q.add_argument('--reviewed-full-clip', action='store_true', required=True)
    q.add_argument('--reviewed-mask', action='store_true', required=True)
    q = sub.add_parser('adopt'); q.add_argument('--run', required=True); q.add_argument('--job', choices=('vocals', 'depth', 'sam', 'seedance'), required=True)
    q.add_argument('--request-json', required=True)
    q = sub.add_parser('export'); q.add_argument('--run', required=True); q.add_argument('--output-dir', required=True)
    q = sub.add_parser('status'); q.add_argument('--run', required=True)
    args = p.parse_args()
    if args.command == 'init':
        result = init(args)
    else:
        run = Path(args.run).resolve()
        check((run / 'state.json').is_file(), 'Run not initialized.')
        with open(run / '.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkflowError('Another command is using this run.')
            state = json.loads((run / 'state.json').read_text())
            if args.command == 'prepare': result = prepare(run, state, args)
            elif args.command == 'generate': result = generate(run, state, args)
            elif args.command == 'build-review': result = build_review(run, state, args)
            elif args.command == 'approve-review':
                originals(run, state)
                check('seedance' not in state['jobs'], 'Cannot replace approval after generation begins.')
                state['review'] = {'fingerprint': review_fingerprint(run, state), 'reviewer': args.reviewer, 'evidence': args.evidence}
                save(run, state); result = {'stage': 'review-recorded', 'paid_requests': 0}
            elif args.command == 'adopt':
                entry = state['jobs'].get(args.job, {})
                check(entry.get('phase') == 'submitting', 'Only an ambiguous submission can be adopted.')
                reply = json.loads(Path(args.request_json).read_text())
                entry.update(request_record(reply, entry['endpoint']))
                entry['phase'] = 'submitted'; save(run, state); result = {'stage': 'adopted', 'paid_requests': 0}
            elif args.command == 'export':
                out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
                names = ('final-480p.mp4',) if state.get('final_sha256') else ('prepared-review.mp4', 'mask.mp4', 'mask-report.json')
                for name in names:
                    check((run / name).is_file(), 'Review/export media missing.')
                    target = out / (run.name + '-' + name)
                    check(not target.exists() or sha(target) == sha(run / name), 'Export path contains a different file.')
                    if not target.exists(): shutil.copy2(run / name, target)
                result = {'exported': [str(out / (run.name + '-' + n)) for n in names]}
            else:
                result = {'run': str(run), 'jobs': {k: {'phase': v['phase'], 'request_id': v.get('request_id')} for k, v in state['jobs'].items()},
                          'review_recorded': bool(state.get('review')), 'final_exists': (run / 'final-480p.mp4').exists()}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except WorkflowError as e:
        print('STOP: ' + str(e), file=sys.stderr); sys.exit(2)
    except Exception as e:
        # Avoid echoing credentials, signed URLs, or remote error bodies.
        print('STOP: ' + type(e).__name__ + '. Inspect local dependencies or the saved request in FAL. No automatic resubmission.', file=sys.stderr)
        sys.exit(3)
