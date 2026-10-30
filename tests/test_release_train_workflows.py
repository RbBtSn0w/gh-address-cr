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
    def execute(self, workflow, step, *, ahead="2", commits="fix: repair", existing="", refs="present", fail_api=False, equal_tree=False, diff_error=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake"
            fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as out:
    out.write(json.dumps([name, *args]) + "\\n")
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
    elif args[0] == "rev-parse": print("abc")
else:
    if args[:2] == ["pr", "list"]: print(os.environ["EXISTING"])
    elif args[0] == "api":
        if os.environ["FAIL_API"] == "1": sys.exit(1)
        print('[[{"body":"Fixes #12", "number":7, "merged_at":"2026-10-30"}]]')
    elif args[:2] == ["pr", "create"]:
        print(Path(args[args.index("--body-file") + 1]).read_text())
    elif args[:2] == ["pr", "view"]: print('{"body":"Maintainer notes"}')
    elif args[:2] == ["pr", "edit"]:
        print(Path(args[args.index("--body-file") + 1]).read_text())
    else: sys.exit(81)
""")
            fake.chmod(0o755)
            for name in ("git", "gh"):
                (root / name).symlink_to(fake)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       CALLS=str(root / "calls"), AHEAD=ahead, COMMITS=commits, EXISTING=existing,
                       REFS=refs, DIFF_ERROR="1" if diff_error else "0", EQUAL_TREE="1" if equal_tree else "0", FAIL_API="1" if fail_api else "0", HAS_CUSTOM_TOKEN="true",
                       RUNNER_TEMP=directory, GITHUB_REPOSITORY="owner/repo")
            result = subprocess.run(["bash", "-c", script(workflow, step)], cwd=root,
                                    env=env, text=True, capture_output=True, timeout=10)
            calls = [json.loads(row) for row in (root / "calls").read_text().splitlines()]
            return result, calls

    def promotion(self, **kwargs):
        return self.execute("scheduled-release-pr.yml", "Create or Update Promotion PR", **kwargs)

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
                result, calls = self.execute("sync-main-to-develop.yml", "Propose reviewed sync", refs=refs)
                self.assertEqual(result.returncode == 0, refs == "present", result.stderr)
                self.assertFalse(any(row[:2] in (["git", "push"], ["git", "merge"]) for row in calls))
                if refs != "present":
                    self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_sync_no_op_and_existing_proposal_do_not_duplicate(self):
        for args in ({"ahead": "0"}, {"existing": "42"}):
            with self.subTest(args=args):
                result, calls = self.execute("sync-main-to-develop.yml", "Propose reviewed sync", **args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(row[:3] == ["gh", "pr", "create"] for row in calls))

    def test_other_breaking_change_commits_remain_releasable(self):
        result, calls = self.promotion(commits="build!: update contract")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(row[:3] == ["gh", "pr", "create"] for row in calls))
