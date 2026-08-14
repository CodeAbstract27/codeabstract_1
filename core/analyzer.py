"""
Privacy Risk & Exposure Analyzer

Analyzes Python AST to compute Privacy Exposure Scores, identify sensitive nodes,
and classify security risk levels prior to LLM code consultation.
"""

import ast
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Tuple
from core.ast_parser import parse_source
from core.pattern_matcher import matches_any
from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class SecretFinding:
    line_number: int
    node_name: str
    pattern_matched: str
    category: str


@dataclass
class AuditReport:
    exposure_score: float
    risk_level: RiskLevel
    total_nodes: int
    secret_count: int
    value_count: int
    findings: List[SecretFinding]


class PrivacyAnalyzer:
    """Analyzes AST nodes to compute Privacy Exposure Scores."""

    def __init__(self, source_code: str):
        self.source_code = source_code

    def analyze(self) -> AuditReport:
        if not self.source_code.strip():
            return AuditReport(
                exposure_score=0.0,
                risk_level=RiskLevel.LOW,
                total_nodes=0,
                secret_count=0,
                value_count=0,
                findings=[],
            )

        try:
            tree = parse_source(self.source_code)
        except Exception as e:
            raise ValueError(f"Invalid Python syntax: {e}")

        total_nodes = 0
        secret_count = 0
        value_count = 0
        findings: List[SecretFinding] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.FunctionDef, ast.ClassDef, ast.arg)):
                total_nodes += 1
                name = getattr(node, "id", None) or getattr(node, "name", None) or getattr(node, "arg", None)
                if not name:
                    continue

                lineno = getattr(node, "lineno", 1)

                if matches_any(name, SECRET_PATTERNS):
                    secret_count += 1
                    findings.append(
                        SecretFinding(
                            line_number=lineno,
                            node_name=name,
                            pattern_matched="SECRET_PATTERN",
                            category="SECRET",
                        )
                    )
                elif matches_any(name, VALUE_PATTERNS):
                    value_count += 1
                    findings.append(
                        SecretFinding(
                            line_number=lineno,
                            node_name=name,
                            pattern_matched="VALUE_PATTERN",
                            category="VALUE",
                        )
                    )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                total_nodes += 1
                val_str = str(node.value)
                lineno = getattr(node, "lineno", 1)
                if matches_any(val_str, SECRET_PATTERNS) or any(
                    kw in val_str.lower() for kw in ["sk_live", "sk_test", "bearer ", "password="]
                ):
                    secret_count += 1
                    findings.append(
                        SecretFinding(
                            line_number=lineno,
                            node_name=val_str[:15] + "...",
                            pattern_matched="STRING_SECRET_LITERAL",
                            category="SECRET",
                        )
                    )

        if total_nodes == 0:
            exposure_score = 0.0
        else:
            weighted_score = (5.0 * secret_count + 1.5 * value_count) / max(1, total_nodes)
            exposure_score = min(100.0, round(weighted_score * 100.0, 2))

        if exposure_score == 0.0:
            risk_level = RiskLevel.LOW
        elif exposure_score < 20.0:
            risk_level = RiskLevel.LOW
        elif exposure_score <= 50.0:
            risk_level = RiskLevel.MEDIUM
        elif exposure_score <= 75.0:
            risk_level = RiskLevel.HIGH
        else:
            risk_level = RiskLevel.CRITICAL

        return AuditReport(
            exposure_score=exposure_score,
            risk_level=risk_level,
            total_nodes=total_nodes,
            secret_count=secret_count,
            value_count=value_count,
            findings=findings,
        )
