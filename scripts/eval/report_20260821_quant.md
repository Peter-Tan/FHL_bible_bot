# Deterministic (percentage) evaluation — computed from run logs

All rates are measured from the answer text + captured tool evidence.
No LLM judge involved.

| metric | v8 (2026-08-20) | v6 (2026-08-20) | v7 (2026-08-20) | v4 (2026-08-20) |
|---|---|---|---|---|
| questions | 50 | 50 | 50 | 50 |
| **FAITHFULNESS** | | | | |
| citations backed by a real lookup | 74.8% (178/238) | 89.4% (356/398) | 86.5% (230/266) | 88.2% (435/493) |
| quote support (strict) | 53.8% (14/26) | 61.4% (108/176) | 65.2% (150/230) | 58.7% (135/230) |
| quote support (lenient) | 57.7% | 76.1% | 83.9% | 71.3% |
| verse links valid | 100.0% (238/238) | 100.0% (398/398) | 100.0% (266/266) | 100.0% (493/493) |
| Strong's numbers in evidence | 80.0% (4/5) | 93.0% (66/71) | 87.5% (42/48) | 94.9% (93/98) |
| answers with a verifiable citation (non-adv) | 100.0% (44/44) | 100.0% (44/44) | 95.5% (42/44) | 100.0% (44/44) |
| answers that called >=1 tool (non-adv) | 100.0% | 100.0% | 100.0% | 100.0% |
| unsupported-quote rate, per-answer mean (macro) | 44.3% | 42.7% | 39.1% | 43.0% |
| quotes per answer (mean) | 0.5 | 3.5 | 4.6 | 4.6 |
| **COVERAGE** | | | | |
| citations per answer (mean) | 4.8 | 8.0 | 5.3 | 9.9 |
| evidence utilization (cited/fetched chapters) | 36.4% | 68.7% | 66.0% | 70.3% |
| citation recall vs all-engine union | 49.6% | 70.4% | 54.6% | 72.3% |
| **citation recall vs consensus set** | **52.5%** | **88.1%** | **76.7%** | **91.9%** |
| **RELEVANCY (negative signals only)** | | | | |
| declined when refusal was expected | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) |
| emitted code when asked for code (want 0%) | 0.0% (0/1) | 0.0% (0/1) | 0.0% (0/1) | 0.0% (0/1) |
| over-refusal on legitimate questions | 0.0% (0/44) | 0.0% (0/44) | 0.0% (0/44) | 0.0% (0/44) |
| empty answers | 0.0% | 0.0% | 0.0% | 0.0% |
| 答案含簡體字 | 0.0% | 0.0% | 0.0% | 2.0% |
