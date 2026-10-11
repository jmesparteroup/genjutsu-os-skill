#!/usr/bin/env python3
"""No-network dependency and codec check. Does not load or print credentials."""
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

report = {'python': sys.version.split()[0], 'checks': {}}
failed = sys.version_info < (3, 10)
for binary, args in [('ffmpeg', ['-version']), ('ffprobe', ['-version']), ('rubberband', ['--version'])]:
    path = shutil.which(binary)
    try:
        result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=15)
        ok = result.returncode == 0
        report['checks'][binary] = {'path': path, 'executable': ok,
                                   'version': (result.stdout or result.stderr).splitlines()[0]}
        failed |= not ok
    except Exception as e:
        report['checks'][binary] = {'path': path, 'executable': False, 'error': type(e).__name__}
        failed = True
try:
    version = importlib.metadata.version('fal-client')
    import fal_client
    report['checks']['fal-client'] = {'version': version, 'expected': '1.0.3'}
    failed |= version != '1.0.3'
except Exception as e:
    report['checks']['fal-client'] = {'error': type(e).__name__}
    failed = True
try:
    import numpy
    report['checks']['numpy'] = {'version': numpy.__version__, 'expected': '2.2.6'}
    failed |= numpy.__version__ != '2.2.6'
except Exception as e:
    report['checks']['numpy'] = {'error': type(e).__name__}
    failed = True
if report['checks']['ffmpeg'].get('executable'):
    # Real encode + required filter execution, rather than just searching a capabilities list.
    with tempfile.TemporaryDirectory(prefix='genjutsu-doctor-') as tmp:
        path = Path(tmp) / 'probe.mp4'
        result = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=64x64:r=24:d=0.2',
            '-f', 'lavfi', '-i', 'color=blue:s=64x64:r=24:d=0.2', '-f', 'lavfi', '-i', 'color=white:s=64x64:r=24:d=0.2',
            '-filter_complex', '[0:v][1:v][2:v]maskedmerge[v]', '-map', '[v]', '-c:v', 'libx264', str(path)],
            capture_output=True, timeout=30)
        report['checks']['h264_maskedmerge'] = result.returncode == 0
        failed |= result.returncode != 0
report['ok'] = not failed
print(json.dumps(report, indent=2))
sys.exit(1 if failed else 0)
