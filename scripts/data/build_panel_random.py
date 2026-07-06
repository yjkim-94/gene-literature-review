#!/usr/bin/env python3
# ============================================================================
# build_panel_random.py
# ============================================================================
# Author:      yjkim
# Purpose:     Generate the keyword-independent random disease panel (B_random).
# Description: Resolves a curated, disease-group-balanced list of 30 diseases
#              to their real PubTator @DISEASE_ entity tokens and snapshot
#              disease_total counts, then writes scripts/data/panel_random.tsv
#              (token<TAB>disease_total<TAB>category<TAB>name) for CDRS Stage 2.
#              - tokens/counts are fetched live (never fabricated) via the same
#                PubTator helpers fetch_genes.py uses, so a run is auditable; the
#                resolved MeSH name is written per row so every token is
#                eyeball-checkable without re-querying.
#              - 6 categories x 5 diseases, chosen to span the volume spectrum
#                and to stay neutral across keywords -- the panel is a random
#                background reference, not a sibling set. Diseases that are
#                method_dev eval keywords are deliberately excluded (they would
#                make the background circular with the benchmark). Any token
#                that still collides with a query's siblings is dropped at run
#                time by fetch_genes (see method_dev.md 6.2).
# Regenerate:  python scripts/data/build_panel_random.py
# ============================================================================
import collections
import os
import sys
import time

# Reuse fetch_genes' PubTator helpers (entity autocomplete + count) -- same
# code path as scoring, so tokens/counts match what CDRS will query.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_genes as fg

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_random.tsv")

# ============================================================================
# 0. 후보 질병 (category별 5개, volume 스펙트럼을 걸치도록 수기 선정)
# ============================================================================
# Balanced across 6 broad groups for keyword-neutrality; each group mixes
# high- and low-volume diseases so the resolved counts spread over the range.
# NONE of these is a method_dev eval keyword (AD/asthma/RA/psoriasis/IBD/T2D/
# Alzheimer/breast/melanoma/SLE/COPD/NAFLD) -- a random background must not
# overlap the benchmark, else B_random leaks the very diseases we score against.
PANEL = {
    "oncology":       ["colorectal cancer", "ovarian cancer", "glioblastoma",
                       "pancreatic cancer", "prostate cancer"],
    "metabolic":      ["osteoporosis", "obesity", "hypothyroidism",
                       "gout", "phenylketonuria"],
    "neuro":          ["migraine", "Parkinson disease", "multiple sclerosis",
                       "epilepsy", "amyotrophic lateral sclerosis"],
    "infectious":     ["tuberculosis", "malaria", "hepatitis C",
                       "HIV infections", "influenza"],
    "cardiovascular": ["hypertension", "myocardial infarction", "atrial fibrillation",
                       "heart failure", "abdominal aortic aneurysm"],
    "psychiatric":    ["schizophrenia", "major depressive disorder", "bipolar disorder",
                       "autistic disorder", "anorexia nervosa"],
}


def _wordset(s):
    return frozenset(w for w in "".join(
        ch if ch.isalnum() else " " for ch in s.lower()).split() if w)


def resolve_disease(keyword):
    """(token, count, name, exact) for a keyword, or None if no @DISEASE_ hit.

    The top autocomplete hit is usually right ('breast cancer' -> Breast
    Neoplasms) but sometimes off ('hepatitis C' ranks Drug-Induced Liver Injury
    first). Rule without a per-term blocklist: among candidates whose name is
    the SAME word set as the keyword (order-independent), take the highest count
    -- that picks the canonical concept over fragmented synonyms ('Depressive
    Disorder Major' 120766 over 'Major Depressive Disorder' 6806) and rejects
    off-concept top hits. If no word-set match (cancer!=neoplasms), fall back to
    the first @DISEASE_ hit; `exact=False` flags that fallback for manual review
    (the written name column lets a human confirm it).
    """
    cands = [c for c in fg.entity_candidates(keyword, top=6)
             if str(c["token"]).startswith("@DISEASE_")]
    if not cands:
        return None
    kw_set = _wordset(keyword)
    matches = [c for c in cands if _wordset(c.get("name", "")) == kw_set]
    if matches:
        # count each match once, then take the max -- fragmented synonyms lose
        # to the canonical high-count concept ('Depressive Disorder Major').
        scored = [(fg._pubtator_count('"%s"' % c["token"])[0], c) for c in matches]
        count, best = max(scored, key=lambda x: x[0])
        return str(best["token"]), count, best.get("name", ""), True
    c = cands[0]
    return str(c["token"]), fg._pubtator_count('"%s"' % c["token"])[0], c.get("name", ""), False


# ============================================================================
# 1. 토큰/카운트 조회
# ============================================================================
def main():
    rows = []  # (token, count, category, name)
    items = [(cat, kw) for cat, kws in PANEL.items() for kw in kws]
    for i, (cat, kw) in enumerate(items):
        r = resolve_disease(kw)
        if r is None:
            sys.exit(f"조회 실패 [{i+1}/{len(items)}]: '{kw}' has no @DISEASE_ token "
                     f"-- fix the curated term and re-run (no partial file written)")
        tok, count, name, exact = r
        flag = "" if exact else "  ⚠ fallback(first-hit) — name 확인 필요"
        print(f"조회 [{i+1}/{len(items)}]: {kw} -> {tok} (n={count}){flag}")
        rows.append((tok, count, cat, name))

    # 중복 토큰 제거 (서로 다른 keyword가 같은 MeSH로 수렴할 수 있음)
    seen, uniq = set(), []
    for row in rows:
        if row[0] not in seen:
            seen.add(row[0])
            uniq.append(row)

    # 무결성: spec은 30개(6 category × 5)를 요구 -- 위반이면 파일 쓰지 말고 fail.
    # (assert가 아니라 sys.exit: -O 실행에서도 살아있어야 하는 boundary check.)
    if len(uniq) != len(items):
        sys.exit(f"중복 토큰으로 {len(items)}→{len(uniq)}개 축소됨 -- 커스텀 질병 목록 "
                 f"중복 제거 후 재실행")
    per_cat = collections.Counter(cat for _, _, cat, _ in uniq)
    if any(n != 5 for n in per_cat.values()):
        sys.exit(f"category 균형 위반: {dict(per_cat)} -- 각 5개여야 함")

    uniq.sort(key=lambda r: r[1])  # ascending volume, so the spread is visible

    # ========================================================================
    # 2. 저장 (# 주석 헤더 = provenance, consumer는 # 라인 skip)
    # ========================================================================
    counts = [c for _, c, _, _ in uniq]
    # 정직한 percentile: 0,10,...,100 위치의 order statistic (interpolation 없음).
    pct = [counts[min(int(len(counts) * q / 10), len(counts) - 1)] for q in range(11)]
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("# panel_random.tsv -- keyword-independent random disease panel "
                "(B_random) for CDRS Stage 2\n")
        f.write(f"# generated by scripts/data/build_panel_random.py | PubTator "
                f"snapshot {time.strftime('%Y-%m-%d')}\n")
        f.write(f"# {len(uniq)} diseases, 6 balanced categories, volume range "
                f"{min(counts)}-{max(counts)}\n")
        f.write("# selection: canonical @DISEASE_ concept per curated term (word-set "
                "match, max count); excludes all method_dev eval keywords\n")
        f.write("# volume order-stats (0,10,..,100 pct): "
                + ", ".join(str(d) for d in pct) + "\n")
        f.write("token\tdisease_total\tcategory\tname\n")
        for tok, count, cat, name in uniq:
            f.write(f"{tok}\t{count}\t{cat}\t{name}\n")

    print(f"\n===== panel_random.tsv 생성 완료 ({len(uniq)} diseases) =====")
    print(f"결과 테이블: {OUT}")


if __name__ == "__main__":
    main()
