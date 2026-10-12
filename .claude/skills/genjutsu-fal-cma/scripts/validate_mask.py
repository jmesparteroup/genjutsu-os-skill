#!/usr/bin/env python3
"""Validate all mask frames numerically; this does not establish subject semantics."""
import argparse
import json
import subprocess
import numpy as np
from fractions import Fraction
from pathlib import Path


def timeline(path):
    data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-show_frames', '-show_entries',
        'stream=width,height,r_frame_rate:frame=best_effort_timestamp_time', '-of', 'json', str(path)]))
    stream = data['streams'][0]
    times = [float(f['best_effort_timestamp_time']) for f in data['frames']]
    if not times or abs(times[0]) > 0.001:
        raise ValueError('Video must start at time zero and have timestamped frames.')
    if abs(float(Fraction(stream['r_frame_rate'])) - 24) > 0.001:
        raise ValueError('Video must be 24 fps.')
    if any(abs(t - i / 24) > 0.002 for i, t in enumerate(times)):
        raise ValueError('Video frame timestamps must follow an uninterrupted 24 fps timeline.')
    return stream['width'], stream['height'], len(times)


def validate(working, mask, depth=None):
    expected = timeline(working)
    if timeline(mask) != expected or (depth and timeline(depth) != expected):
        raise ValueError('Working, depth and mask timelines/dimensions do not match.')
    width, height, frames = expected
    frame_size = width * height * 3
    process = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', str(mask), '-map', '0:v:0',
                                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    coverage, fractions = [], []
    try:
        for index in range(frames):
            raw = bytearray()
            while len(raw) < frame_size:
                block = process.stdout.read(frame_size - len(raw))
                if not block:
                    raise ValueError('Mask decode ended before the expected frame count.')
                raw.extend(block)
            # Inspect RGB before grayscale conversion: a colored overlay cannot masquerade as a mask.
            rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
            high, low = rgb.max(axis=1), rgb.min(axis=1)
            colored = np.count_nonzero(high - low > 4)
            intermediate = np.count_nonzero((high > 12) & (low < 243))
            white = np.count_nonzero(low >= 243)
            pixels = width * height
            if colored / pixels > 0.001 or intermediate / pixels > 0.02:
                raise ValueError(f'Mask frame {index} is colored or contains too many gray pixels. Obtain a binary mask; do not threshold an overlay.')
            coverage.append(float(white / pixels))
            fractions.append(float(intermediate / pixels))
        if process.stdout.read(1):
            raise ValueError('Mask decode has extra frames.')
        if process.wait() != 0:
            raise ValueError('FFmpeg mask decode failed.')
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
    if max(coverage) < 0.001 or min(coverage) > 0.999:
        raise ValueError('Mask is empty or fills the entire clip; inspect subject selection.')
    return {'frames_checked': frames, 'width': width, 'height': height, 'fps': 24,
            'white_fraction_per_frame': coverage, 'max_gray_fraction': max(fractions),
            'semantics': 'UNVERIFIED: human must confirm white is subject, black is background for the entire clip.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--working', required=True); p.add_argument('--mask', required=True)
    p.add_argument('--depth'); p.add_argument('--report', required=True)
    args = p.parse_args()
    report = validate(args.working, args.mask, args.depth)
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(f'Checked {report["frames_checked"]} mask frames. Automatic mask checks passed; manual review is optional.')
