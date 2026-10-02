#!/usr/bin/env bash
# Pin an unreleased gh-address-cr runtime for dogfooding, and print the shell
# exports that select it.
#
#   eval "$(scripts/dogfood_env.sh)"                # pin HEAD's commit
#   eval "$(scripts/dogfood_env.sh --ref develop)"  # pin develop's commit
#   eval "$(scripts/dogfood_env.sh --no-install)"   # reuse the last pinned build
#
# Why a pinned install: `gh-address-cr` on PATH is usually the released package,
# and `python3 -m gh_address_cr` from an editable install follows whatever
# branch is checked out. Addressing a PR means checking out its branch, which
# would silently change the runtime under test. This installs the chosen commit
# non-editably into its own venv, so the runtime stays fixed while you switch
# branches. Its efficiency reports carry `runtime.origin=vcs` and the commit,
# which `scripts/compare_telemetry_by_runtime.py` can compare with a release.
#
# Only stdout carries the exports; progress goes to stderr. Uncommitted changes
# are never part of the build.
set -euo pipefail

usage() {
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' >&2
    echo "Options: --ref <git-ref> (default HEAD)  --no-install  --home <dir>" >&2
    echo "Environment: GH_ADDRESS_CR_DOGFOOD_HOME (default ~/.cache/gh-address-cr-dogfood)" >&2
}

ref="HEAD"
install=1
home="${GH_ADDRESS_CR_DOGFOOD_HOME:-${HOME}/.cache/gh-address-cr-dogfood}"
while [ $# -gt 0 ]; do
    case "$1" in
        --ref) [ $# -ge 2 ] || { usage; exit 2; }; ref="$2"; shift 2 ;;
        --no-install) install=0; shift ;;
        --home) [ $# -ge 2 ] || { usage; exit 2; }; home="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "dogfood_env: unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

venv="${home}/venv"
state="${home}/state"

if [ "$install" -eq 1 ]; then
    repo_root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
    if ! sha="$(git -C "$repo_root" rev-parse --verify --quiet "${ref}^{commit}")"; then
        echo "dogfood_env: '${ref}' is not a commit in ${repo_root}" >&2
        exit 2
    fi
    if [ "$sha" = "$(git -C "$repo_root" rev-parse HEAD)" ] && [ -n "$(git -C "$repo_root" status --porcelain --untracked-files=no)" ]; then
        echo "dogfood_env: warning: uncommitted changes are not part of the pinned build" >&2
    fi
    echo "dogfood_env: installing ${sha:0:12} into ${venv}" >&2
    [ -x "${venv}/bin/python" ] || python3 -m venv "$venv" >&2
    "${venv}/bin/python" -m pip install --quiet --upgrade pip >&2
    "${venv}/bin/python" -m pip install --quiet --force-reinstall "git+file://${repo_root}@${sha}" >&2
    installed="$("${venv}/bin/python" - <<'PY'
import json
from importlib import metadata

raw = metadata.distribution("gh-address-cr").read_text("direct_url.json") or "{}"
print((json.loads(raw).get("vcs_info") or {}).get("commit_id", ""))
PY
)"
    if [ "$installed" != "$sha" ]; then
        echo "dogfood_env: installed commit '${installed}' does not match ${sha}" >&2
        exit 1
    fi
fi

if [ ! -x "${venv}/bin/gh-address-cr" ]; then
    echo "dogfood_env: no pinned runtime in ${venv}; run without --no-install first" >&2
    exit 2
fi
mkdir -p "$state"

label="$("${venv}/bin/python" - <<'PY'
import json
from importlib import metadata

raw = metadata.distribution("gh-address-cr").read_text("direct_url.json")
direct_url = json.loads(raw) if raw else {}
commit = (direct_url.get("vcs_info") or {}).get("commit_id")
if commit:
    origin = f"vcs {commit[:12]}"
elif (direct_url.get("dir_info") or {}).get("editable"):
    origin = "editable"
else:
    origin = "package" if not direct_url else "local"
print(f"{metadata.version('gh-address-cr')} {origin}")
PY
)"
echo "dogfood_env: runtime ${label}" >&2

printf '# gh-address-cr dogfood runtime: %s\n' "$label"
# $PATH stays literal on purpose: it must expand in the caller's shell at eval time.
# shellcheck disable=SC2016
printf 'export PATH=%q:"$PATH"\n' "${venv}/bin"
printf 'export GH_ADDRESS_CR_STATE_DIR=%q\n' "$state"
