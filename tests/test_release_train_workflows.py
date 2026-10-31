"""Execute release workflow shell guards against isolated command fixtures."""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def script(workflow, step):
    content = (ROOT / ".github/workflows" / workflow).read_text()
    block = content.split("- name: " + step, 1)[1].split("run: |", 1)[1]
    lines = []
    for line in block.splitlines()[1:]:
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


class ReleaseTrainWorkflowTests(unittest.TestCase):
    def execute(self, workflow, step, *, ahead="2", commits="fix: repair", existing="", refs="present", fail_api=False, equal_tree=False, diff_error=False, pr_body="Fixes #12", existing_body="Maintainer notes", custom_token=True, snapshot_kind="none", source_advances=False, repeat=1, fail_ref_create=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake"
            fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["STATE"])
state = json.loads(state_path.read_text())
row = [name, *args]
if "--input" in args:
    row.append({"input": json.loads(Path(args[args.index("--input") + 1]).read_text())})
with open(os.environ["CALLS"], "a") as out:
    out.write(json.dumps(row) + "\\n")
source, tree, candidate = "a" * 40, "b" * 40, "c" * 40

def emit(data):
    if "--jq" in args:
        expression = args[args.index("--jq") + 1]
        if expression == ".sha": data = data["sha"]
        elif expression == ".object.sha": data = data["object"]["sha"]
        else: raise ValueError(expression)
        print(data)
    else:
        print(json.dumps(data))

def save():
    state_path.write_text(json.dumps(state))
if name == "git":
    if args[0] == "ls-remote":
        if os.environ["REFS"] == "error": sys.exit(1)
        if os.environ["REFS"] == "present":
            print("abc refs/heads/develop")
            if "refs/heads/main" in args: print("def refs/heads/main")
    elif args[0] == "rev-list":
        print(os.environ["AHEAD"] if "--count" in args else "abc")
    elif args[0] == "log": print(os.environ["COMMITS"])
    elif args[0] == "diff": sys.exit(2 if os.environ["DIFF_ERROR"] == "1" else (0 if os.environ["EQUAL_TREE"] == "1" else 1))
    elif args[0] not in ("fetch", "rev-parse"): sys.exit(80)
    elif args[0] == "rev-parse": print(tree if args[1].endswith("^{tree}") else source)
else:
    if args[:2] == ["pr", "list"]: print(state["pr"])
    elif args[0] == "api":
        if os.environ["FAIL_API"] == "1": sys.exit(1)
        endpoint = next(value for value in args if value.startswith("repos/"))
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        if "/git/matching-refs/" in endpoint:
            branch = "sync/main-to-develop/" + source
            emit([{"ref":"refs/heads/" + branch,"object":{"sha":state["ref"]}}] if state["ref"] else [])
        elif endpoint.endswith("/git/ref/heads/main"):
            emit({"object":{"sha":"d" * 40 if os.environ["SOURCE_ADVANCES"] == "1" else source}})
        elif endpoint.endswith("/git/commits") and method == "POST":
            payload = row[-1]["input"]
            state["commit"] = {"sha":candidate,"tree":{"sha":payload["tree"]},"parents":[{"sha":value} for value in payload["parents"]],"message":payload["message"]}
            save(); emit(state["commit"])
        elif "/git/commits/" in endpoint:
            commit = state["commit"].copy()
            kind = os.environ["SNAPSHOT_KIND"]
            if kind == "invalid_tree": commit["tree"] = {"sha":"d" * 40}
            elif kind == "invalid_parent": commit["parents"] = [{"sha":"d" * 40}]
            emit(commit)
        elif endpoint.endswith("/git/refs") and method == "POST":
            if state["ref"] or os.environ["FAIL_REF_CREATE"] == "1": sys.exit(1)
            payload = row[-1]["input"]
            state["ref"] = payload["sha"]; save()
            emit({"ref":payload["ref"],"object":{"sha":state["ref"]}})
        else:
            print(json.dumps([[{"body":os.environ["PR_BODY"], "number":7, "merged_at":"2026-10-30"}]]))
    elif args[:2] == ["pr", "create"]:
        state["pr"] = "42"; save()
        print(Path(args[args.index("--body-file") + 1]).read_text())
    elif args[:2] == ["pr", "view"]: print(json.dumps({"body":os.environ["EXISTING_BODY"]}))
    elif args[:2] == ["pr", "edit"]:
        print(Path(args[args.index("--body-file") + 1]).read_text())
    else: sys.exit(81)
""")
            fake.chmod(0o755)
            for name in ("git", "gh"):
                (root / name).symlink_to(fake)
            state = {"ref":None,"commit":None,"pr":existing}
            if snapshot_kind != "none" or existing:
                state.update(ref="c" * 40, commit={"sha":"c" * 40,"tree":{"sha":"b" * 40},"parents":[{"sha":"a" * 40}],"message":"chore(repo): validate main " + "a" * 40 + " sync"})
            (root / "state.json").write_text(json.dumps(state))
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       CALLS=str(root / "calls"), AHEAD=ahead, COMMITS=commits, EXISTING=existing,
                       REFS=refs, DIFF_ERROR="1" if diff_error else "0", EQUAL_TREE="1" if equal_tree else "0", FAIL_API="1" if fail_api else "0", HAS_CUSTOM_TOKEN="true" if custom_token else "false", STATE=str(root / "state.json"),
                       SNAPSHOT_KIND=snapshot_kind, SOURCE_ADVANCES="1" if source_advances else "0", FAIL_REF_CREATE="1" if fail_ref_create else "0",
                       RUNNER_TEMP=directory, GITHUB_REPOSITORY="owner/repo", PR_BODY=pr_body, EXISTING_BODY=existing_body)
            for _ in range(repeat):
                result = subprocess.run(["bash", "-c", script(workflow, step)], cwd=root,
                                        env=env, text=True, capture_output=True, timeout=10)
                if result.returncode:
                    break
            calls = [json.loads(row) for row in (root / "calls").read_text().splitlines()]
            return result, calls

    def promotion(self, **kwargs):
        return self.execute("branches.yml", "Create or Update Promotion PR", **kwargs)

    def test_promotion_never_merges_and_preserves_issue_references(self):
        result, calls = self.promotion()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Closes #12", result.stdout)
        self.assertIn("human", result.stdout.lower())
        self.assertFalse(any(row[:3] == ["gh", "pr", "merge"] for row in calls))

    def test_empty_and_non_release_ranges_do_not_create_prs(self):
        for args in ({"ahead": "0"}, {"commits": "docs: improve guide"}, {"equal_tree": True}):
            with self.subTest(args=args):
                result, calls = self.promotion(**args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_custom_refactor_release_rule_is_preserved(self):
        result, calls = self.promotion(commits="refactor(eval): neutral runner")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_existing_proposal_is_not_duplicated(self):
        result, calls = self.promotion(existing="42")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Maintainer notes", result.stdout)
        self.assertIn("Closes #12", result.stdout)
        self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_missing_ref_transport_and_issue_api_errors_fail_closed(self):
        for args in ({"refs": "missing"}, {"refs": "error"}, {"fail_api": True}, {"diff_error": True}):
            with self.subTest(args=args):
                result, calls = self.promotion(**args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_sync_only_proposes_and_missing_ref_is_not_recreated(self):
        for refs in ("present", "missing", "error"):
            with self.subTest(refs=refs):
                result, calls = self.execute("branches.yml", "Propose reviewed sync", refs=refs)
                self.assertEqual(result.returncode == 0, refs == "present", result.stderr)
                self.assertFalse(any(row[:2] in (["git", "push"], ["git", "merge"]) for row in calls))
                if refs != "present":
                    self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_sync_no_op_and_existing_proposal_do_not_duplicate(self):
        for args in ({"ahead": "0"}, {"existing": "42"}):
            with self.subTest(args=args):
                result, calls = self.execute("branches.yml", "Propose reviewed sync", **args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_other_breaking_change_commits_remain_releasable(self):
        result, calls = self.promotion(commits="build!: update contract")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_breaking_note_formats_match_release_analyzer(self):
        for note in ("  BREAKING CHANGE: incompatible", "* breaking-change: incompatible", " |*BREAKING CHANGE incompatible"):
            with self.subTest(note=note):
                result, calls = self.promotion(commits="build: adjust\n\n" + note)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(any(row[:3] == ["gh", "pr", "create"] for row in calls))
        result, calls = self.promotion(commits="build: adjust\n\n  BREAKING CHANGE:   ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_closing_keyword_colons_are_carried_forward(self):
        result, _ = self.promotion(pr_body="Closes: #12; FIXES : #13; resolves #14")
        self.assertEqual(result.returncode, 0, result.stderr)
        for number in (12, 13, 14):
            self.assertIn(f"Closes #{number}", result.stdout)

    def test_notes_outside_generated_block_survive_repeated_updates(self):
        start, end = "<!-- release-train-proposal -->", "<!-- /release-train-proposal -->"
        body = f"Before notes\n{start}\nOld generated content\n{end}\nAfter notes"
        for _ in range(2):
            result, _ = self.promotion(existing="42", existing_body=body)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Before notes", result.stdout)
            self.assertIn("After notes", result.stdout)
            self.assertNotIn("Old generated content", result.stdout)
            self.assertEqual(result.stdout.count(start), 1)
            self.assertEqual(result.stdout.count(end), 1)
            body = result.stdout

    def test_ambiguous_generated_blocks_are_not_overwritten(self):
        for body in ("<!-- release-train-proposal -->\nHuman notes", "<!-- /release-train-proposal -->"):
            with self.subTest(body=body):
                result, calls = self.promotion(existing="42", existing_body=body)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(row[:3] == ["gh", "pr", "edit"] for row in calls))

    def sync(self, **kwargs):
        return self.execute("branches.yml", "Propose reviewed sync", **kwargs)

    def test_sync_skip_ci_source_gets_non_skip_same_tree_snapshot(self):
        result, calls = self.sync(commits="chore(release): 3.21.2 [skip ci]")
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [row for row in calls if row[:3] == ["gh", "pr", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0][creates[0].index("--head") + 1], "sync/main-to-develop/" + "a" * 40)
        commits = [row[-1]["input"] for row in calls if any(isinstance(value, str) and value.endswith("/git/commits") for value in row) and "POST" in row]
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["tree"], "b" * 40)
        self.assertEqual(commits[0]["parents"], ["a" * 40])
        self.assertNotIn("[skip ci]", commits[0]["message"].lower())

    def test_sync_repeated_run_reuses_snapshot_and_proposal(self):
        result, calls = self.sync(repeat=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(row[:3] == ["gh", "pr", "create"] for row in calls), 1)
        self.assertEqual(sum(any(isinstance(value, str) and value.endswith("/git/refs") for value in row) and "POST" in row for row in calls), 1)

    def test_sync_invalid_snapshots_and_moving_main_fail_closed(self):
        for args in ({"snapshot_kind":"invalid_tree"}, {"snapshot_kind":"invalid_parent"}, {"source_advances":True}, {"fail_ref_create":True}):
            with self.subTest(args=args):
                result, calls = self.sync(**args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))
                self.assertFalse(any("PATCH" in row for row in calls))

    def test_sync_default_token_cannot_create_ci_suppressed_proposal(self):
        result, calls = self.sync(custom_token=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))
        result, calls = self.sync(custom_token=False, ahead="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))
