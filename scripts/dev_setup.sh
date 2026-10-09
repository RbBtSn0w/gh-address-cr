#!/usr/bin/env bash
# Create (or refresh) the repository's development virtual environment.
#
#   scripts/dev_setup.sh                       # ./.venv with the default python3
#   scripts/dev_setup.sh --python python3.13   # pick the interpreter
#   scripts/dev_setup.sh --venv /path/to/venv  # pick the location
#
# Why a venv: `pip install -e .` into a system or Homebrew Python writes a
# `gh-address-cr` script into that Python's bin directory (for Homebrew,
# /opt/homebrew/bin). That script shadows the released CLI, keeps reporting the
# development version, and makes `brew link` fail with "Target already exists".
# Inside a venv the entrypoint stays under the venv, so the released CLI on PATH
# is untouched. Activate with `source .venv/bin/activate` before running tests.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

usage() {
    sed -n '2,13p' "${script_dir}/$(basename "${BASH_SOURCE[0]}")" | sed 's/^# \{0,1\}//' >&2
    echo "Options: --python <interpreter> (default python3)  --venv <dir> (default ${repo_root}/.venv)" >&2
}

python_bin="python3"
venv_dir="${repo_root}/.venv"
while [ $# -gt 0 ]; do
    case "$1" in
        --python) [ $# -ge 2 ] || { usage; exit 2; }; python_bin="$2"; shift 2 ;;
        --venv) [ $# -ge 2 ] || { usage; exit 2; }; venv_dir="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "dev_setup: unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

command -v "${python_bin}" >/dev/null 2>&1 || { echo "dev_setup: interpreter not found: ${python_bin}" >&2; exit 1; }
"${python_bin}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || { echo "dev_setup: ${python_bin} is older than Python 3.12 (required by pyproject.toml)" >&2; exit 1; }

if [ ! -x "${venv_dir}/bin/python" ]; then
    echo "dev_setup: creating ${venv_dir}" >&2
    "${python_bin}" -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || { echo "dev_setup: ${venv_dir}/bin/python is older than Python 3.12 (required by pyproject.toml); remove ${venv_dir} and rerun" >&2; exit 1; }

"${venv_dir}/bin/python" -m pip install --quiet --upgrade pip
"${venv_dir}/bin/python" -m pip install --quiet -e "${repo_root}[dev]"

echo "dev_setup: ready. Activate with: source ${venv_dir}/bin/activate" >&2
