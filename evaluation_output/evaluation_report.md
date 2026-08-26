# CodeAbstract — Evaluation Report

> Generated: 2026-08-26 15:48:45  
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
| Throughput (LOC/sec) | 4,712 | ≥ 1,000 | ✅ |

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
| api_client | 47 | 100.0% | 0.0654 |
| ecommerce_pricing | 47 | 100.0% | 0.3113 |
| ml_pipeline | 64 | 100.0% | 0.2000 |
| web_server_config | 41 | 100.0% | 0.1210 |
| simple_utility | 44 | 100.0% | 0.3757 |
| auth_service | 57 | 100.0% | 0.2035 |
| financial_calculator | 46 | 100.0% | 0.4354 |
| database_layer | 48 | 100.0% | 0.3240 |
| microservice_router | 47 | 100.0% | 0.1520 |
| analytics_engine | 52 | 100.0% | 0.2857 |
| **Mean** | – | **100.0%** | **0.2474** |

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
| api_client | ✅ | 1.0000 | 0 | 104.9% |
| ecommerce_pricing | ✅ | 1.0000 | 0 | 127.0% |
| ml_pipeline | ✅ | 1.0000 | 0 | 115.7% |
| web_server_config | ✅ | 1.0000 | 0 | 101.8% |
| simple_utility | ✅ | 1.0000 | 0 | 88.8% |
| auth_service | ✅ | 1.0000 | 0 | 106.8% |
| financial_calculator | ✅ | 1.0000 | 0 | 130.4% |
| database_layer | ✅ | 1.0000 | 0 | 97.5% |
| microservice_router | ✅ | 1.0000 | 0 | 118.6% |
| analytics_engine | ✅ | 1.0000 | 0 | 114.9% |

---

## Pillar 5 — Performance

**Mean Throughput**: 4,712 LOC/sec  
**Mean Abstraction Time**: 8.8 ms  
**Mean Encryption Round-trip**: 1.6 ms

| File | LOC | Abstract (ms) | Reconstruct (ms) | Throughput (LOC/s) |
|------|-----|--------------|-----------------|-------------------|
| api_client | 42 | 10.2 | 1.1 | 4,133 |
| ecommerce_pricing | 39 | 10.3 | 0.9 | 3,788 |
| ml_pipeline | 48 | 16.1 | 0.8 | 2,985 |
| web_server_config | 31 | 6.2 | 0.5 | 5,024 |
| simple_utility | 41 | 9.7 | 0.8 | 4,223 |
| auth_service | 42 | 8.4 | 0.7 | 4,990 |
| financial_calculator | 33 | 6.6 | 0.8 | 4,994 |
| database_layer | 41 | 6.6 | 0.5 | 6,207 |
| microservice_router | 36 | 6.6 | 1.1 | 5,484 |
| analytics_engine | 37 | 7.0 | 0.7 | 5,291 |

### Scaling Curve

| LOC | Abstraction Time (ms) | Throughput (LOC/s) |
|-----|----------------------|-------------------|
| 39 | 14.9 | 2,609 |
| 78 | 16.2 | 4,809 |
| 117 | 18.4 | 6,344 |
| 195 | 39.9 | 4,883 |
| 312 | 44.6 | 6,998 |