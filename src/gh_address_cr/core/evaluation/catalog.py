from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from gh_address_cr.core.evaluation.models import stable_fingerprint


class EvaluationCatalog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def rebuild(self, records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        unique: dict[str, dict[str, Any]] = {}
        for raw in records:
            record = dict(raw)
            for field in ("run_id", "repo", "pr_number", "runtime_version", "cohort_key", "projection_fingerprint"):
                if not record.get(field):
                    raise ValueError(f"{field} is required")
            unique[str(record["projection_fingerprint"])] = record
        ordered = sorted(unique.values(), key=lambda row: (str(row["runtime_version"]), str(row["run_id"])))
        source_fingerprint = stable_fingerprint(ordered, prefix="catalog_")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=self.path.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            connection = sqlite3.connect(temporary)
            try:
                connection.executescript(
                    """
                    CREATE TABLE catalog_meta (schema_version TEXT NOT NULL, source_fingerprint TEXT NOT NULL);
                    CREATE TABLE runs (
                        run_id TEXT PRIMARY KEY,
                        repo TEXT NOT NULL,
                        pr_number TEXT NOT NULL,
                        runtime_version TEXT NOT NULL,
                        cohort_key TEXT NOT NULL,
                        projection_fingerprint TEXT NOT NULL UNIQUE,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX runs_version_cohort_idx ON runs(runtime_version, cohort_key);
                    CREATE INDEX runs_repo_pr_idx ON runs(repo, pr_number);
                    CREATE TABLE concerns (evaluation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload_json TEXT NOT NULL);
                    CREATE TABLE coverage (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, dimension TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(owner_type, owner_id, dimension));
                    CREATE TABLE costs (owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, metric_name TEXT NOT NULL, metric_value REAL, PRIMARY KEY(owner_type, owner_id, metric_name));
                    CREATE TABLE observations (observation_id TEXT PRIMARY KEY, run_id TEXT, payload_json TEXT NOT NULL);
                    CREATE TABLE evidence_pointers (owner_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(owner_id, fingerprint));
                    """
                )
                connection.execute("INSERT INTO catalog_meta VALUES (?, ?)", ("evaluation-catalog.v1", source_fingerprint))
                connection.executemany(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(row["run_id"], row["repo"], str(row["pr_number"]), row["runtime_version"], row["cohort_key"], row["projection_fingerprint"], json.dumps(row, sort_keys=True)) for row in ordered],
                )
                for row in ordered:
                    run_id = str(row["run_id"])
                    for concern in row.get("concerns") or []:
                        evaluation_id = str(concern.get("evaluation_id") or stable_fingerprint(concern, prefix="evaluation_"))
                        connection.execute(
                            "INSERT OR IGNORE INTO concerns VALUES (?, ?, ?)",
                            (evaluation_id, run_id, json.dumps(concern, sort_keys=True)),
                        )
                        for evidence in concern.get("evidence") or []:
                            fingerprint = str(evidence.get("fingerprint") or stable_fingerprint(evidence, prefix="evidence_"))
                            connection.execute(
                                "INSERT OR IGNORE INTO evidence_pointers VALUES (?, ?, ?)",
                                (evaluation_id, fingerprint, json.dumps(evidence, sort_keys=True)),
                            )
                    for dimension, coverage in (row.get("coverage") or {}).items():
                        connection.execute(
                            "INSERT OR REPLACE INTO coverage VALUES ('run', ?, ?, ?)",
                            (run_id, str(dimension), json.dumps(coverage, sort_keys=True)),
                        )
                    for metric, value in (row.get("cost") or {}).items():
                        connection.execute(
                            "INSERT OR REPLACE INTO costs VALUES ('run', ?, ?, ?)",
                            (run_id, str(metric), value if isinstance(value, (int, float)) else None),
                        )
                    for observation in row.get("observations") or []:
                        observation_id = str(observation.get("observation_id") or stable_fingerprint(observation, prefix="observation_"))
                        connection.execute(
                            "INSERT OR IGNORE INTO observations VALUES (?, ?, ?)",
                            (observation_id, run_id, json.dumps(observation, sort_keys=True)),
                        )
                connection.commit()
            finally:
                connection.close()
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"status": "SUCCESS", "run_count": len(ordered), "source_fingerprint": source_fingerprint, "catalog_artifact": str(self.path)}

    def query_runs(self, runtime_version: str, *, cohort_key: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(self.path)
        try:
            if cohort_key is None:
                rows = connection.execute("SELECT payload_json FROM runs WHERE runtime_version = ? ORDER BY run_id", (runtime_version,)).fetchall()
            else:
                rows = connection.execute("SELECT payload_json FROM runs WHERE runtime_version = ? AND cohort_key = ? ORDER BY run_id", (runtime_version, cohort_key)).fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            connection.close()

    def find_run(self, repo: str, pr_number: str, run_id: str | None = None) -> dict[str, Any] | None:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(self.path)
        try:
            if run_id is None:
                rows = connection.execute(
                    "SELECT payload_json FROM runs WHERE repo = ? AND pr_number = ? ORDER BY run_id",
                    (repo, str(pr_number))
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload_json FROM runs WHERE repo = ? AND pr_number = ? AND run_id = ? ORDER BY run_id",
                    (repo, str(pr_number), run_id)
                ).fetchall()
        finally:
            connection.close()
        return json.loads(rows[-1][0]) if rows else None

    def summarize_pr(self, repo: str, pr_number: str) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(self.path)
        try:
            rows = connection.execute(
                "SELECT run_id, runtime_version FROM runs WHERE repo = ? AND pr_number = ? ORDER BY run_id",
                (repo, str(pr_number))
            ).fetchall()
        finally:
            connection.close()
        return {
            "schema_version": "evaluation-pr.v1",
            "repo": repo,
            "pr_number": str(pr_number),
            "run_count": len(rows),
            "run_ids": [row[0] for row in rows],
            "runtime_versions": sorted({str(row[1]) for row in rows}),
        }

    def summarize_runtime_version(self, runtime_version: str) -> dict[str, Any]:
        rows = self.query_runs(runtime_version)
        return {
            "schema_version": "evaluation-runtime.v1",
            "runtime_version": runtime_version,
            "run_count": len(rows),
            "run_ids": [row["run_id"] for row in rows],
            "repos": sorted({str(row["repo"]) for row in rows}),
            "cohort_keys": sorted({str(row["cohort_key"]) for row in rows}),
        }
