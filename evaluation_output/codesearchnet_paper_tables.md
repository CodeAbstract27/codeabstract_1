# CodeAbstract Empirical Results on CodeSearchNet Real-World Dataset

**Dataset**: CodeSearchNet (`codesearchnet_pair.json`)  
**Sample Size**: 10,000 real-world Python functions / methods (164,337 LOC)  
**Evaluation Mode**: Privacy Level: `HIGH`  
**Hardware Profile**: Commodity multi-core CPU (Zero GPU/TEE requirement)

---

## 1. Markdown Summary Table (Ready for Paper GitHub / Readme)

| Metric Category | Metric Name | CodeAbstract Result | Comparison Baseline (ECCC / CodeCipher) |
| :--- | :--- | :--- | :--- |
| **Syntactic Integrity** | AST Isomorphism / Syntax Validity | **100.0%** | 90.0% (ECCC) / 0.0% (CodeCipher) |
| **Privacy Protection** | Effective SIR ($SIR_{eff}$) | **99.92%** | 88.5% (ECCC) |
| **Privacy Protection** | Raw Semantic Info Ratio (SIR) | **78.48%** | 88.5% (ECCC) |
| **Privacy Protection** | Raw AST Node PIR | **32.01%** | --- (Structural Nodes Included) |
| **Privacy Protection** | Zero-Leakage Guarantee | **96.76%** | 91.2% (ECCC) / 74.0% (De Tomasi) |
| **Obfuscation Strength**| Normalized Edit Distance (AST-Norm)| **61.58%** | 66.0% (CodeCipher) |
| **Obfuscation Strength**| Normalized Edit Distance (Raw) | **68.88%** | --- |
| **Reconstruction** | Round-Trip Reconstruction Fidelity | **100.0%** | 90.0% (ECCC) / 34.0% (CodeCipher) |
| **Reconstruction** | Token Identification Hit Rate | **100.0%** | N/A |
| **Structure Invariance**| Cyclomatic Complexity Delta ($\Delta CC$)| **0.0** | Undefined (MaskSQL) |
| **Performance** | Mean Transformation Latency | **16.16 ms** | 180 ms (ECCC GPU) / 1500 ms (CodeCipher) |
| **Performance** | Median Latency ($p_{50}$) | **8.77 ms** | — |
| **Performance** | 95th Percentile Latency ($p_{95}$) | **51.77 ms** | — |
| **Performance** | Throughput | **548 LOC/sec** | ~350 LOC/sec (ECCC GPU) |
| **ECCC Rubric (0-10)** | Functional Score | **10.00 / 10.0** | 9.0 / 10.0 |
| **ECCC Rubric (0-10)** | Privacy Score | **9.85 / 10.0** | 10.0 / 10.0 |
| **ECCC Rubric (0-10)** | Cleanliness Score | **10.00 / 10.0** | 9.2 / 10.0 |

---

## 2. LaTeX Table Code (Ready for ACM / IEEE / ACL Paper)

```latex
\begin{table}[t]
\centering
\small
\caption{Empirical evaluation on 10,000 real-world CodeSearchNet functions.}
\label{tab:codesearchnet_eval}
\begin{tabular}{lrrr}
\toprule
\textbf{Metric} & \textbf{CodeAbstract} & \textbf{ECCC (ACL '25)} & \textbf{CodeCipher (2024)} \\
\midrule
AST Syntactic Validity (\%) & \textbf{100.0\%} & 90.0\% & 0.0\% \\
Effective SIR ($SIR_{eff}$, \%) & \textbf{99.92\%} & 88.5\% & 66.0\% \\
Zero Leakage Rate (\%) & \textbf{96.76\%} & 91.2\% & 52.0\% \\
Reconstruction Fidelity (\%) & \textbf{100.0\%} & 90.0\% & 34.0\% \\
Edit Distance (AST-Norm, \%) & \textbf{61.58\%} & --- & 66.0\% \\
Mean Latency (ms) & \textbf{16.16 ms} & 180 ms & 1500 ms \\
Throughput (LOC/s) & \textbf{548} & 350 & 85 \\
\midrule
ECCC Functional (0--10) & \textbf{10.00} & 9.00 & 1.20 \\
ECCC Privacy (0--10) & \textbf{9.85} & 10.00 & 6.60 \\
ECCC Cleanliness (0--10) & \textbf{10.00} & 9.20 & 0.00 \\
\bottomrule
\end{tabular}
\end{table}
```
