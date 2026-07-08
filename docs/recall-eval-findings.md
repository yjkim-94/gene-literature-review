# Recall eval findings (2026-07-07)

## 목적

`evals/run_eval.py`의 기존 recall smoke test는 top-20 포함 여부만 보므로, 정답 gene이 상위에 있는지와 누락 원인이 무엇인지 설명하지 못했다. 이번 변경은 ranking algorithm을 바꾸지 않고, eval harness와 OT stress test 구성을 보강했다.

## 변경 사항

- `evals/evals.json`을 disease-only OpenTargets eval로 재구성했다.
- `.gt_cache`에 저장된 OpenTargets genetic_association gold가 30개 이상인 disease keyword만 사용했다.
- 각 keyword의 `gold_genes`는 `genetic_association >= 0.5` 중 score 상위 30개로 고정했다.
- default eval 규모를 `--max 30 --scan 200`으로 올렸다.
- `--entity`를 지원해 disease keyword는 PubTator disease entity로 scan한다.
- keyword별 `recall@10`, `recall@30`, gold gene rank median/mean, miss 원인(`pool-miss` vs `rank-cut`)을 출력한다.
- 결과 markdown을 `evals/output/recall_eval.md`에 저장한다.

## 현재 결과

Command: `python evals\run_eval.py`

| metric | value |
|---|---:|
| keywords | 12 |
| gold genes per keyword | 30 |
| mean recall@30 | 0.13 |

상세 결과는 `evals/output/recall_eval.md`에 저장됐다.

## 해석

OpenTargets genetic gold는 문헌 co-occurrence ranking과 독립적인 축이라, 이 결과는 main 성능 점수가 아니라 stress test다. 낮은 mean recall@30은 주로 `pool-miss`에서 발생했다. 즉 많은 OT genetic gold gene이 PubTator keyword paper scan의 scored candidate pool에 들어오지 않는다.

## 한계

- 이 스킬의 Phase 1은 문헌에서 keyword 맥락으로 특이적으로 연구된 gene을 찾는다.
- OT genetic gold는 variant/GWAS 기반 disease association이라 목표 함수가 다르다.
- 따라서 OT 단독 gold로 "스킬 성능이 낮다"고 결론 내리면 안 된다.
- main eval은 GO/Reactome/MSigDB/curated review처럼 task-aligned gold로 별도 구성해야 한다.
- OT 결과는 문헌 ranking이 genetic association을 얼마나 놓치는지 보는 보조 지표로만 유지한다.

## 검증

- `python -m py_compile evals\run_eval.py`: pass
- `python evals\run_eval.py`: pass

## Task-aligned GO-BP eval

> **⚠ 폐기 (2026-07-08).** 이 GO-BP task-aligned eval은 폐기됨(recall@30 0.14는 gold-tool construct 불일치의
> artifact — pathway membership ≠ literature prominence). 참조 파일 `evals/evals_task_aligned.json`·
> `evals/output/task_aligned_recall_eval.md`는 삭제됨. 근거·경과는 `dev_state.md`(2026-07-08)와
> `docs/task-aligned-gold-design.md` 배너 참조. 아래 표는 역사 기록. (위 §1–검증까지의 `run_eval.py` OT stress
> test는 유지 대상.)

별도 main-eval 초안으로 `evals/evals_task_aligned.json`을 추가했다. QuickGO GO-BP에서 5 keyword를 고르고 각 30 human genes를 gold로 고정했다. 실행 설정은 `--max 30`, `scan=500`이다.

| keyword | recall@30 | pool-miss | rank-cut |
|---|---:|---:|---:|
| ferroptosis | 0.23 | 22 | 1 |
| autophagy | 0.23 | 20 | 3 |
| apoptotic process | 0.10 | 27 | 0 |
| inflammatory response | 0.07 | 28 | 0 |
| DNA repair | 0.07 | 20 | 8 |

Mean recall@30은 0.14다. `DNA repair`는 full run 중 한 번 transient failure가 났지만, 단독 재실행은 성공했고 `evals/output/task_aligned_recall_eval.md`를 생성했다. scan을 500으로 올려도 miss의 대부분은 `pool-miss`라서, ranking보다 candidate discovery/scan 단계가 병목이다.
