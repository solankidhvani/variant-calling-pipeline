#!/usr/bin/env python3
"""
job_monitor.py

Polls Slurm for the status of an array job's tasks, logs state
transitions to a CSV audit trail, and resubmits tasks that fail
(up to a configurable retry limit) before flagging them for human
follow-up.

This is the piece that turns "submit 200 jobs and hope" into
something you can actually track turnaround-time and failure rate
against — each row in the CSV is one (job, attempt) with timestamps,
so it doubles as the audit log for KPI reporting.

Usage:
    python job_monitor.py --job-id 123456 --manifest sample_manifest.tsv \
        --sbatch-script submit_variant_calling.sbatch --max-retries 2

    # Dry run against a mock Slurm backend, for testing without a cluster:
    python job_monitor.py --job-id 123456 --manifest sample_manifest.tsv \
        --sbatch-script submit_variant_calling.sbatch --mock

Requires: Python 3.8+, standard library only.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


TERMINAL_FAIL_STATES = {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "CANCELLED"}
TERMINAL_OK_STATES = {"COMPLETED"}
RUNNING_STATES = {"PENDING", "RUNNING", "REQUEUED", "RESIZING", "SUSPENDED"}


@dataclass
class TaskRecord:
    array_task_id: str
    sample_id: str
    job_id: str
    attempt: int = 1
    state: str = "PENDING"
    last_checked: str = ""
    retries_used: int = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_manifest(manifest_path: Path) -> dict[str, str]:
    """Map array task index (1-indexed line number) -> sample_id."""
    tasks = {}
    with manifest_path.open() as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            sample_id = line.split("\t")[0]
            tasks[str(i)] = sample_id
    return tasks


class SlurmBackend:
    """Thin wrapper around squeue/sacct/sbatch so the polling logic
    doesn't care whether it's talking to a real cluster or a mock."""

    def query_states(self, job_id: str) -> dict[str, str]:
        """Return {array_task_id: state} for all tasks of an array job."""
        # sacct gives terminal states after tasks finish; squeue covers
        # tasks still queued/running. Query both and let sacct win, since
        # it reflects the final state once a task leaves the queue.
        states: dict[str, str] = {}

        squeue = subprocess.run(
            ["squeue", "-j", job_id, "-h", "-o", "%K|%T"],
            capture_output=True, text=True,
        )
        for line in squeue.stdout.strip().splitlines():
            if "|" not in line:
                continue
            task_id, state = line.split("|", 1)
            states[task_id.strip()] = state.strip()

        sacct = subprocess.run(
            ["sacct", "-j", job_id, "-n", "-P", "-o", "JobID,State"],
            capture_output=True, text=True,
        )
        for line in sacct.stdout.strip().splitlines():
            if "|" not in line:
                continue
            jobid_field, state = line.split("|", 1)
            if "_" in jobid_field:
                task_id = jobid_field.split("_", 1)[1]
                states[task_id] = state.strip().split()[0]  # drop "CANCELLED by ..."

        return states

    def resubmit(self, sbatch_script: str, manifest: str, array_task_id: str) -> str:
        """Resubmit a single array task; returns new job id."""
        result = subprocess.run(
            ["sbatch", "--parsable", f"--array={array_task_id}", sbatch_script, manifest],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()


class MockSlurmBackend(SlurmBackend):
    """Simulates a cluster locally so the retry logic can be tested
    without access to a real Slurm scheduler. Deterministic: every
    task with an even array id 'fails' once, then succeeds on retry."""

    def __init__(self):
        self._seen: dict[str, int] = {}

    def query_states(self, job_id: str) -> dict[str, str]:
        states = {}
        for task_id, seen_count in self._seen.items():
            task_num = int(task_id)
            if task_num % 5 == 0 and seen_count < 2:
                states[task_id] = "FAILED"
            else:
                states[task_id] = "COMPLETED"
        return states

    def resubmit(self, sbatch_script, manifest, array_task_id):
        self._seen[array_task_id] = self._seen.get(array_task_id, 0) + 1
        return f"mock-{array_task_id}-attempt{self._seen[array_task_id]}"

    def register(self, task_ids):
        for t in task_ids:
            self._seen.setdefault(t, 0)


def write_audit_row(csv_path: Path, record: TaskRecord, event: str):
    file_exists = csv_path.exists()
    with csv_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "event", "sample_id", "array_task_id",
                "job_id", "attempt", "state", "retries_used",
            ])
        writer.writerow([
            now_iso(), event, record.sample_id, record.array_task_id,
            record.job_id, record.attempt, record.state, record.retries_used,
        ])


def monitor(
    job_id: str,
    manifest_path: Path,
    sbatch_script: str,
    max_retries: int,
    poll_interval: int,
    audit_csv: Path,
    backend: SlurmBackend,
) -> int:
    task_samples = load_manifest(manifest_path)
    records: dict[str, TaskRecord] = {
        task_id: TaskRecord(array_task_id=task_id, sample_id=sample_id, job_id=job_id)
        for task_id, sample_id in task_samples.items()
    }

    if isinstance(backend, MockSlurmBackend):
        backend.register(records.keys())

    pending = set(records.keys())
    permanently_failed = []

    print(f"Monitoring {len(pending)} tasks for job {job_id} "
          f"(max_retries={max_retries}, poll_interval={poll_interval}s)")

    while pending:
        states = backend.query_states(job_id)
        newly_resolved = []

        for task_id in list(pending):
            state = states.get(task_id, "PENDING")
            record = records[task_id]
            record.state = state
            record.last_checked = now_iso()

            if state in TERMINAL_OK_STATES:
                write_audit_row(audit_csv, record, "completed")
                newly_resolved.append(task_id)

            elif state in TERMINAL_FAIL_STATES:
                if record.retries_used < max_retries:
                    record.retries_used += 1
                    record.attempt += 1
                    write_audit_row(audit_csv, record, "retrying")
                    print(f"  [{record.sample_id}] task {task_id} failed "
                          f"({state}) -> retry {record.retries_used}/{max_retries}")
                    new_job_id = backend.resubmit(sbatch_script, str(manifest_path), task_id)
                    record.job_id = new_job_id
                else:
                    write_audit_row(audit_csv, record, "failed_permanently")
                    print(f"  [{record.sample_id}] task {task_id} exhausted "
                          f"retries ({max_retries}) -> FLAGGED FOR REVIEW")
                    permanently_failed.append(task_id)
                    newly_resolved.append(task_id)

        pending -= set(newly_resolved)

        if pending:
            time.sleep(poll_interval)

    print(f"\nDone. Completed: {len(records) - len(permanently_failed)}/{len(records)}  "
          f"Permanently failed: {len(permanently_failed)}")
    if permanently_failed:
        print("Samples needing manual follow-up:")
        for task_id in permanently_failed:
            print(f"  - {records[task_id].sample_id} (task {task_id})")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job-id", required=True, help="Slurm array job ID to monitor")
    parser.add_argument("--manifest", required=True, type=Path, help="Sample manifest TSV")
    parser.add_argument("--sbatch-script", required=True, help="Script used for resubmission on failure")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--poll-interval", type=int, default=60, help="Seconds between polls")
    parser.add_argument("--audit-csv", type=Path, default=Path("logs/job_audit.csv"))
    parser.add_argument("--mock", action="store_true", help="Use a simulated backend (no real cluster needed)")
    args = parser.parse_args()

    args.audit_csv.parent.mkdir(parents=True, exist_ok=True)
    backend = MockSlurmBackend() if args.mock else SlurmBackend()

    if args.mock:
        # Speed the demo up so it's runnable interactively.
        args.poll_interval = min(args.poll_interval, 1)

    sys.exit(monitor(
        job_id=args.job_id,
        manifest_path=args.manifest,
        sbatch_script=args.sbatch_script,
        max_retries=args.max_retries,
        poll_interval=args.poll_interval,
        audit_csv=args.audit_csv,
        backend=backend,
    ))


if __name__ == "__main__":
    main()
