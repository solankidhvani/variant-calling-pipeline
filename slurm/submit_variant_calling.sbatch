#!/bin/bash
#SBATCH --job-name=variant_calling
#SBATCH --array=1-%NUM_SAMPLES%
#SBATCH --output=logs/%x_%A_%a.out
#SBATCH --error=logs/%x_%A_%a.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --partition=general

# ------------------------------------------------------------------
# submit_variant_calling.sbatch
#
# Slurm array job that runs the BWA -> GATK variant calling pipeline
# once per sample. Each array task picks its sample off a manifest
# file by line number, so scaling from 1 sample to 500 is just a
# matter of changing --array and the manifest.
#
# Usage:
#   NUM_SAMPLES=$(wc -l < sample_manifest.tsv)
#   sbatch --array=1-${NUM_SAMPLES} submit_variant_calling.sbatch sample_manifest.tsv
#
# sample_manifest.tsv format (tab-separated, no header):
#   sample_id    fastq_r1_path    fastq_r2_path    output_dir
# ------------------------------------------------------------------

set -euo pipefail

MANIFEST="${1:?Usage: sbatch submit_variant_calling.sbatch <sample_manifest.tsv>}"
mkdir -p logs

# SLURM_ARRAY_TASK_ID is 1-indexed; sed picks the matching line.
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$MANIFEST")

if [[ -z "$LINE" ]]; then
    echo "ERROR: no manifest entry for array task ${SLURM_ARRAY_TASK_ID}" >&2
    exit 1
fi

SAMPLE_ID=$(echo "$LINE" | cut -f1)
FASTQ_R1=$(echo "$LINE" | cut -f2)
FASTQ_R2=$(echo "$LINE" | cut -f3)
OUTPUT_DIR=$(echo "$LINE" | cut -f4)

echo "[$(date -Iseconds)] Task ${SLURM_ARRAY_TASK_ID}: starting sample ${SAMPLE_ID}"

./run_sample.sh \
    --sample-id "$SAMPLE_ID" \
    --r1 "$FASTQ_R1" \
    --r2 "$FASTQ_R2" \
    --output-dir "$OUTPUT_DIR" \
    --threads "${SLURM_CPUS_PER_TASK}"

STATUS=$?

if [[ $STATUS -eq 0 ]]; then
    echo "[$(date -Iseconds)] Task ${SLURM_ARRAY_TASK_ID}: sample ${SAMPLE_ID} completed"
else
    echo "[$(date -Iseconds)] Task ${SLURM_ARRAY_TASK_ID}: sample ${SAMPLE_ID} FAILED (exit ${STATUS})" >&2
fi

exit $STATUS
