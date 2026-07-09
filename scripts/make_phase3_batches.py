#!/usr/bin/env python3
"""Build Phase 3 subagent batch files from genes.tsv."""
import argparse
import csv
import math
from pathlib import Path


PROMPT_TEMPLATE = """Read only the gene files listed below. Do not fetch anything.

Run directory: {run_dir}
Gene files:
{gene_files}

For each gene, read its JSON file one by one and summarize using ONLY the abstracts in that file.
Return the filled template blocks concatenated in the same order as this batch.

### <SYMBOL> - <full gene name>
- **{summary_label}**: 2-3 sentences. End each claim with its evidence PMID in [PMID:xxxxxxxx] format.
- **주요 발견**: 2-4 bullets. Every bullet must cite a PMID.
- **근거 논문**: table | PMID | 연도 | 접근성 | 한 줄 요약 |. For the PMID cell, use the file's "url" to build a clickable link [xxxxxxxx](https://pubmed.ncbi.nlm.nih.gov/xxxxxxxx/).
- **근거 논문 전체 보기**: @@PMIDLINK@@

Rules:
- Cite ONLY PMIDs that exist in the file. Never invent a PMID or a finding.
- If a paper's "retracted" is true, mark 철회 in its 접근성 cell and do NOT use it in {summary_label} or 주요 발견.
- If a claim is from an abstract-only paper, that is fine; the access column records it.
- If the file has no papers, write "관련 문헌 없음" and stop.
- Return only the filled templates, nothing else.
"""


def read_symbols(genes_tsv):
    with genes_tsv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if "symbol" not in (reader.fieldnames or []):
            raise SystemExit(f"missing symbol column: {genes_tsv}")
        return [row["symbol"].strip() for row in reader if row.get("symbol", "").strip()]


def split_even(symbols, batch_size):
    if not symbols:
        return []
    batch_count = math.ceil(len(symbols) / batch_size)
    base = len(symbols) // batch_count
    extra = len(symbols) % batch_count
    batches = []
    start = 0
    for i in range(batch_count):
        size = base + (1 if i < extra else 0)
        batches.append(symbols[start:start + size])
        start += size
    return batches


def clean_old_batches(out_dir):
    for pattern in ("batch*.symbols.txt", "batch*.prompt.txt"):
        for path in out_dir.glob(pattern):
            path.unlink()


def write_batches(genes_tsv, out_dir=None, batch_size=30, summary_label="키워드와의 연결성"):
    genes_tsv = Path(genes_tsv)
    out_dir = Path(out_dir) if out_dir else genes_tsv.parent / "phase3_batches"
    lit_dir = genes_tsv.parent / "lit"
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_old_batches(out_dir)

    symbols = read_symbols(genes_tsv)
    batches = split_even(symbols, batch_size)
    for i, batch in enumerate(batches, 1):
        prefix = out_dir / f"batch{i:02d}"
        (prefix.with_suffix(".symbols.txt")
            .write_text("\n".join(batch) + "\n", encoding="utf-8", newline="\n"))
        gene_files = "\n".join(f"- {(lit_dir / (symbol + '.json')).as_posix()}" for symbol in batch)
        prompt = PROMPT_TEMPLATE.format(
            run_dir=genes_tsv.parent.as_posix(),
            gene_files=gene_files,
            summary_label=summary_label,
        )
        (prefix.with_suffix(".prompt.txt")
            .write_text(prompt, encoding="utf-8", newline="\n"))
    return batches, out_dir


def main():
    parser = argparse.ArgumentParser(description="Build Phase 3 subagent batch prompts.")
    parser.add_argument("--genes", required=True, help="Path to output/<slug>/genes.tsv")
    parser.add_argument("--out-dir", help="Default: output/<slug>/phase3_batches")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--general-literature", action="store_true",
                        help="Use the Mode-B label for gene-list-only reviews.")
    args = parser.parse_args()

    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    label = "통합 문헌 요약" if args.general_literature else "키워드와의 연결성"
    batches, out_dir = write_batches(args.genes, args.out_dir, args.batch_size, label)
    sizes = "/".join(str(len(batch)) for batch in batches)
    print(f"wrote {len(batches)} batch(es) [{sizes}] to {out_dir}")


if __name__ == "__main__":
    main()
