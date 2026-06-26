# Germline Variant Calling Pipeline

**End-to-end germline variant calling pipeline using BWA, GATK HaplotypeCaller, and SnpEff annotation on human reference genome (GRCh38). Designed for reproducibility and HPC deployment.**

---

## Overview

This pipeline processes raw sequencing reads through alignment, variant calling, filtering, and functional annotation — following GATK best practices throughout. It is containerized with Docker for portability and reproducibility, and designed for execution on HPC clusters via shell-scripted job orchestration.

**Key outputs:** Annotated VCF with SNPs and indels, QC reports, alignment statistics.

---

## Pipeline Workflow

```
Raw FASTQ (paired-end)
        │
        ▼
   Quality Control
   (FastQC → MultiQC report)
        │
        ▼
   Alignment to GRCh38
   (BWA-MEM)
        │
        ▼
   SAM → BAM conversion + sorting
   (SAMtools)
        │
        ▼
   Mark Duplicates
   (GATK MarkDuplicates)
        │
        ▼
   Base Quality Score Recalibration
   (GATK BQSR)
        │
        ▼
   QC Checkpoint
   (SAMtools flagstat — alignment metrics)
        │
        ▼
   Variant Calling
   (GATK HaplotypeCaller — SNPs + Indels)
        │
        ▼
   Variant Filtering
   (GATK VQSR / hard filters — GATK best practices)
        │
        ▼
   Functional Annotation
   (SnpEff — GRCh38.99)
        │
        ▼
   Annotated VCF + Summary Report
```

---

## Tools & Versions

| Tool | Version | Purpose |
|------|---------|---------|
| BWA-MEM | 0.7.17 | Read alignment to GRCh38 |
| SAMtools | 1.17 | BAM conversion, sorting, flagstat QC |
| FastQC | 0.12.1 | Raw read quality assessment |
| MultiQC | 1.14 | Aggregate QC report |
| GATK | 4.4.0 | MarkDuplicates, BQSR, HaplotypeCaller, filtering |
| SnpEff | 5.1 | Functional variant annotation (GRCh38.99) |
| Docker | 24.0 | Containerized, reproducible environment |

---

## Key Stats

| Parameter | Value |
|-----------|-------|
| Reference genome | GRCh38 (hg38) |
| Variant types called | SNPs + Indels (germline) |
| Variant caller | GATK HaplotypeCaller (GVCF mode) |
| Annotation database | SnpEff GRCh38.99 |
| Filtering approach | GATK best practices (hard filters) |
| Deployment | HPC (shell-scripted job orchestration) + Docker |

---

## QC Checkpoints

**Pre-alignment:** FastQC on raw paired-end FASTQ files; MultiQC for aggregated summary.

**Post-alignment:** SAMtools flagstat — reports total reads, mapped reads, properly paired reads, and duplicate rate.

**Variant-level:** GATK variant filtration using standard quality metrics (QD, FS, MQ, MQRankSum, ReadPosRankSum) consistent with GATK best practices.

---

## Variant Filtering Criteria

**SNPs:**
- QD < 2.0
- FS > 60.0
- MQ < 40.0
- MQRankSum < -12.5
- ReadPosRankSum < -8.0

**Indels:**
- QD < 2.0
- FS > 200.0
- ReadPosRankSum < -20.0

---

## Annotation

Functional annotation performed with **SnpEff (GRCh38.99)**, adding:
- Gene name and transcript ID
- Variant effect (missense, synonymous, frameshift, splice site, etc.)
- Impact prediction (HIGH / MODERATE / LOW / MODIFIER)
- HGVS notation (protein and coding level)

---

## How to Run

### 1. Clone the repository

```bash
git clone https://github.com/solankidhvani/variant-calling-pipeline.git
cd variant-calling-pipeline
```

### 2. Pull the Docker container

```bash
docker pull solankidhvani/variant-calling-pipeline:latest
```

### 3. Download reference genome (GRCh38)

```bash
# Download GRCh38 from NCBI or Ensembl
# Place in: data/reference/GRCh38.fa
# Index with BWA:
bwa index data/reference/GRCh38.fa
samtools faidx data/reference/GRCh38.fa
gatk CreateSequenceDictionary -R data/reference/GRCh38.fa
```

### 4. Add your input FASTQ files

```
data/
├── fastq/
│   ├── sample_R1.fastq.gz
│   └── sample_R2.fastq.gz
└── reference/
    └── GRCh38.fa
```

### 5. Run the pipeline

```bash
bash pipeline.sh --sample sample --threads 8
```

### 6. HPC execution (SLURM example)

```bash
sbatch submit_pipeline.sh
```

---

## Repository Structure

```
variant-calling-pipeline/
├── pipeline.sh              # Main pipeline script
├── submit_pipeline.sh       # SLURM job submission script
├── Dockerfile               # Docker container definition
├── config/
│   └── params.sh            # Configurable parameters (threads, paths, sample IDs)
├── scripts/
│   ├── 01_qc.sh             # FastQC + MultiQC
│   ├── 02_align.sh          # BWA-MEM alignment
│   ├── 03_process_bam.sh    # SAMtools sort, index, flagstat
│   ├── 04_gatk_preprocess.sh # MarkDuplicates + BQSR
│   ├── 05_variant_call.sh   # GATK HaplotypeCaller
│   ├── 06_filter.sh         # Variant filtering
│   └── 07_annotate.sh       # SnpEff annotation
├── results/                 # Output directory (gitignored)
└── README.md
```

---

## Environment

```
Docker image based on Ubuntu 22.04
Python >= 3.9
Java >= 11 (required for GATK and SnpEff)
BWA, SAMtools, FastQC, MultiQC installed via conda
GATK 4.4.0 (jar)
SnpEff 5.1 (jar)
```

---

## References

- [GATK Best Practices — Germline Short Variant Discovery](https://gatk.broadinstitute.org/hc/en-us/articles/360035535932)
- [BWA Manual](http://bio-bwa.sourceforge.net/bwa.shtml)
- [SnpEff Documentation](https://pcingola.github.io/SnpEff/)

---

## Author

**Dhvani Solanki**  
Bioinformatician | Toronto, ON  
[github.com/solankidhvani](https://github.com/solankidhvani) | [linkedin.com/in/dhvani-solanki](https://linkedin.com/in/dhvani-solanki)

*Part of an active bioinformatics portfolio. See also: [scRNA-seq PBMC Analysis](https://github.com/solankidhvani/scRNAseq-PBMC-Seurat-analysis) | [Ontario Cancer Trends](https://github.com/solankidhvani/ontario-cancer-trends)*
