# HPC Job Scheduling: Slurm Array Jobs with Monitoring & Retry

This folder adds Slurm-based orchestration to the variant calling pipeline:
instead of running each sample's FASTQ → BAM → VCF pipeline one at a time,
samples are submitted as a Slurm **array job**, and a Python monitor tracks
each task through completion, **automatically retries transient failures**,
and writes an **audit CSV** suitable for turnaround-time / KPI reporting.

## Why this exists

Running a pipeline on one sample is easy. Running it on 200 samples reliably —
where some jobs get OOM-killed, some nodes fail, and someone needs to know
*which* samples still need attention by tomorrow morning — is a different
problem. This is a minimal, readable version of that problem.

## Files

| File | Purpose |
|---|---|
| `submit_variant_calling.sbatch` | Slurm array job template. Each array task reads one line from a sample manifest and calls `run_sample.sh`. |
| `run_sample.sh` | Per-sample BWA → GATK pipeline. Validates inputs/outputs at every stage and fails loudly with a specific error rather than producing a silent partial result. Also writes a SHA-256 checksum file for the BAM/VCF outputs. |
| `job_monitor.py` | Polls `squeue`/`sacct` for task states, resubmits failed tasks up to `--max-retries`, and logs every state transition to a CSV audit trail. Includes a `--mock` mode so the retry logic can be demoed without a real cluster. |
| `sample_manifest.tsv` | Example manifest (sample_id, R1, R2, output_dir) — the input array jobs iterate over. |

## Usage (on a real cluster)

```bash
NUM_SAMPLES=$(wc -l < sample_manifest.tsv)

JOB_ID=$(sbatch --parsable --array=1-${NUM_SAMPLES} \
    submit_variant_calling.sbatch sample_manifest.tsv)

python job_monitor.py \
    --job-id "$JOB_ID" \
    --manifest sample_manifest.tsv \
    --sbatch-script submit_variant_calling.sbatch \
    --max-retries 2 \
    --poll-interval 60 \
    --audit-csv logs/job_audit.csv
```

## Try it without a cluster

`job_monitor.py` ships with a mock Slurm backend so the retry/audit logic
can be verified without LSF/Slurm access:

```bash
python job_monitor.py \
    --job-id 999999 \
    --manifest sample_manifest.tsv \
    --sbatch-script submit_variant_calling.sbatch \
    --mock --max-retries 2
```

Sample output:

```
Monitoring 10 tasks for job 999999 (max_retries=2, poll_interval=1s)
  [S005] task 5 failed (FAILED) -> retry 1/2
  [S010] task 10 failed (FAILED) -> retry 1/2
  [S005] task 5 failed (FAILED) -> retry 2/2
  [S010] task 10 failed (FAILED) -> retry 2/2

Done. Completed: 10/10  Permanently failed: 0
```

The mock backend deterministically fails every 5th task once, so you can see
both the retry path and the "exhausted retries → flagged for review" path
(raise `--max-retries` below 2 to see a permanent failure recorded).

## Audit CSV

Every state transition — submitted, retrying, completed, or permanently
failed — is appended to `logs/job_audit.csv` with a timestamp:

```
timestamp,event,sample_id,array_task_id,job_id,attempt,state,retries_used
2026-08-19T22:15:43+00:00,completed,S001,1,999999,1,COMPLETED,0
2026-08-19T22:15:43+00:00,retrying,S005,5,999999,2,FAILED,1
2026-08-19T22:15:45+00:00,completed,S005,5,mock-5-attempt2,3,COMPLETED,2
```

This is intentionally flat/tabular rather than nested JSON, so it can be
loaded straight into a `turnaround_time` report or a Postgres table with
`COPY ... FROM 'job_audit.csv' CSV HEADER`.

## Design notes

- **Array jobs over a loop of individual `sbatch` calls** — one array job
  is easier to monitor, cancel, and reason about than hundreds of
  independent job IDs, and it's the idiomatic Slurm pattern for
  "same pipeline, many samples."
- **Retry logic lives outside the scheduler**, in Python, rather than
  relying on Slurm's own requeue flags — this keeps the retry policy
  (how many attempts, what counts as a failure) explicit, testable, and
  independent of cluster configuration.
- **`run_sample.sh` fails fast and specifically** (`set -euo pipefail` +
  explicit checks after each stage) so a failure log tells you *which*
  stage broke, rather than requiring someone to diff a truncated BAM.
- Adapting this to **LSF** mainly means swapping `sbatch`/`squeue`/`sacct`
  for `bsub`/`bjobs` in `SlurmBackend` — the polling/retry/audit logic in
  `job_monitor.py` doesn't otherwise change.
