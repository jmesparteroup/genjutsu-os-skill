#!/usr/bin/env bash
# Explicit, Linux-only fallback. CMA environment packages are preferred.
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Use the CMA Linux environment; this script does not repair macOS packages.' >&2; exit 2; }
[[ "${1:-}" == --install ]] || { echo 'Usage: bash bootstrap.sh --install [venv-directory]'; exit 2; }
genjutsu_venv="${2:-/workspace/.venvs/genjutsu-fal-cma}"
if [[ "$(id -u)" == 0 ]]; then
  apt-get update
  apt-get install -y --no-install-recommends ffmpeg rubberband-cli python3-venv ca-certificates
else
  echo 'System dependencies require environment packages or a prepared container. Configure assets/environment.yaml.' >&2
  exit 2
fi
python3 -m venv "$genjutsu_venv"
"$genjutsu_venv/bin/python" -m pip install -r "$(dirname "$0")/../assets/requirements.txt"
"$genjutsu_venv/bin/python" "$(dirname "$0")/doctor.py"
echo "Run scripts with $genjutsu_venv/bin/python"
