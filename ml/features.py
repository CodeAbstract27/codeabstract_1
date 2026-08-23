"""
Feature Extraction for the ML Detectors

Phase 2.

Turns an identifier or literal into a numeric feature vector for the
Random Forest baseline. Features are hand-crafted and interpretable by
design — the proposal asks for a cheap, offline, explainable baseline that
a transformer must then beat, and a baseline nobody can interpret cannot
serve as a control.

**Deliberately excluded: the SECRET/VALUE regex matches themselves.** Adding
them would hand the model the answer on a dataset whose labels were derived
from those same regexes, and its score would measure nothing but the
circularity. The features here describe the *shape* of a name — length,
casing, entropy, morphology — not whether the shipped patterns match it.
"""

import math
import re
from collections import Counter
from typing import Dict, List, Sequence

# Feature order is fixed and public: the Random Forest reports importances
# against these names, and a reordering would silently invalidate them.
FEATURE_NAMES: List[str] = [
    'length',
    'n_tokens',
    'n_digits',
    'digit_ratio',
    'n_upper',
    'upper_ratio',
    'is_screaming_case',
    'is_snake_case',
    'is_camel_case',
    'n_underscores',
    'entropy',
    'max_token_length',
    'mean_token_length',
    'has_vowel_run',
    'consonant_ratio',
    'is_numeric_literal',
    'is_constant',
    'is_function',
    'is_class',
    'is_arg',
    'is_attribute',
    'starts_with_underscore',
    'has_hyphen',
    'has_dot',
    'has_slash',
    'has_url_scheme',
    'longest_alnum_run',
]

_VOWELS = set('aeiouAEIOU')


def _entropy(text: str) -> float:
    """Shannon entropy of *text* in bits per character."""
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    )


def _split_tokens(name: str) -> List[str]:
    """Split an identifier into words across snake_case and camelCase."""
    parts = [p for p in re.split(r'[_\-\.\s]+', name) if p]
    tokens: List[str] = []
    for part in parts:
        tokens.extend(re.findall(r'[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+', part) or [part])
    return tokens or [name]


def extract_features(name: str, node_type: str = 'Name') -> List[float]:
    """
    Build the feature vector for one sample.

    Args:
        name: The identifier text, or the literal's string form.
        node_type: AST node type (``Name``, ``Constant``, ``FunctionDef`` …).

    Returns:
        A list of floats, aligned to :data:`FEATURE_NAMES`.
    """
    text = name or ""
    length = len(text)
    tokens = _split_tokens(text)

    digits = sum(1 for c in text if c.isdigit())
    uppers = sum(1 for c in text if c.isupper())
    letters = [c for c in text if c.isalpha()]
    consonants = sum(1 for c in letters if c not in _VOWELS)

    is_numeric = False
    try:
        float(text)
        is_numeric = True
    except ValueError:
        pass

    token_lengths = [len(t) for t in tokens] or [0]
    alnum_runs = re.findall(r'[A-Za-z0-9]+', text) or ['']

    return [
        float(length),
        float(len(tokens)),
        float(digits),
        digits / length if length else 0.0,
        float(uppers),
        uppers / length if length else 0.0,
        1.0 if text.isupper() and length > 1 else 0.0,
        1.0 if re.fullmatch(r'[a-z0-9_]+', text or ' ') else 0.0,
        1.0 if re.fullmatch(r'[a-z]+([A-Z][a-z0-9]*)+', text or ' ') else 0.0,
        float(text.count('_')),
        _entropy(text),
        float(max(token_lengths)),
        sum(token_lengths) / len(token_lengths),
        1.0 if re.search(r'[aeiou]{2,}', text, re.IGNORECASE) else 0.0,
        consonants / len(letters) if letters else 0.0,
        1.0 if is_numeric else 0.0,
        1.0 if node_type == 'Constant' else 0.0,
        1.0 if node_type in ('FunctionDef', 'AsyncFunctionDef') else 0.0,
        1.0 if node_type == 'ClassDef' else 0.0,
        1.0 if node_type == 'arg' else 0.0,
        1.0 if node_type == 'Attribute' else 0.0,
        1.0 if text.startswith('_') else 0.0,
        1.0 if '-' in text else 0.0,
        1.0 if '.' in text else 0.0,
        1.0 if '/' in text else 0.0,
        1.0 if re.match(r'^[a-z][a-z0-9+.\-]*://', text) else 0.0,
        float(max(len(run) for run in alnum_runs)),
    ]


def build_matrix(samples: Sequence) -> Dict[str, object]:
    """
    Vectorise a sequence of samples.

    Args:
        samples: Objects exposing ``name``/``node_name``, ``node_type``
            and ``label``.

    Returns:
        ``{'X': List[List[float]], 'y': List[str], 'feature_names': [...]}``.
    """
    features: List[List[float]] = []
    labels: List[str] = []

    for sample in samples:
        name = getattr(sample, 'name', None) or getattr(sample, 'node_name', '')
        node_type = getattr(sample, 'node_type', 'Name')
        label = getattr(sample, 'label', None) or getattr(sample, 'expected_label', '')
        features.append(extract_features(name, node_type))
        labels.append(label)

    return {'X': features, 'y': labels, 'feature_names': list(FEATURE_NAMES)}
