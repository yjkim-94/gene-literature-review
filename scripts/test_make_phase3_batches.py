"""Offline self-check for Phase 3 batch/prompt generation.

Run: python scripts/test_make_phase3_batches.py
"""
import csv
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_phase3_batches import split_even, write_batches


def _write_genes(path, n):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["symbol"])
        for i in range(1, n + 1):
            writer.writerow([f"GENE{i}"])


def test_split_31_evenly():
    batches = split_even([f"G{i}" for i in range(31)], 30)
    assert [len(batch) for batch in batches] == [16, 15]


def test_write_batch_symbols_and_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "output" / "demo"
        run_dir.mkdir(parents=True)
        genes = run_dir / "genes.tsv"
        _write_genes(genes, 31)

        batches, out_dir = write_batches(genes, summary_label="핵심 문헌 요지")

        assert [len(batch) for batch in batches] == [16, 15]
        assert (out_dir / "batch01.symbols.txt").read_text(encoding="utf-8").splitlines()[0] == "GENE1"
        prompt = (out_dir / "batch02.prompt.txt").read_text(encoding="utf-8")
        assert "GENE17.json" in prompt
        assert "GENE31.json" in prompt
        assert "핵심 문헌 요지" in prompt
        assert "| PMID | 연도 | 접근수준 | 한 줄 요지 |" in prompt
        assert "Do not fetch anything" in prompt
        assert ('keep the `### <SYMBOL> - <full gene name>` header line, '
                'write "관련 문헌 없음" under it') in prompt


def test_default_label_and_skill_save_contract():
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "output" / "demo"
        run_dir.mkdir(parents=True)
        genes = run_dir / "genes.tsv"
        _write_genes(genes, 1)
        _, out_dir = write_batches(genes)
        assert "키워드와의 연관성" in (out_dir / "batch01.prompt.txt").read_text(encoding="utf-8")

    skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    phase3 = skill[skill.index("## Phase 3"):skill.index("## Phase 4")]
    assert "sequential processing saves all blocks to `output/<slug>/summaries/batch01.md`" in phase3
    assert "parallel processing has the main agent save each returned batch as `output/<slug>/summaries/batchNN.md`" in phase3
    assert "Before Phase 4, verify" in phase3


if __name__ == "__main__":
    test_split_31_evenly()
    test_write_batch_symbols_and_prompt()
    test_default_label_and_skill_save_contract()
    print("ok: Phase 3 batches split evenly and write symbols/prompts")
