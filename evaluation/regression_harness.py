"""
Historical Regression Harness

Phase 3 — exit criterion: *the suite reproduces every Phase 0 defect when
run against the pre-fix commit.*

An evaluation that has never failed is not known to be capable of failing.
Every pillar in this project reported green while the system was
transmitting live API keys, so "the tests pass" carries no weight until the
suite has been shown to go red against code that is known to be broken.

This harness checks out a historical commit into a temporary directory,
loads *that* commit's abstraction engine, and runs the current defect
probes against it. The probes come from ``docs/AUDIT.md`` — the same inputs
that reproduced each defect during the audit.

Nothing is mutated: ``git archive`` writes to a scratch directory and the
working tree is never touched, so this is safe to run against uncommitted
work.
"""

import ast
import importlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

# The audit's reproductions, as executable probes. Each returns True when
# the defect is PRESENT.
LEAK_SOURCE = '''
api_key = "sk_live_51H8xQ2eZvKYlo2C"
db_pass = "hunter2"
conn = f"postgres://admin:{db_pass}@10.2.3.4:5432/prod_billing"
header = f"Bearer sk_live_51H8xQ2eZvKYlo2C"
'''

SHADOW_SOURCE = '''def alpha(data):
    result = data * 2
    return result

def beta(data):
    result = data + 1
    return result
'''

IMPORT_SOURCE = 'import stripe\nfrom acme_internal.billing import ledger\nledger.post(1)\n'


@dataclass
class DefectCheck:
    """One defect probe."""

    defect_id: str
    description: str
    probe: Callable


@dataclass
class CheckOutcome:
    """Result of running one probe against one commit."""

    defect_id: str
    description: str
    defect_present: bool
    detail: str = ""
    error: str = ""


@dataclass
class RegressionReport:
    """All probes run against one commit."""

    commit: str
    outcomes: List[CheckOutcome] = field(default_factory=list)

    @property
    def defects_found(self) -> int:
        return sum(1 for o in self.outcomes if o.defect_present)

    @property
    def errors(self) -> int:
        return sum(1 for o in self.outcomes if o.error)

    def summary(self) -> str:
        lines = [f"Commit {self.commit}: "
                 f"{self.defects_found}/{len(self.outcomes)} defects present"]
        for outcome in self.outcomes:
            if outcome.error:
                mark = "ERROR"
            elif outcome.defect_present:
                mark = "PRESENT"
            else:
                mark = "absent"
            lines.append(f"  {outcome.defect_id:4s} {mark:8s} {outcome.description}")
            if outcome.detail:
                lines.append(f"       {outcome.detail}")
            if outcome.error:
                lines.append(f"       {outcome.error}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# Probes
# ═══════════════════════════════════════════════════════════

def _probe_d1(engine) -> CheckOutcome:
    """D1 — secret literals transmitted verbatim."""
    leaked = []
    for level in ("low", "medium", "high", "critical"):
        code = engine.abstract(LEAK_SOURCE, privacy_level=level).abstract_code
        for secret in ("sk_live_51H8xQ2eZvKYlo2C", "hunter2", "prod_billing"):
            if secret in code:
                leaked.append(f"{level}:{secret[:18]}")
    return CheckOutcome(
        defect_id="D1",
        description="secret literals transmitted verbatim",
        defect_present=bool(leaked),
        detail=f"{len(leaked)} leak(s): {', '.join(leaked[:4])}" if leaked else "",
    )


def _probe_d2(engine, reconstruct) -> CheckOutcome:
    """D2 — token prefix collision in RECONSTRUCT."""
    source = "\n".join(f"variable_number_{i} = {i}" for i in range(12))
    result = engine.abstract(source, privacy_level="high")
    translated = reconstruct(
        "Bug in VAR_1 and also VAR_10 is wrong.",
        result.encrypted_mapping,
        result.encryption_key,
    )
    first_line = translated.split("\n")[0]
    corrupted = "variable_number_10" not in first_line
    return CheckOutcome(
        defect_id="D2",
        description="VAR_1 substitutes itself inside VAR_10",
        defect_present=corrupted,
        detail=first_line.strip() if corrupted else "",
    )


def _probe_d3(engine) -> CheckOutcome:
    """D3 — imports leak vendor and internal package names."""
    code = engine.abstract(IMPORT_SOURCE, privacy_level="high").abstract_code
    leaked = [n for n in ("stripe", "acme_internal", "ledger") if n in code]
    return CheckOutcome(
        defect_id="D3",
        description="import statements leak vendor / internal names",
        defect_present=bool(leaked),
        detail=f"survived: {', '.join(leaked)}" if leaked else "",
    )


def _probe_d4(engine) -> CheckOutcome:
    """D4 — scope-blind token cache collapses shadowed names."""
    result = engine.abstract(SHADOW_SOURCE, privacy_level="high")
    from algorithms.encrypt import decrypt_mapping
    mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
    tokens = [t for t, e in mapping.items() if e['name'] == 'result']
    collapsed = len(tokens) < 2
    return CheckOutcome(
        defect_id="D4",
        description="shadowed names collapse into one token",
        defect_present=collapsed,
        detail=f"'result' got {len(tokens)} token(s), expected 2" if collapsed else "",
    )


def _probe_d5(engine) -> CheckOutcome:
    """D5 — critical privacy level is a no-op."""
    source = "def f(x):\n    total_amount = x * 2\n    return total_amount\n"
    high = engine.abstract(source, privacy_level="high").abstract_code
    critical = engine.abstract(source, privacy_level="critical").abstract_code
    return CheckOutcome(
        defect_id="D5",
        description="'critical' is byte-identical to 'high'",
        defect_present=(high == critical),
        detail="outputs identical" if high == critical else "",
    )


# ═══════════════════════════════════════════════════════════
# Running against a commit
# ═══════════════════════════════════════════════════════════

def export_commit(commit: str, destination: Path) -> Path:
    """
    Extract *commit* into *destination* without touching the working tree.

    Args:
        commit: Any git revision.
        destination: Directory to populate.

    Returns:
        The populated directory.

    Raises:
        RuntimeError: If the export fails.
    """
    destination.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", commit],
        capture_output=True,
        check=False,
    )
    if archive.returncode != 0:
        raise RuntimeError(
            f"git archive {commit} failed: "
            f"{archive.stderr.decode('utf-8', 'replace')[:200]}"
        )

    extract = subprocess.run(
        ["tar", "-x", "-C", str(destination)],
        input=archive.stdout,
        capture_output=True,
        check=False,
    )
    if extract.returncode != 0:
        raise RuntimeError(
            f"tar extraction failed: "
            f"{extract.stderr.decode('utf-8', 'replace')[:200]}"
        )
    return destination


def run_against_commit(commit: str = "HEAD") -> RegressionReport:
    """
    Run every defect probe against a historical commit's engine.

    Args:
        commit: Git revision to test.

    Returns:
        A :class:`RegressionReport`.

    Raises:
        RuntimeError: If the commit cannot be exported.
    """
    report = RegressionReport(commit=commit)
    scratch = Path(tempfile.mkdtemp(prefix="codeabstract-regression-"))

    # Modules whose historical versions must shadow the current ones.
    swapped = [
        name for name in list(sys.modules)
        if name.split('.')[0] in ('algorithms', 'core', 'config', 'evaluation')
    ]
    saved = {name: sys.modules[name] for name in swapped}
    original_path = list(sys.path)

    try:
        export_commit(commit, scratch)

        for name in swapped:
            del sys.modules[name]
        sys.path.insert(0, str(scratch))

        engine = importlib.import_module("algorithms.abstract")
        reconstruct = importlib.import_module("algorithms.reconstruct").reconstruct

        probes = [
            ("D1", lambda: _probe_d1(engine)),
            ("D2", lambda: _probe_d2(engine, reconstruct)),
            ("D3", lambda: _probe_d3(engine)),
            ("D4", lambda: _probe_d4(engine)),
            ("D5", lambda: _probe_d5(engine)),
        ]

        for defect_id, probe in probes:
            try:
                report.outcomes.append(probe())
            except Exception as error:  # a probe must never abort the run
                report.outcomes.append(CheckOutcome(
                    defect_id=defect_id,
                    description="probe raised",
                    defect_present=False,
                    error=f"{type(error).__name__}: {error}",
                ))

    finally:
        sys.path[:] = original_path
        for name in list(sys.modules):
            if name.split('.')[0] in ('algorithms', 'core', 'config', 'evaluation'):
                del sys.modules[name]
        sys.modules.update(saved)
        shutil.rmtree(scratch, ignore_errors=True)

    return report


def run_against_working_tree() -> RegressionReport:
    """
    Run the same probes against the code currently on disk.

    Needed as the control: probes that fire on a broken commit prove
    nothing unless they also stay quiet on a fixed one. Uncommitted work
    is invisible to :func:`run_against_commit`, so this path imports the
    live modules instead.

    Returns:
        A :class:`RegressionReport` labelled ``working-tree``.
    """
    import algorithms.abstract as engine
    from algorithms.reconstruct import reconstruct

    report = RegressionReport(commit="working-tree")
    probes = [
        ("D1", lambda: _probe_d1(engine)),
        ("D2", lambda: _probe_d2(engine, reconstruct)),
        ("D3", lambda: _probe_d3(engine)),
        ("D4", lambda: _probe_d4(engine)),
        ("D5", lambda: _probe_d5(engine)),
    ]
    for defect_id, probe in probes:
        try:
            report.outcomes.append(probe())
        except Exception as error:
            report.outcomes.append(CheckOutcome(
                defect_id=defect_id,
                description="probe raised",
                defect_present=False,
                error=f"{type(error).__name__}: {error}",
            ))
    return report


def verify_suite_can_fail(
    broken_commit: str = "47d91bc",
    expected_defects: int = 4,
) -> Dict[str, object]:
    """
    Confirm the probes go red against known-broken code.

    This is the exit criterion in executable form. If the probes report a
    clean bill of health for a commit the audit reproduced defects on, the
    probes are wrong, not the commit.

    Args:
        broken_commit: A commit known to carry the Phase 0 defects.
        expected_defects: Minimum defects that must be detected.

    Returns:
        ``{'passed': bool, 'report': RegressionReport, 'reason': str}``.
    """
    report = run_against_commit(broken_commit)
    found = report.defects_found
    passed = found >= expected_defects

    return {
        'passed': passed,
        'report': report,
        'found': found,
        'expected': expected_defects,
        'reason': (
            f"detected {found} defect(s) at {broken_commit}, "
            f"expected at least {expected_defects}"
        ),
    }
