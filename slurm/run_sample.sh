#!/bin/bash
# ------------------------------------------------------------------
# run_sample.sh
#
# Runs the FASTQ -> BAM -> VCF pipeline for a single sample.
# Called by submit_variant_calling.sbatch, but works standalone too:
#
#   ./run_sample.sh --sample-id S001 \
#       --r1 data/S001_R1.fastq.gz \
#       --r2 data/S001_R2.fastq.gz \
#       --output-dir results/S001 \
#       --threads 4
#
# Designed to fail loudly and specifically rather than silently
# producing a partial/corrupt output — every stage checks its inputs
# and outputs before moving on, so a bad FASTQ or a killed job leaves
# a clear error in the log rather than a truncated BAM.
# ------------------------------------------------------------------

set -euo pipefail

REFERENCE="${REFERENCE_GENOME:-/data/reference/GRCh38.fa}"
THREADS=4

usage() {
    echo "Usage: $0 --sample-id ID --r1 FASTQ_R1 --r2 FASTQ_R2 --output-dir DIR [--threads N]"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sample-id) SAMPLE_ID="$2"; shift 2 ;;
        --r1) FASTQ_R1="$2"; shift 2 ;;
        --r2) FASTQ_R2="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --threads) THREADS="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; usage ;;
    esac
done

: "${SAMPLE_ID:?}" "${FASTQ_R1:?}" "${FASTQ_R2:?}" "${OUTPUT_DIR:?}"

log() { echo "[$(date -Iseconds)] [${SAMPLE_ID}] $*"; }
fail() { log "ERROR: $*"; exit 1; }

# --- Pre-flight checks -------------------------------------------------
[[ -f "$FASTQ_R1" ]] || fail "R1 not found: $FASTQ_R1"
[[ -f "$FASTQ_R2" ]] || fail "R2 not found: $FASTQ_R2"
[[ -s "$FASTQ_R1" ]] || fail "R1 is empty: $FASTQ_R1"
[[ -s "$FASTQ_R2" ]] || fail "R2 is empty: $FASTQ_R2"
[[ -f "$REFERENCE" ]] || fail "Reference genome not found: $REFERENCE (set REFERENCE_GENOME env var)"

mkdir -p "$OUTPUT_DIR"
BAM="${OUTPUT_DIR}/${SAMPLE_ID}.sorted.bam"
VCF="${OUTPUT_DIR}/${SAMPLE_ID}.vcf.gz"

# --- Alignment: BWA-MEM -> sorted BAM -----------------------------------
log "Aligning with BWA-MEM (${THREADS} threads)"
bwa mem -t "$THREADS" -R "@RG\tID:${SAMPLE_ID}\tSM:${SAMPLE_ID}\tPL:ILLUMINA" \
    "$REFERENCE" "$FASTQ_R1" "$FASTQ_R2" \
    | samtools sort -@ "$THREADS" -o "$BAM" - \
    || fail "BWA/sort pipeline failed"

[[ -s "$BAM" ]] || fail "BAM output missing or empty after alignment: $BAM"
samtools quickcheck "$BAM" || fail "BAM failed integrity check: $BAM"

samtools index "$BAM" || fail "BAM indexing failed"

# --- Variant calling: GATK HaplotypeCaller -----------------------------
log "Calling variants with GATK HaplotypeCaller"
gatk HaplotypeCaller \
    -R "$REFERENCE" \
    -I "$BAM" \
    -O "$VCF" \
    || fail "GATK HaplotypeCaller failed"

[[ -s "$VCF" ]] || fail "VCF output missing or empty: $VCF"
bcftools index -t "$VCF" || fail "VCF indexing failed"

# --- Checksum for downstream transfer verification ----------------------
sha256sum "$BAM" "$VCF" > "${OUTPUT_DIR}/${SAMPLE_ID}.checksums.sha256"

log "Done. BAM: $BAM  VCF: $VCF"
