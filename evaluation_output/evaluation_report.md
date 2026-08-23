# CodeAbstract — Evaluation Report

> Generated: 2026-08-19 14:24:07  
> Privacy Level: `high`  
> Corpus: 10 files | Labeled dataset: 150 nodes

---

## Summary

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Privacy Information Ratio (PIR) | 0.0024 | ≤ 0.05 | ✅ |
| Token Hit Rate (Reconstruction) | 100.0% | ≥ 95% | ✅ |
| Classification Macro-F1 | 0.8937 | ≥ 0.85 | ✅ |
| AST Isomorphism Score | 1.0000 | 1.00 | ✅ |
| Syntax Validity Rate | 100.0% | 100% | ✅ |
| Throughput (LOC/sec) | 5,336 | ≥ 1,000 | ✅ |
| Mapping Accuracy | 0.9975 | ≥ 0.85 | ✅ |

---

## Pillar 1 — Privacy Leakage (PIR)

| File | SECRET Leakage | VALUE Leakage | PIR |
|------|---------------|--------------|-----|
| api_client | 0.0% | 0.0% | 0.0000 |
| ecommerce_pricing | 0.0% | 2.4% | 0.0244 |
| ml_pipeline | 0.0% | 0.0% | 0.0000 |
| web_server_config | 0.0% | 0.0% | 0.0000 |
| simple_utility | 0.0% | 0.0% | 0.0000 |
| auth_service | 0.0% | 0.0% | 0.0000 |
| financial_calculator | 0.0% | 0.0% | 0.0000 |
| database_layer | 0.0% | 0.0% | 0.0000 |
| microservice_router | 0.0% | 0.0% | 0.0000 |
| analytics_engine | 0.0% | 0.0% | 0.0000 |
| **Mean** | **0.0%** | **0.2%** | **0.0024** |

---

## Pillar 2 — Reconstruction Fidelity

| File | Tokens | Hit Rate | Roundtrip Fidelity |
|------|--------|----------|--------------------|
| api_client | 52 | 100.0% | 0.2761 |
| ecommerce_pricing | 49 | 100.0% | 0.2472 |
| ml_pipeline | 68 | 100.0% | 0.3016 |
| web_server_config | 45 | 100.0% | 0.3758 |
| simple_utility | 46 | 100.0% | 0.2655 |
| auth_service | 58 | 100.0% | 0.3155 |
| financial_calculator | 46 | 100.0% | 0.3080 |
| database_layer | 58 | 100.0% | 0.3214 |
| microservice_router | 49 | 100.0% | 0.3651 |
| analytics_engine | 55 | 100.0% | 0.2459 |
| **Mean** | – | **100.0%** | **0.3022** |

---

## Pillar 3 — Classification Accuracy

**Overall Accuracy**: 89.3%  (134/150 nodes)  
**Macro F1**: 0.8937

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------|
| SECRET | 0.9796 | 0.9600 | 0.9697 | 50 |
| VALUE | 0.8462 | 0.8800 | 0.8628 | 50 |
| IDENTIFIER | 0.8571 | 0.8400 | 0.8485 | 50 |
| **Macro** | **0.8943** | **0.8933** | **0.8937** | 150 |

### Confusion Matrix

| True \ Predicted | SECRET | VALUE | IDENTIFIER |
|-----------------|--------|-------|------------|
| SECRET | 48 | 1 | 1 |
| VALUE | 0 | 44 | 6 |
| IDENTIFIER | 1 | 7 | 42 |

---

## Pillar 4 — Code Structure Preservation

**Syntax Validity Rate**: 100.0%  
**Mean AST Isomorphism**: 1.0000  
**Mean Cyclomatic Complexity Delta**: 0.00

| File | Syntax Valid | AST Isom. | CC Delta | Abstr. Density |
|------|-------------|-----------|----------|----------------|
| api_client | ✅ | 1.0000 | 0 | 98.8% |
| ecommerce_pricing | ✅ | 1.0000 | 0 | 127.0% |
| ml_pipeline | ✅ | 1.0000 | 0 | 113.5% |
| web_server_config | ✅ | 1.0000 | 0 | 109.1% |
| simple_utility | ✅ | 1.0000 | 0 | 88.8% |
| auth_service | ✅ | 1.0000 | 0 | 102.3% |
| financial_calculator | ✅ | 1.0000 | 0 | 130.4% |
| database_layer | ✅ | 1.0000 | 0 | 103.8% |
| microservice_router | ✅ | 1.0000 | 0 | 118.6% |
| analytics_engine | ✅ | 1.0000 | 0 | 114.9% |

---

## Pillar 5 — Performance

**Mean Throughput**: 5,336 LOC/sec  
**Mean Abstraction Time**: 7.3 ms  
**Mean Encryption Round-trip**: 0.9 ms

| File | LOC | Abstract (ms) | Reconstruct (ms) | Throughput (LOC/s) |
|------|-----|--------------|-----------------|-------------------|
| api_client | 42 | 6.9 | 0.8 | 6,070 |
| ecommerce_pricing | 39 | 7.6 | 0.7 | 5,153 |
| ml_pipeline | 48 | 9.3 | 1.0 | 5,140 |
| web_server_config | 31 | 5.2 | 0.6 | 6,005 |
| simple_utility | 41 | 8.0 | 0.6 | 5,153 |
| auth_service | 42 | 7.3 | 0.8 | 5,727 |
| financial_calculator | 33 | 6.8 | 0.7 | 4,869 |
| database_layer | 41 | 7.7 | 0.8 | 5,325 |
| microservice_router | 36 | 7.0 | 0.7 | 5,175 |
| analytics_engine | 37 | 7.8 | 0.9 | 4,747 |

### Scaling Curve

| LOC | Abstraction Time (ms) | Throughput (LOC/s) |
|-----|----------------------|-------------------|
| 39 | 8.5 | 4,583 |
| 78 | 14.7 | 5,317 |
| 117 | 22.9 | 5,116 |
| 195 | 36.2 | 5,383 |
| 312 | 62.3 | 5,012 |

---

## Pillar 6 — Mapping Accuracy

**Mean Mapping Accuracy**: 0.9975  
**Definition-Site Accuracy**: 0.9946  
**Occurrence Accuracy**: 0.9955  
**Shadow Resolution**: 1.0000  
**Line-Map Accuracy**: 1.0000

| File | Definition | Occurrence | Shadow | Line Map | Overall |
|------|-----------|-----------|--------|----------|---------|
| api_client | 0.972 | 0.984 | 1.000 | 1.000 | 0.989 |
| ecommerce_pricing | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ml_pipeline | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| web_server_config | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| simple_utility | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| auth_service | 0.974 | 0.971 | 1.000 | 1.000 | 0.986 |
| financial_calculator | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| database_layer | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| microservice_router | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| analytics_engine | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

---

## Pillar 7 - Adversarial Re-identification

An attacker holding the original files and one abstracted file tries to say which file it came from. Structure survives abstraction by design, so this measures what that design costs.

| Privacy level | Top-1 | Top-3 | MRR | CPE | Advantage over chance | Identifiers surviving |
|---|---|---|---|---|---|---|
| `low` | 1.000 | 1.000 | 1.000 | 0.0006 | 1.000 | 0.864 |
| `medium` | 1.000 | 1.000 | 1.000 | 0.0006 | 1.000 | 0.582 |
| `high` | 1.000 | 1.000 | 1.000 | 0.0006 | 1.000 | 0.045 |
| `critical` | 1.000 | 1.000 | 1.000 | 0.0006 | 1.000 | 0.045 |

Random-guess baseline: 0.1000 (10 candidates). CPE 1.0 = attacker learned nothing; 0.0 = attacker is certain.

**Verdict:** The abstracted code is almost perfectly linkable back to its source. Structure alone identifies the file.

The token scheme also labels its own findings: `SECRET_n` marks where a credential sat, which the original identifier may not have revealed. Mean SECRET tokens per file, by level:

- `low`: 11.6
- `medium`: 11.6
- `high`: 11.6
- `critical`: 11.6

---

## Dataset Integrity (Pillar 3 caveat)

The classification F1 above is computed on a dataset whose labels were derived from the same patterns it grades. These figures measure how far that compromises the result.

| Check | Value | Reading |
|-------|-------|---------|
| Regex baseline accuracy | 0.8933 | the score any name-regex achieves by construction |
| Discriminative power | 0.1067 | only 16 of 150 items can separate two detectors |
| Rationale leakage | 0.6133 | share of labels justified by quoting the pattern list |
| Annotated blind | 0.0000 | share labelled without sight of the patterns |
| Provenance recorded | 0.0000 | share traceable to real-world code |

**Usable for detector comparison:** yes

- The naive regex baseline already scores 89.3% on this dataset, so most items cannot distinguish it from any other detector.
- 61.3% of rationales quote the pattern list, indicating labels were derived from the patterns under test.
- Only 0.0% of items were annotated blind to the pattern list; independence cannot be assumed for the rest.
- Only 0.0% of items record a provenance, so the sample cannot be traced to real-world code.