"""
Adversarial Re-identification

Phase 3 — the validation story the proposal calls "Adversarial Novelty".

Every metric shipped before this one grades the system on whether it did
what it set out to do. None asks the question an attacker asks: *given only
the abstracted code, how much of the original can I recover?* A privacy
system that is never attacked has not been evaluated.

Three attacks are implemented, all offline and deterministic:

1. **Linkage** (:func:`run_linkage_attack`) — the attacker holds a pool of
   candidate source files and one abstracted file, and must say which
   candidate it came from. This is the standard re-identification setup
   from the anonymisation literature, and it is the one that matters here:
   abstraction claims to hide *which* proprietary code you are asking
   about, and linkage tests exactly that claim.

2. **Token-prefix leakage** (:func:`measure_prefix_leakage`) — the token
   scheme itself announces the classifier's verdict. ``SECRET_0`` tells an
   observer "a credential lives here", which is information the original
   identifier did not necessarily reveal.

3. **Alignment channels** (:func:`inventory_alignment_channels`) — text
   that survives abstraction verbatim (allowlisted imports, builtins,
   preserved type names) and lets an attacker anchor tokens to known
   quantities.

The headline number is **Code Privacy Entropy** (:func:`code_privacy_entropy`):
the normalised entropy of the attacker's posterior over candidates. CPE of
1.0 means the attacker learned nothing; 0.0 means they identified the source
exactly.
"""

import ast
import math
from collections import Counter
from dataclasses import dataclass, field

from typing import Dict, List, Optional, Sequence, Tuple

# Node types that carry structure rather than identity. These survive
# abstraction by design -- preserving them is the point -- which is
# precisely why they are what an attacker fingerprints on.
_STRUCTURAL_NODES = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For,
    ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Return,
    ast.Raise, ast.Assert, ast.Assign, ast.AugAssign, ast.AnnAssign,
    ast.Call, ast.Compare, ast.BoolOp, ast.BinOp, ast.UnaryOp,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
    ast.Lambda, ast.Yield, ast.Await, ast.Import, ast.ImportFrom,
)


# Length of the node-type n-grams used for the ordered similarity term.
_NGRAM = 3


@dataclass
class Fingerprint:
    """A structural signature of a file, carrying no identifiers."""

    node_sequence: List[str] = field(default_factory=list)
    arities: List[int] = field(default_factory=list)
    depths: List[int] = field(default_factory=list)
    node_counts: Dict[str, int] = field(default_factory=dict)
    n_statements: int = 0
    ngrams: Counter = field(default_factory=Counter)

    def similarity(self, other: "Fingerprint") -> float:
        """
        Structural similarity to another fingerprint, in [0, 1].

        Blends an ordered term (n-gram overlap over the node-type sequence)
        with an unordered term (node-type frequencies) and function arity
        agreement. The ordered term catches "same code, renamed"; the
        unordered term stays robust to small edits.

        N-grams rather than an edit-distance ratio: a linkage attack scores
        every candidate against every target, and an O(n²) comparison over
        a 120-file corpus does not finish. Counted n-gram overlap is O(n)
        per pair and empirically discriminates just as sharply here.
        """
        if not self.node_sequence or not other.node_sequence:
            return 0.0

        ordered = _counter_overlap(self.ngrams, other.ngrams)
        unordered = _counter_overlap(
            Counter(self.node_counts), Counter(other.node_counts)
        )
        arity = _sequence_agreement(self.arities, other.arities)

        return round(0.5 * ordered + 0.35 * unordered + 0.15 * arity, 6)


def _counter_overlap(a: Counter, b: Counter) -> float:
    """Weighted Jaccard (min-over-max) between two multisets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    intersection = sum((a & b).values())
    union = sum((a | b).values())
    return intersection / union if union else 0.0


def _sequence_agreement(a: Sequence[int], b: Sequence[int]) -> float:
    """Multiset agreement between two integer sequences."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    counter_a, counter_b = Counter(a), Counter(b)
    overlap = sum((counter_a & counter_b).values())
    total = max(sum(counter_a.values()), sum(counter_b.values()))
    return overlap / total if total else 0.0


def fingerprint(source_code: str) -> Fingerprint:
    """
    Extract a structural fingerprint, discarding every identifier.

    The attacker never sees names — only shape. That is exactly the
    information abstraction is designed to preserve.

    Args:
        source_code: Python source (original or abstracted).

    Returns:
        A :class:`Fingerprint`. Empty if the source does not parse.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return Fingerprint()

    sequence: List[str] = []
    arities: List[int] = []
    depths: List[int] = []

    def walk(node: ast.AST, depth: int) -> None:
        if isinstance(node, _STRUCTURAL_NODES):
            sequence.append(type(node).__name__)
            depths.append(depth)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            arities.append(
                len(getattr(args, 'posonlyargs', []) or [])
                + len(args.args or [])
                + len(args.kwonlyargs or [])
            )
        for child in ast.iter_child_nodes(node):
            walk(child, depth + 1)

    walk(tree, 0)

    ngrams = Counter(
        tuple(sequence[i:i + _NGRAM])
        for i in range(max(0, len(sequence) - _NGRAM + 1))
    )

    return Fingerprint(
        node_sequence=sequence,
        arities=arities,
        depths=depths,
        node_counts=dict(Counter(sequence)),
        n_statements=len([n for n in ast.walk(tree) if isinstance(n, ast.stmt)]),
        ngrams=ngrams,
    )


# ═══════════════════════════════════════════════════════════
# Attack 1 — linkage
# ═══════════════════════════════════════════════════════════

@dataclass
class LinkageResult:
    """Outcome of a single linkage attempt."""

    true_name: str
    predicted_name: str
    correct: bool
    rank: int                     # 1 = identified on the first guess
    n_candidates: int
    posterior: List[float] = field(default_factory=list)
    margin: float = 0.0           # top score minus runner-up

    @property
    def reciprocal_rank(self) -> float:
        return 1.0 / self.rank if self.rank else 0.0


@dataclass
class LinkageReport:
    """Aggregated linkage attack across a corpus."""

    privacy_level: str
    n_files: int
    top1_accuracy: float
    top3_accuracy: float
    mean_reciprocal_rank: float
    random_baseline: float
    code_privacy_entropy: float
    per_file: List[LinkageResult] = field(default_factory=list)

    @property
    def advantage(self) -> float:
        """
        How far the attacker beats guessing.

        Reported as the lift over chance rather than raw accuracy, because
        raw accuracy is not comparable across corpora of different sizes.
        """
        if self.random_baseline >= 1.0:
            return 0.0
        return round(
            (self.top1_accuracy - self.random_baseline) / (1 - self.random_baseline),
            4,
        )

    def verdict(self) -> str:
        """Plain-language reading of the result."""
        if self.advantage >= 0.90:
            return (
                "The abstracted code is almost perfectly linkable back to its "
                "source. Structure alone identifies the file."
            )
        if self.advantage >= 0.50:
            return "The attacker substantially outperforms chance."
        if self.advantage >= 0.15:
            return "The attacker gains a modest but real advantage."
        return "The attacker does no better than guessing."


def _softmax(scores: Sequence[float], temperature: float = 0.05) -> List[float]:
    """
    Convert similarity scores into a posterior over candidates.

    The temperature controls how decisively the attacker commits. It is
    fixed and documented rather than tuned, because tuning it against the
    system under test would let the evaluation flatter itself.
    """
    if not scores:
        return []
    scaled = [s / temperature for s in scores]
    peak = max(scaled)
    exponentiated = [math.exp(s - peak) for s in scaled]
    total = sum(exponentiated)
    return [e / total for e in exponentiated] if total else [
        1.0 / len(scores)
    ] * len(scores)


def code_privacy_entropy(posterior: Sequence[float]) -> float:
    """
    Normalised Shannon entropy of the attacker's posterior.

    CPE = H(posterior) / log2(N).

    1.0 — the posterior is uniform; the attacker learned nothing.
    0.0 — the posterior is a point mass; the attacker is certain.

    Normalising by ``log2(N)`` makes the figure comparable across corpora
    of different sizes, which raw entropy is not.

    Args:
        posterior: Probabilities over candidates, summing to 1.

    Returns:
        CPE in [0, 1].
    """
    n = len(posterior)
    if n <= 1:
        return 0.0

    entropy = -sum(p * math.log2(p) for p in posterior if p > 0)
    return round(entropy / math.log2(n), 6)


def run_linkage_attack(
    files: Sequence[Dict],
    privacy_level: str = "high",
    abstract_fn=None,
) -> LinkageReport:
    """
    Attempt to re-identify each abstracted file within a candidate pool.

    The attacker's knowledge is deliberately generous: they hold the
    original source of every candidate. This is the right threat model for
    the project's own use case — a company's repository is not secret from
    its own employees, and the claim under test is that *the LLM* cannot
    tell which file it is looking at.

    Args:
        files: Corpus entries with ``name`` and ``code``.
        privacy_level: Level to abstract at.
        abstract_fn: Injectable abstraction function, for testing.

    Returns:
        A :class:`LinkageReport`.

    Raises:
        ValueError: If fewer than two candidates are supplied.
    """
    if len(files) < 2:
        raise ValueError("a linkage attack needs at least two candidates")

    if abstract_fn is None:
        from algorithms.abstract import abstract as abstract_fn

    candidate_names = [entry['name'] for entry in files]
    candidate_prints = [fingerprint(entry['code']) for entry in files]

    results: List[LinkageResult] = []
    entropies: List[float] = []

    for index, entry in enumerate(files):
        abstracted = abstract_fn(
            entry['code'], privacy_level=privacy_level
        ).abstract_code
        target = fingerprint(abstracted)

        scores = [target.similarity(candidate) for candidate in candidate_prints]
        posterior = _softmax(scores)
        entropies.append(code_privacy_entropy(posterior))

        ranked = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )
        rank = ranked.index(index) + 1
        best = ranked[0]
        runner_up = scores[ranked[1]] if len(ranked) > 1 else 0.0

        results.append(LinkageResult(
            true_name=entry['name'],
            predicted_name=candidate_names[best],
            correct=(best == index),
            rank=rank,
            n_candidates=len(files),
            posterior=[round(p, 6) for p in posterior],
            margin=round(scores[best] - runner_up, 6),
        ))

    n = len(results)
    return LinkageReport(
        privacy_level=privacy_level,
        n_files=n,
        top1_accuracy=round(sum(1 for r in results if r.correct) / n, 4),
        top3_accuracy=round(sum(1 for r in results if r.rank <= 3) / n, 4),
        mean_reciprocal_rank=round(
            sum(r.reciprocal_rank for r in results) / n, 4
        ),
        random_baseline=round(1 / n, 4),
        code_privacy_entropy=round(sum(entropies) / len(entropies), 6),
        per_file=results,
    )


# ═══════════════════════════════════════════════════════════
# Attack 2 — token prefix leakage
# ═══════════════════════════════════════════════════════════

@dataclass
class PrefixLeakage:
    """How much the token naming scheme reveals on its own."""

    n_tokens: int
    prefix_counts: Dict[str, int] = field(default_factory=dict)
    secret_positions_revealed: int = 0
    classification_entropy: float = 0.0

    @property
    def reveals_secret_locations(self) -> bool:
        return self.secret_positions_revealed > 0


def measure_prefix_leakage(abstract_code: str) -> PrefixLeakage:
    """
    Quantify what the token scheme discloses without any mapping table.

    ``SECRET_0`` is a label, not just a placeholder: it tells whoever reads
    the abstracted code that a credential sat at that position. The
    original identifier may not have revealed that — a variable called
    ``cfg`` gives nothing away, while ``SECRET_3`` marks it precisely.

    This is a design trade-off rather than a defect: distinct prefixes help
    the model reason and help reconstruction stay unambiguous. It is
    recorded here so the cost is stated rather than assumed away.

    Args:
        abstract_code: The emitted abstract source.

    Returns:
        A :class:`PrefixLeakage`.
    """
    import re

    tokens = re.findall(
        r'\b(FUNC|VAR|SECRET|CONST|NUM|CLASS|MODULE)_\d+\b', abstract_code
    )
    counts = dict(Counter(tokens))
    total = len(tokens)

    entropy = 0.0
    if total:
        for count in counts.values():
            p = count / total
            entropy -= p * math.log2(p)

    return PrefixLeakage(
        n_tokens=total,
        prefix_counts=counts,
        secret_positions_revealed=counts.get('SECRET', 0),
        classification_entropy=round(entropy, 4),
    )


# ═══════════════════════════════════════════════════════════
# Attack 3 — alignment channels
# ═══════════════════════════════════════════════════════════

@dataclass
class AlignmentChannels:
    """Text surviving abstraction that an attacker can anchor on."""

    surviving_identifiers: List[str] = field(default_factory=list)
    surviving_imports: List[str] = field(default_factory=list)
    n_original_identifiers: int = 0

    @property
    def survival_rate(self) -> float:
        if not self.n_original_identifiers:
            return 0.0
        return round(
            len(self.surviving_identifiers) / self.n_original_identifiers, 4
        )


def inventory_alignment_channels(
    original_source: str,
    abstract_code: str,
) -> AlignmentChannels:
    """
    List identifiers that appear verbatim in both the original and the output.

    Every survivor is an anchor: an attacker who sees ``requests`` in the
    abstracted code knows the file makes HTTP calls, and can use that to
    narrow which of their candidate files it is. Some survival is
    deliberate — abstracting the standard library would destroy utility —
    so this is a measurement of a chosen cost, not a list of bugs.

    Args:
        original_source: The developer's file.
        abstract_code: The emitted abstract source.

    Returns:
        An :class:`AlignmentChannels` inventory.
    """
    from algorithms.helpers import BUILTINS

    def identifiers(code: str) -> set:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return set()

        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(node.name)
            elif isinstance(node, ast.arg):
                found.add(node.arg)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.alias):
                found.add(node.asname or node.name.split('.', 1)[0])
        return found

    def imports(code: str) -> set:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return set()
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    original_ids = identifiers(original_source)
    abstract_ids = identifiers(abstract_code)

    meaningful = {
        name for name in original_ids
        if name not in BUILTINS and len(name) > 1
    }
    survivors = sorted(meaningful & abstract_ids)

    return AlignmentChannels(
        surviving_identifiers=survivors,
        surviving_imports=sorted(imports(original_source) & imports(abstract_code)),
        n_original_identifiers=len(meaningful),
    )


# ═══════════════════════════════════════════════════════════
# Suite
# ═══════════════════════════════════════════════════════════

@dataclass
class AdversarySuiteResult:
    """The adversarial evaluation across all privacy levels."""

    per_level: Dict[str, LinkageReport] = field(default_factory=dict)
    mean_survival_rate: Dict[str, float] = field(default_factory=dict)
    mean_secret_positions: Dict[str, float] = field(default_factory=dict)
    files_evaluated: int = 0


def run_adversary_suite(
    files: Optional[Sequence[Dict]] = None,
    levels: Tuple[str, ...] = ("low", "medium", "high", "critical"),
) -> AdversarySuiteResult:
    """
    Run every attack at every privacy level.

    Args:
        files: Corpus entries; defaults to the benchmark corpus.
        levels: Privacy levels to evaluate.

    Returns:
        An :class:`AdversarySuiteResult`.
    """
    from algorithms.abstract import abstract

    if files is None:
        from evaluation.benchmarks.corpus import ALL_FILES
        files = ALL_FILES

    suite = AdversarySuiteResult(files_evaluated=len(files))

    for level in levels:
        suite.per_level[level] = run_linkage_attack(files, privacy_level=level)

        survivals: List[float] = []
        secrets: List[int] = []
        for entry in files:
            abstracted = abstract(entry['code'], privacy_level=level).abstract_code
            survivals.append(
                inventory_alignment_channels(entry['code'], abstracted).survival_rate
            )
            secrets.append(
                measure_prefix_leakage(abstracted).secret_positions_revealed
            )

        suite.mean_survival_rate[level] = round(sum(survivals) / len(survivals), 4)
        suite.mean_secret_positions[level] = round(sum(secrets) / len(secrets), 4)

    return suite
