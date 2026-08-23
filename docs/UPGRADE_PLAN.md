# CodeAbstract — Phase-Wise Upgrade Plan

> Companion to [AUDIT.md](AUDIT.md), which contains the reproduced evidence behind every
> defect ID (`D1`–`D6`) referenced here.

Phases are ordered by **dependency, not by appeal**. Phases 0 and 1 are prerequisites for every claim
the thesis will make; Phases 2 onward are the research contributions. Week estimates assume the
four-person team in the proposal, with Phases 3 and 4 running partly in parallel.

| Phase | Focus | Effort | Depends on |
|---|---|---|---|
| [0](#phase-0--make-the-privacy-claim-true) | Make the privacy claim true | 2–3 weeks | — (blocks everything) · **in progress** |
| [1](#phase-1--rebuild-the-mapping-as-a-real-symbol-table) | Rebuild the mapping as a real symbol table | 3–4 weeks | Phase 0 · **complete** |
| [2](#phase-2--from-regex-to-hybrid-detection) | From regex to hybrid detection | 4–5 weeks | Phase 1 · **partial — dataset blocked** |
| [3](#phase-3--evaluation-that-can-fail) | Evaluation that can fail | 4–5 weeks | Phase 1 (parallel with 4) · **mostly complete — utility axis blocked** |
| [4](#phase-4--platform-providers-transparency-languages) | Platform: providers, transparency, languages | 3–4 weeks | Phase 1 (parallel with 3) |
| [5](#phase-5--delivery) | Delivery | 3–4 weeks | Phases 3 & 4 · **partial — web interface shipped** |

---

## Phase 0 — Make the privacy claim true

**2–3 weeks · Blocks everything · Must ship first**

Close the four leak paths and the correctness bugs. **Until this lands, every number the project
publishes is describing a system that leaks secrets.** Nothing else in this plan is worth starting
first.

### Workstreams

| Workstream | Status | Detail |
|---|---|---|
| **Value-level redaction** (D1) | Done | New `core/secret_detector.py`: known credential formats (Stripe, AWS, GitHub, Slack, Google, OpenAI, JWT, PEM, connection strings, `Authorization` values), Shannon-entropy scoring for the unbranded tail, and placeholder suppression so `"your-api-key-here"` is not redacted. A label-inheritance pre-pass in `abstract.py` propagates SECRET from a binding to the literal bound to it, covering assignments, attribute assignments, keyword arguments, dict entries and comparisons. |
| **F-string handling** (D1) | Done | The blanket `JoinedStr` skip is replaced by whole-template classification: fragments are flattened to `postgres://admin:{}@host/db` and matched as one value, so a credential split across a literal and an interpolation is still caught. Redacted fragments are rewritten in place rather than swapped to `Name` nodes, which keeps the f-string valid. |
| **Import abstraction** (D3) | Done | New `config/allowlist.py` (stdlib via `sys.stdlib_module_names` + ~200 public packages). Non-allowlisted modules become `MODULE_n`; relative imports are always treated as internal. Allowlisted names are preserved **at their use sites too**, closing the alignment channel where a surviving `import` pinned a token. |
| **Collision-safe replacement** (D2) | Done | Single word-bounded `re.sub` pass with longest-token-first alternation. Two independent guards: one pass means output is never re-scanned, and `\bVAR_1\b` cannot match inside `VAR_10`. |
| **Privacy levels wired up** (D5) | Done | `PRIVACY_LEVELS` is now read by both `_should_abstract()` and `is_semantically_significant()`; the `abstract_short_names` flag finally has an effect. The four levels produce four distinct outputs. |
| **Housekeeping** (D6) | Partial | `--version` fixed (single source of truth in `config/settings.py`); UTF-8 forced via `ui.console.ensure_utf8_stdout()`, which the evaluation runner now calls; evaluation report regenerated with real Pillar 5 numbers. **Still open:** `src/codeabstract/` layout and the dependency lockfile. |
| **Regression tests** | Done | `tests/test_algorithms/test_phase0_regressions.py` — 51 tests, one class per defect, asserting on the exact inputs from the audit. |

### Exit criteria

- [x] No credential-shaped string survives abstraction at *any* privacy level — 0/21 corpus secrets leak at all four levels, down from 8/21 at `low` and `medium`.
- [x] `low`, `medium`, `high`, `critical` produce four distinct outputs on the same input.
- [x] A file with 30+ identifiers per prefix round-trips through RECONSTRUCT with zero corrupted substitutions.
- [x] `codeabstract --version` prints a version.
- [ ] `pip install .` adds exactly one top-level name. **Open** — still installs ten.

### Verification

- 133 tests pass (82 pre-existing, unchanged; 51 new).
- Corpus leak check: 0/21 secrets survive at every privacy level (was 8/21 at `low`/`medium`).
- Stress test: all 70 project source files abstract to valid Python and round-trip through
  RECONSTRUCT at all four levels — 280 runs, zero failures.
- Throughput 6,911 LOC/sec, down from 11,916 (the pre-passes cost ~40%), still 7× the
  proposal's 1,000 LOC/sec target.

> **Note for Phase 3.** PIR is unchanged at 0.0024 across this entire body of work — it did not
> move when the leaks were introduced and did not move when they were closed. The metric grades
> the classifier against itself, so it can neither detect the defect nor confirm the fix. The
> ground-truth leak check used above is the shape the real metric needs to take.

---

## Phase 1 — Rebuild the mapping as a real symbol table

**3–4 weeks · Depends on Phase 0**

The proposal promises **85%+ mapping accuracy** and "actionable feedback". A flat `name -> token` dict
cannot deliver either. This phase replaces it with scope-aware, occurrence-level mapping — the piece
that makes bidirectional mapping a genuine contribution rather than find-and-replace.

### Workstreams

| Workstream | Status | Detail |
|---|---|---|
| **Scoped symbol table** (D4) | Done | New `core/symbol_table.py`: a full lexical scope tree (module → class → function → comprehension) honouring `global`/`nonlocal` and the rule that class scopes sit outside a nested function's lookup chain. Tokens key on `(scope, name)`, so `alpha.result` and `beta.result` are distinct symbols with distinct lines. Literals and attributes get their own namespaces, which also fixed a separate conflation where the string `"endpoint"` and a variable `endpoint` collapsed into one token. |
| **Occurrence records** | Done | Every `(lineno, col)` is recorded, and the reported definition line is the *binding* site rather than whichever occurrence the breadth-first walk reached first. |
| **Line-number translation** | Done | ABSTRACT emits an abstract→original line index by pairing the mutated tree (which retains original line numbers) against a re-parse of the emitted code; the walk stops where shapes disagree, so a partial index is possible but a wrong one is not. RECONSTRUCT rewrites "line 6", "lines 5-6" and "Line #6" before token substitution. Persisted in a new `line_map_json` column with a guarded `ALTER TABLE` migration, so pre-Phase-1 sessions keep working. |
| **Comment and docstring policy** | Done | Policy made explicit rather than migrating to a CST: comments are **stripped by default**, and `--keep-comments` opts into re-injection where every comment is screened — dropped if its text trips the secret or business-value classifier, and identifiers mentioned in surviving prose are rewritten to tokens. Re-injection is validated by re-parsing; if it would not parse, the un-injected code is used. |
| **Allowlist & override** | Done | New `config/ignore_rules.py` reads `.codeabstractignore` upward from the source file. Three directives — `keep:`, `secret:`, `module:` — all glob-capable. **A `keep` rule cannot rescue a real secret:** if the node still classifies SECRET on its own evidence the rule is ignored, so a config file can never put a credential on the wire. |
| **Apply-fixes-back** | Done | New `algorithms/apply_fix.py` and a `codeabstract apply` command: pulls fenced Python blocks from the response, de-tokenises them with the same collision-safe substitution, and shows a unified diff before writing. Only whole-file rewrites are offered as applicable patches; fragments are restored and handed back for manual placement, because guessing where a fragment belongs writes broken code into someone's repository. |

### Exit criteria

- [x] Shadowed and duplicate names across scopes resolve to the correct definition site — shadow resolution **1.000** across the corpus.
- [x] A new **mapping accuracy** metric exists and reads ≥ 85% — Pillar 6 reports **0.9975**.
- [x] Line citations in an LLM response land on the right line of the *original* file.
- [x] Abstracted output round-trips back to a syntactically valid file, comment-preserving under `--keep-comments`.

### Verification

- 169 tests pass (82 pre-existing, 51 Phase 0, 36 Phase 1).
- Mapping accuracy **0.9975** — definition-site 0.9946, occurrence 0.9955, shadow resolution 1.000, line-map 1.000.
- Phase 0 guarantees still hold: 0/21 corpus secrets leak at every privacy level.
- Stress test: 77 project source files × 4 levels, all valid Python, all round-tripping.
- Full loop exercised end to end: abstract → simulated LLM response → de-tokenise → diff → apply, with the fix landing in the developer's file under its original names.
- Throughput 5,283 LOC/sec (from 6,911 — scope analysis and the line index cost ~24%), still 5× the proposal's target.

> **A note on the new pillar.** Its first draft scored shadow resolution at 0.59, which turned out to be the
> metric penalising the engine for correctly *never* abstracting `self`. Grading now covers only names the
> engine actually maps. Worth recording because it is the same failure mode as the circular pillars in
> Phase 3's brief: a metric that measures the wrong population is as misleading as one that grades itself.

---

## Phase 2 — From regex to hybrid detection

**4–5 weeks · Depends on Phase 1 · Research contribution**

The proposal specifies a fine-tuned CodeBERT secret detector and an optional Random Forest sensitivity
classifier. What exists is 31 regexes matched against a lowercased name. This phase builds the ML
layer — **and, first, an honest dataset to train and judge it on**.

### Workstreams

| Workstream | Status | Detail |
|---|---|---|
| **De-circularise the dataset** | **Blocked** | Requires two human annotators working blind to the pattern list. Writing a dataset and then scoring my own detector on it reproduces the exact defect the audit found, with a fabricated κ on top — so the dataset was not written. What shipped instead is the *tooling* the annotation effort needs: `evaluation/benchmarks/annotation.py` provides the schema (recording annotator, provenance, and whether they were blind), a Cohen's κ implementation, and a circularity audit that measures how far a dataset's labels are already determined by the detector under test. |
| **Context features** | Done | New `core/context_features.py`: eleven weighted usage signals — env reads (`os.environ[...]`, `getenv`), auth headers, `password=` keyword arguments, credential sinks (`compare_digest`, `authenticate`), credential sources (`vault.get_secret`), callee signatures, secret-named returns. Signals combine as independent evidence and are **pooled per symbol**, not per node. This subsumes the narrower Phase 0 propagation pass. |
| **Random Forest baseline** | Done (gated) | `ml/features.py` + `ml/random_forest.py`: 27 interpretable shape features, stratified 5-fold CV, feature importances. Features **deliberately exclude the SECRET/VALUE regex matches** — handing the model its own labelling rule would make its score meaningless. `train_and_report` runs the circularity audit on its own training data and refuses to mark a result trustworthy when the labels were not assigned blind. |
| **CodeBERT fine-tune** | **Blocked** | Downstream of the dataset. `transformers` and `torch` are installed, but fine-tuning on circular labels produces a model that has learned the regexes, and reporting its F1 as detection accuracy would be worse than not building it. |
| **Confidence & hybrid routing** | Done | `classify_with_evidence()` returns a `Decision` carrying a label, a confidence, the detector that fired, and its reasons. Five tiers, highest precision first: vendor credential format (0.99) → binding context (0.90) → name pattern (0.75) → entropy (0.65) → literal type (0.55). Decisions below 0.60 are counted in `low_confidence_nodes` and recorded on the mapping entry. The bare-label `classify_node()` API is unchanged for existing callers. |

### Exit criteria

- [ ] A held-out, independently annotated test set exists with inter-annotator agreement published. **Blocked on human annotation.**
- [ ] Hybrid detection beats the regex baseline on recall at equal or better precision, reported as a confidence interval. **The harness exists and runs; the dataset to run it on does not.**
- [x] Zero credential-shaped values missed — 0/21 corpus secrets leak at every privacy level, unchanged from Phase 0.

### What the measurements actually showed

Running the new tooling on the existing dataset turned the audit's qualitative claim into numbers:

| Check | Value | Reading |
|---|---|---|
| Regex baseline accuracy | 0.8933 | ≈ the reported macro-F1 of 0.8937 — the F1 *is* the baseline |
| Discriminative power | 0.1067 | only 16 of 150 items can separate two detectors |
| Rationale leakage | 0.6133 | 61% of labels are justified by quoting the pattern list |
| Annotated blind | 0.0000 | no item was labelled without sight of the patterns |
| Provenance recorded | 0.0000 | no item traces to real-world code |

Two further findings came out of running the harness:

1. **Hybrid scores identically to the regex baseline on this dataset — Δ exactly 0.0000 on every metric,
   with the bootstrap interval collapsed to zero.** The dataset is node-level: bare `(name, type)` pairs
   with no surrounding code. The context tier therefore has nothing to read, and the hybrid degrades to
   its name-pattern tier. The dataset is not merely circular, it is **the wrong shape** to evaluate what
   this phase built.

2. **The Random Forest scores 0.70, below the 0.893 regex baseline.** That is the expected consequence of
   excluding the patterns from the feature set: the labels are "does this name contain one of these
   substrings", which is not recoverable from morphology. The dataset teaches nothing that generalises.

Capability is demonstrated by behavioural tests instead. Seven fixtures use identifiers with no
secret-ish name — `blob`, `handle`, `material`, `supplied`, `payload` — where a name-regex scores 0/7 by
construction. The context detector redacts all seven at the loosest privacy level, and leaves three
benign controls alone. These are capability tests, **not** an evaluation dataset, and no accuracy figure
is claimed from them.

### Verification

- 216 tests pass (82 pre-existing, 51 Phase 0, 36 Phase 1, 47 Phase 2).
- Context-only detection: 7/7 on fixtures a name-regex cannot catch; 0/3 false positives on controls.
- Phase 0 and 1 guarantees intact: 0/21 corpus secrets leak; mapping accuracy 0.9975.
- Stress test: 84 project source files × 4 levels, all valid Python, all round-tripping.
- The evaluation report now carries a **Dataset Integrity** section directly under the classification
  pillar, so the macro-F1 cannot be read without the caveat that qualifies it.

> **To unblock this phase**, what is needed is roughly 300–500 samples of real code, each labelled
> independently by two people who have not seen `config/patterns.py`, with provenance recorded. The
> schema, the κ calculation, the circularity audit, the comparison harness and the RF trainer are all
> in place and will run against it unchanged. Until then, this phase ships capability without a
> benchmark — which is the honest half of the work, and the half that does not require inventing data.

---

## Phase 3 — Evaluation that can fail

**4–5 weeks · Parallel with Phase 4 · Research contribution**

The proposal's sharpest research ideas — the adversarial re-identification attack and a Code Privacy
Entropy metric — are entirely unbuilt, and there is still no utility measurement of any kind.
**An evaluation that cannot fail is not evidence.**

### Workstreams

| Workstream | Status | Detail |
|---|---|---|
| **Corpus to 100+ files** | Done | New `evaluation/benchmarks/corpus_real.py` builds a corpus from real Python already on the machine — 120 stdlib files, 24,737 LOC, mean 206 LOC, 18 domains. That code was written by people with no knowledge of this project, which the synthetic corpus can never be. It does **not** replace the synthetic corpus: stdlib contains no credentials, so leak ground truth still comes from the ten files where the secrets are known by construction. Two corpora, two jobs. |
| **Adversarial re-identification** | Done | New `evaluation/adversary.py`. Rather than an attacker LLM (which needs an API key and sends code to a third party), the attack is a **linkage attack**, run offline and deterministically: the adversary holds the original files and one abstracted file, and must say which it came from. This is the standard re-identification setup, and it tests the claim that abstraction hides *which* proprietary code you are asking about. |
| **Code Privacy Entropy (CPE)** | Done | Formalised as the normalised Shannon entropy of the attacker's posterior over candidates: `H(posterior) / log2(N)`. 1.0 = the attacker learned nothing, 0.0 = certain. Normalising by `log2(N)` makes it comparable across corpora of different sizes. Alignment channels are inventoried separately (`inventory_alignment_channels`), as is the information the token scheme leaks on its own (`measure_prefix_leakage`). |
| **Utility measurement** | Partial | `evaluation/utility.py` implements the paired raw-vs-abstracted collection, a content-addressed response cache so runs are reproducible without an API key, automatic proxies (issue overlap, line-citation agreement with `line_map` alignment), and a **blind rating sheet** exporter that keeps the raw/abstracted key in a separate file. The headline 80% number needs human raters and an LLM; `collect_pairs` raises rather than returning zeros when given no client. |
| **Developer study** | **Blocked** | Ten human participants. Same category as Phase 2's annotators — not something to simulate. The blind-rating export is the part of the apparatus that could be built without them. |
| **Reproducibility** | Done | Every stochastic component is seeded (`20260818`): the bootstrap in `detection.py`, the rating-sheet shuffle, the RF splitter. Corpus discovery is deterministic (sorted, size-filtered). LLM responses cache to disk content-addressed. |

### Exit criteria

- [x] The suite reproduces every Phase 0 defect when run against the pre-fix commit — **5/5 detected at `47d91bc`, 0/5 against the current engine.**
- [ ] A privacy–utility curve across all four levels with confidence intervals. **Blocked** — the privacy axis is measured at all four levels; the utility axis needs an LLM and blind raters.
- [x] Attacker re-identification rate reported per level, including the alignment-channel breakdown.

### The finding

The linkage attack, run on the 120-file real corpus with a random-guess baseline of 0.0083:

| Privacy level | Top-1 | MRR | CPE | Advantage over chance | Identifiers surviving |
|---|---|---|---|---|---|
| `low` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.864 |
| `medium` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.582 |
| `high` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.045 |
| `critical` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.045 |

**Every file is re-identified perfectly, at every privacy level.** Two things follow, and both matter
more than any number shipped so far.

1. **Pillar 4's success is Pillar 7's failure.** AST isomorphism of 1.0000 has been reported since the
   first evaluation as evidence that abstraction preserves structure — which it is, and which is what
   makes the output useful to an LLM. It is *also* a perfect fingerprint. The same property that
   delivers utility delivers linkability, and the project has been reporting one half of that trade
   without the other.

2. **Privacy levels do nothing here.** Identifier survival falls from 86% at `low` to 4.5% at `high` —
   the identifier-hiding machinery works well. Re-identification stays at 1.000 throughout, because
   privacy levels govern *names* and the attack reads *shape*. The proposal promises to characterise a
   privacy–utility trade-off across these levels; along this axis there is no trade-off to plot,
   because the privacy term is constant.

This does not mean the system is worthless — it never claimed to hide that a file exists, and the
threat model that matters for most users is "do not send my credentials and identifiers to a third
party", which the earlier phases now enforce. It does mean the **threat model has to be written down
explicitly** (Phase 5) and must state that abstraction protects identifiers and secrets, not the fact
of which code you are asking about. Defences worth evaluating — structural noise injection, statement
reordering, dead-branch insertion — are the differential-privacy-for-syntax idea the proposal already
sketches, and this attack is the instrument that would measure whether they work.

A third, smaller finding: the token scheme labels its own conclusions. `SECRET_n` announces where a
credential sat, at ~11 positions per corpus file, information the original identifier may not have
carried. That is a deliberate trade (distinct prefixes help the model reason and keep reconstruction
unambiguous), now measured rather than assumed.

### Verification

- 248 tests pass (82 pre-existing, 51 Phase 0, 36 Phase 1, 47 Phase 2, 32 Phase 3).
- Regression harness: **5/5 defects detected at `47d91bc`, 0/5 on the current engine** — the probes
  discriminate rather than always firing.
- Real corpus: 120 files, 24,737 LOC, all parse on the local interpreter.
- Phase 0–2 guarantees intact: 0/21 corpus secrets leak at every level; mapping accuracy 0.9975.
- The evaluation report now carries Pillar 7 alongside the Dataset Integrity section, so the
  structure-preservation result and its adversarial cost are read together.

---

## Phase 4 — Platform: providers, transparency, languages

**3–4 weeks · Parallel with Phase 3**

`pyproject.toml` advertises `openai` and `anthropic` extras that no code imports — only Gemini is
implemented, behind a factory that ignores its own provider argument. This phase makes the tool match
its own packaging and gives the user visibility into what left the machine.

### Workstreams

| Workstream | Detail |
|---|---|
| **Provider abstraction** | A real `LLMClient` protocol with OpenAI, Anthropic and Gemini behind it; provider and model selectable per invocation; retries, timeouts and token accounting shared across all three. |
| **Free-form queries** | Today the user picks one of five fixed presets. The proposal's input spec has "User Query" as a first-class field — accept arbitrary questions, and abstract the query text too, since it will name the very things being hidden. |
| **Privacy report** | Output format #5 in the proposal, currently absent. After every run, show what was hidden, what was deliberately kept, and what the detector was unsure about. Compliance teams need it; so does the user's trust. |
| **Audit log** | Append-only local record of each outbound request — file, provider, privacy level, token counts, detector version. Named in the proposal's use-case table as the compliance deliverable. |
| **Second language** | JavaScript/TypeScript via tree-sitter — a stretch goal in the proposal, and the cleanest proof that the approach is not a Python `ast` trick. Refactor the engine around a language-agnostic node interface before starting. |
| **Key handling** | Fernet keys currently sit in the same SQLite row as the ciphertext they unlock, which is encoding, not protection. Move keys to the OS keychain via `keyring`, or derive them from a passphrase. |

### Exit criteria

- [ ] The same file reviewed through all three providers, with results compared in the evaluation.
- [ ] Every run emits a privacy report and an audit entry.
- [ ] A JS/TS file abstracts and reconstructs end to end.
- [ ] The database alone is useless without the keychain entry.

---

## Phase 5 — Delivery

**3–4 weeks · Depends on Phases 3 & 4**

The proposal commits to a web interface, a 10–12 page paper, a 40–60 page thesis, a demo video and a
documented open-source release. None of it should start before Phase 3 produces numbers worth writing
about.

### Workstreams

| Workstream | Status | Detail |
|---|---|---|
| **Web interface** | Done | New `web/` package: `codeabstract web` serves the proposal's Option B — side-by-side original and abstracted code with per-token highlighting, the privacy report inline, and the model's suggestions mapped back onto the developer's own names. All five of the proposal's output formats are present as panes: abstracted code, local vault, raw LLM analysis, mapped feedback, privacy report. **Flask, not Streamlit**, and for a reason that outlived the choice — see below. |
| **Batch & pre-commit** | Not started | Directory scanning and a pre-commit hook — the "Compliance" and "Open Source maintainer" rows of the proposal's use-case table, neither of which the CLI serves today. |
| **Paper & thesis** | Not started | Write against the Phase 3 tables. The honest-limitations section already drafted in the proposal is a strength — keep it, and add what this audit found about metrics that cannot fail. |
| **Release** | Not started | PyPI package, tagged release, README rewritten against measured behaviour, documented threat model stating plainly what is and is not protected, demo video. |
| **VS Code extension** | Not started | Stretch goal. Only if Phases 0–4 are genuinely closed — a half-finished plugin costs more credibility than a missing one. |

### Exit criteria

- [x] A browser can drive the whole pipeline — abstract, send, reconstruct — with the privacy report inline and suggestions mapped back.
- [ ] README claims are traceable to a number in the evaluation report — no unsupported "0 secrets leaked".
- [ ] A stranger can clone, install and reproduce the headline results from the docs alone.
- [ ] The threat model states the limits explicitly, in the proposal's own honest register.

### Why Flask and not Streamlit

The proposal names either. The deciding argument is that **a Streamlit script has no seam a test can
grip**. Its model is a script re-run per interaction with widget state as the only input; there is
nowhere to assert on what a request produced. Flask has a request boundary, so `app.test_client()`
drives the entire pipeline in-process — which turns the claim this project exists to make into an
assertion rather than a screenshot:

> No credential value appears in the provider payload, the abstract code, the vault, the privacy
> report, the reconstructed feedback, the stored session, or the audit log.

That is `tests/test_web/test_web_privacy.py`, and it is checked at all four privacy levels.

### What the web boundary changed

Three things had to be *stricter* in a browser than in the terminal, and each is a decision rather
than an implementation detail.

1. **Secret values are masked on the way out, and reconstruction runs against the masked mapping.**
   RECONSTRUCT's job is to put the original names back, and for a `SECRET` token that means the
   credential. In a terminal that is the user's own screen. In a browser it is history, extensions,
   devtools and whatever is being screen-shared in a demo. Masking the name alone was not enough:
   each mapping entry carries ±k lines of the *original* source as context, and the line that bound
   a credential contains it — so every secret value is scrubbed from every snippet too. Unmasking
   needs two gates, the server's `--allow-reveal` and the request's, because a gate the client alone
   controls protects nothing.

2. **No path ever comes from the client.** The CLI takes a filename and reads it; a server doing the
   same reads any file its process can see. The web interface takes *content* plus a name used only
   to pick a language adapter, and reduces that name to a basename before anything looks at it.

3. **Writes require `Content-Type: application/json`.** A page on any origin can make a browser issue
   a simple cross-origin form POST. Requiring JSON takes every mutating endpoint out of the
   simple-request class, so the browser must preflight and the preflight fails. `codeabstract web`
   also refuses to bind anywhere but loopback without `--expose`, because nothing in the app
   authenticates a caller and the vault is what is on the other side of the port.

One boundary is stated precisely rather than loosely, because the loose version would be false: the
original-code pane echoes the submitted source back verbatim, credentials included. That is not a
leak — it is the user's own paste returned to the tab it came from, and the side-by-side view cannot
exist without it. The claim is about everything *derived* from the source, and that is what the tests
assert.

### Verification

- **526 tests pass** (325 pre-existing, unchanged; 201 new for the web interface).
- Secrets withheld from the provider payload at all four privacy levels, asserted on the prompt the
  client actually received rather than on the response.
- Escaping is tested directly: a `<script>` tag in the source, and a quote in an identifier name that
  would otherwise break out of a `title` attribute.
- The D2 collision guard is re-asserted at the web boundary — `VAR_1` must not substitute inside
  `VAR_10` in either the highlighter or the translate endpoint.
- Path traversal in the `filename` field abstracts the submitted buffer or is rejected; it never
  reads.
- The audit log's hash chain still verifies after web runs, and web entries are marked `<web>/…` so a
  reviewer is not sent looking for a file that does not exist.

---

## Three things worth arguing about

1. **Do not present current results anywhere until Phase 0 lands.** PIR 0.0024 and "0 secrets leaked"
   are, on today's code, contradicted by a four-line input. That is survivable now and fatal in a
   thesis defence.

2. **Phase 2's ML work is worth less than Phase 3's adversarial evaluation.** If schedule pressure
   forces a cut, ship the Random Forest baseline and skip the CodeBERT fine-tune — a hybrid detector
   with an honest attacker evaluation is a stronger contribution than a transformer scored on a
   circular dataset. The novelty claim rests on bidirectional mapping and adversarial validation, not
   on model size.

3. **The comment-stripping decision needs an explicit owner.** `ast.unparse` currently discards
   comments as a side effect, not a policy. It is simultaneously the strongest privacy behaviour in
   the system and a large utility cost, and it blocks applying fixes back to source. Decide it
   deliberately in Phase 1 and write it into the threat model either way.
