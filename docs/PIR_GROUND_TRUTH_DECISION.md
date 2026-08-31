# Maintainer decision note: PIR ground truth uses a context-blind classifier

**Status:** Investigated and fixed. **Scope:** `evaluation/metrics/privacy.py` only.
**Does not affect:** production abstraction, or any other evaluation pillar.

## The question

Testing (Phase 3, EVAL-1) flagged that `evaluation/metrics/privacy.py`'s Privacy
Information Ratio (PIR) computes "what counts as sensitive in the original
source" — the metric's ground truth — using `algorithms.classify.classify_node()`
called on each AST node in isolation (`inherited=None`), rather than the
context-aware path (`core.context_features.analyze_context` +
`inherited_secret_labels`, then `algorithms.classify.classify_with_evidence`)
that `algorithms.abstract` actually uses to decide what to redact.

This note answers: how big is the gap, does it currently make the published
PIR number wrong, and is a fix warranted.

## 1. Every evaluation component using context-blind classification

Searched every module under `evaluation/` for a call to `classify_node`,
`classify_with_evidence`, `classify_signals`, or `analyze_context`.

| Module | Pillar | Uses | Verdict |
|---|---|---|---|
| `evaluation/metrics/privacy.py` | 1 — Privacy (PIR) | bare `classify_node(node)`, no context | **the defect** |
| `evaluation/metrics/classification.py` | 3 — Classification F1 | bare `classify_node(node)`, no context | related but distinct — see below |
| `evaluation/metrics/detection.py` | not wired into any pillar (standalone detector-comparison utility used by `ml/random_forest.py` and `tests/test_algorithms/test_phase2_detection.py`) | **correctly** builds `analyze_context()` and calls `classify_with_evidence()` | not a defect — already does it right |
| `evaluation/metrics/mapping.py`, `reconstruction.py`, `structure.py`, `evaluation/adversary.py` | 2, 4, 6, 7 | call the real `algorithms.abstract.abstract()` directly and measure its *output* (mapping/structure/re-identification) | not affected — they never independently re-derive "what's sensitive," so they cannot inherit this bug |

**`classification.py` (Pillar 3, F1) is a different problem, already disclosed.**
Its "true" labels come from an independently hand-labeled 150-node dataset
(`evaluation/benchmarks/labeled_nodes.py`), not from `classify_node` — the
function under test is only the *predictor*, compared against that separate
dataset. But every fixture in that dataset is a single isolated
`(node_name, node_type)` pair with no surrounding code, so there is no
context for a context-aware classifier to use even in principle. This is a
**fixture-design limitation**, already surfaced by the report's own
"Dataset Integrity (Pillar 3 caveat)" section (regex-baseline accuracy 89.3%
"by construction", 0% blind-annotated). **Left unchanged** — out of scope
for this note, which is specifically about the wrong-classifier-function
defect in Pillar 1.

## 2. Production classifier vs. evaluation ground truth

Production (`algorithms/abstract.py`) decides a node's label with:

```
context_evidence  = analyze_context(tree)              # core.context_features
inherited_labels  = inherited_secret_labels(context_evidence)
decision          = classify_with_evidence(node, inherited_labels.get(id(node)),
                                            context_evidence.get(id(node)))
```

`evaluation/metrics/privacy.py`'s `_count_original_labels` instead does:

```
label = classify_node(node)          # inherited always None, no context at all
```

`classify_node`'s own docstring says `inherited` is meant to be supplied
("optional label propagated from the enclosing assignment... `'SECRET'` here
forces a SECRET classification") — the caller here simply never computes it.

## 3. Known context-dependent secret fixtures, run through both

| Fixture | Weak (`classify_node`) SECRET set | Correct (context-aware) SECRET set |
|---|---|---|
| `"sk_live_" + "abc123..."` (concatenation, no name signal) | `{}` | `{sk_live_abc123, def456...}` |
| `db_pass = "hunter" + "2222"` | `{db_pass}` | `{db_pass, hunter, 2222}` |
| `f"postgres://admin:{db_pass}@..."` | `{db_pass}` | `{db_pass, hunter2, postgres://admin:, ...}` |
| `"db://%s:%s@host" % (user, "hunter2222")` | `{db://%s:%s@host}` | `{..., hunter2222, user}` |
| `connect(password="hunter2222")` | `{}` | `{hunter2222}` |
| `api_key = "hunter2222"` (control — an ordinary, already-handled case) | `{api_key}` | `{api_key, hunter2222}` |

**6 of 6 categories under-count**, including the plain, unremarkable control
case: a short, non-vendor-shaped literal (`"hunter2222"`) bound to an
obviously secret-named variable is *never* added to the weak ground truth's
SECRET set, because `classify_node`'s own value-shape check
(`is_secret_value`) requires either a vendor format match or 24+ characters
of high entropy, and the literal alone reaches neither. Only the *name*
node (`api_key`) is caught. This is not an exotic edge case — it is the
literal-VALUE half of exactly the class of bug the original D1 defect and
the recent concatenation defect both were.

A seventh fixture (`os.environ["STRIPE_KEY"]` assigned to a bare `x`) was
tried and dropped from this table: it looked like a gap at first (the
critical-level mapping table includes `x`), but `x` is filtered out by
`is_semantically_significant` at every level below `critical` regardless of
this fix, and the only actual literal text in that source (the key string
`"STRIPE_KEY"`) was already caught by *both* the weak and the corrected
ground truth — not a real gap. Chasing that fixture down surfaced a
genuinely separate, real finding instead: `os.environ.get("KEY", "fallback")`
/ `os.getenv("KEY", "fallback")` — the two-argument form — never propagated
SECRET into the fallback-default argument, so a hardcoded credential used as
a fallback default survived at `low`/`medium`. This was a **production**
defect, not an evaluation one, and was out of scope for this note; it has
since been fixed separately (`core.context_features._is_secret_source` /
`_mark_env_fallback_default`), with regression coverage in
`TestL8EnvReadFallbackDefault` in `tests/test_algorithms/test_leak_regressions.py`.

## 4. Quantified impact on the actual 10-file corpus

First pass used a stand-in "strong" ground truth built by reading
`algorithms.abstract`'s own mapping table at `privacy_level='critical'`
(which classifies everything). That surfaced a **methodological artifact in
the comparison script itself**, not a production defect: single-punctuation
f-string fragments (`':'`, `'/'`) that legitimately get redacted as part of
a whole credential template were being checked with a bare `\b`-anchored
regex, which false-positive-matches any colon or slash anywhere in unrelated
code. Corrected by requiring a name to contain a 3+ character alphanumeric
run before treating it as a leak probe (documented in-line in the
comparison script). This is called out here because it is exactly the kind
of self-check this investigation was asked to do before drawing conclusions.

With that correction:

- **Corpus-wide SECRET leakage, at every privacy level (low/medium/high):
  0 leaked, under both the weak and the corrected ground truth.** The
  current published PIR numbers' bottom-line conclusion — "nothing in this
  corpus leaks" — **is not wrong**.
- However, **13 literal SECRET values across 4 of the 10 files
  (`web_server_config`, `auth_service`, `database_layer`,
  `microservice_router`) are classified SECRET by production *only* through
  context** (`secret_assign` name-propagation, `credential_template`
  propagation into a %-format/f-string argument, or f-string-template
  flattening) **and are invisible to the weak ground truth's SECRET set
  entirely.** Example: `'redis_auth_abc123'` in `web_server_config`,
  `'mesh_token_abc123def456'` in `microservice_router`.
- Applying the minimal proposed fix (below) to the per-occurrence walk
  changes per-file SECRET counts only upward, never downward (e.g.
  `api_client` 17→20, `auth_service` 31→38, `web_server_config` 17→20;
  files with no context-only secrets are unchanged). VALUE counts move by
  at most ±1 per file. No wild swings, no regressions in either direction —
  consistent with "the fix adds coverage, it does not change what was
  already being measured correctly."

## 5. Does PIR need rebasing?

**The qualitative conclusion in the current `evaluation_output/` report does
not need to change** — no leak exists in the corpus today under either
methodology. **The raw per-file `secret_total`/`value_total` counts in a
freshly generated report will change** (upward, by the amounts in §4) once
the fix lands, because the ground truth now counts nodes it previously
missed. Anyone citing exact secret/value counts from a report generated
before this fix should regenerate it; the PIR *ratio* itself stays ≈0 for
this corpus either way.

The real risk this fixes is not today's number — it is **that PIR currently
cannot detect a *future* regression** in exactly the context-dependent
secret-handling machinery (`secret_assign`, `credential_template`,
f-string/`%`-template flattening) that has already broken twice in this
project's history (the original D1 defect, and the concatenation defect
found earlier in this same testing pass). A regression there would leave
those 13+ corpus values unredacted, and the unfixed PIR metric would report
0% leakage anyway, because it never put them on its checklist.

## 6. Decision

**Fix applied.** Scope: `evaluation/metrics/privacy.py._count_original_labels`
only. Change: build `context_evidence`/`inherited_labels` the same way
`algorithms/abstract.py` does, and classify each node with
`classify_with_evidence` instead of bare `classify_node`. Counting
granularity (per AST occurrence, not deduplicated by symbol) is
**deliberately left unchanged** — that is a separate, secondary design
question (whether a value used 10 times should count 10x or once in the
leakage rate) that this note does not decide, to keep the fix minimal and
scoped to the confirmed defect.

**Not changed:** `evaluation/metrics/classification.py` (Pillar 3) — its
limitation is fixture design, already self-disclosed, and a different kind
of problem than this note addresses.
