#!/usr/bin/env python3
"""Create a credential-free CMA skill ZIP and SHA-256 manifest offline."""
import hashlib
import json
import zipfile
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
skill = repo / '.claude/skills/genjutsu-fal-cma'
dist = repo / 'dist'
dist.mkdir(exist_ok=True)
files = sorted(p for p in skill.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
allowed = {'.md', '.py', '.sh', '.yaml', '.txt'}
assert (skill / 'SKILL.md').is_file(), 'Skill entrypoint missing'
assert all(p.suffix in allowed and not p.is_symlink() for p in files), 'Unexpected bundle file'
archive = dist / 'genjutsu-fal-cma.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in files:
        info = zipfile.ZipInfo('genjutsu-fal-cma/' + path.relative_to(skill).as_posix(), (2026, 10, 11, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        z.writestr(info, path.read_bytes())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None, 'ZIP integrity check failed'
manifest = {'files': {p.relative_to(skill).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
(dist / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(archive)
