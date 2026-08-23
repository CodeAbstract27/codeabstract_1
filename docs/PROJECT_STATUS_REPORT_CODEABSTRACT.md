# CodeAbstract — Project Status Report

**Repository:** CodeAbstract (single Python package) · **Branch:** `main` · **Version:** `1.0.0` — untagged

**Snapshot date:** 2026-08-20 · **Latest commit:** `47d91bc` · 2026-08-08 · **Contributors:** 3 people / 24 commits (see §8)

**Status legend:** *done* — verified by a runnable command · *in progress* — real but incomplete · *pending* — not started · *blocked* — cannot proceed without a human input the repository cannot supply · *limitation* — by design, unresolved

Sourced from `README.md`, `docs/AUDIT.md`, `docs/UPGRADE_PLAN.md`, `docs/README.md`, `evaluation_output/evaluation_report.md`, `pyproject.toml`, and git history (`log`, `shortlog`, `ls-files`, `diff --stat`), plus a live `pytest` run and direct probes of the installed CLI on 2026-08-20. Figures are dated to their source; where a live run disagrees with a checked-in document, both numbers are given rather than one quietly discarded.

> **Read this first.** The single most consequential fact about this project's status is not in any of its documents: **none of the Phase 0–5 work is committed.** `HEAD` is `47d91bc` (2026-08-08) — the pre-audit engine, the one that transmits a live API key verbatim at every privacy level. Everything described below as *done* exists only in the working tree of one machine: 27 modified tracked files (+3,368 / −343 lines) and 40 untracked paths. See §6, issue 1.

---

## 1. Project / Work Overview

### What CodeAbstract is

A command-line tool that lets a developer ask an LLM about proprietary source code without sending the proprietary parts. Source is parsed to a syntax tree, sensitive nodes are classified and replaced with stable tokens (`FUNC_0`, `SECRET_1`, `MODULE_2`), the abstracted code goes to the provider, and the model's answer is translated back onto the developer's own identifiers and line numbers using a locally-held, encrypted mapping table.

The project is built around four formal algorithms, all implemented:

| Algorithm | Role |
|---|---|
| `ABSTRACT(S, k)` | Parse to AST, build a scoped symbol table, classify each node, emit tokens plus a ±k-line context window and an abstract→original line index |
| `CLASSIFY(E)` | Label a node `SECRET`, `VALUE` or `IDENTIFIER` — five confidence-ranked detector tiers, not one regex pass |
| `RECONSTRUCT(R, M̃, K)` | Decrypt the mapping, rewrite line citations, substitute tokens back collision-safely, attach source context |
| `ENCRYPT(M) / DECRYPT(M̃, K)` | Fernet (AES-128-CBC + HMAC-SHA256) at rest, with the key held outside the database |

### Component map

| Layer | Module | Role |
|---|---|---|
| Algorithms | `algorithms/` | `abstract`, `abstract_source`, `classify`, `reconstruct`, `encrypt`, `apply_fix` |
| Detection core | `core/` | `symbol_table` (lexical scope tree), `secret_detector` (credential formats + entropy), `context_features` (11 usage signals), `comment_handler`, `privacy_report`, `query_abstractor` |
| Languages | `core/languages/` | `python_adapter` (stdlib `ast`), `javascript` (tree-sitter, byte-range rewrite) |
| Config & policy | `config/` | `patterns`, `settings` (the four privacy levels), `allowlist`, `ignore_rules` (`.codeabstractignore`) |
| Providers | `llm/` | `base` protocol + `gemini_client`, `openai_client`, `anthropic_client` |
| Storage | `storage/` | `database` (SQLite), `session_manager`, `mapping_store`, `key_store` (OS keychain), `audit_log` (hash-chained JSONL) |
| Interfaces | `cli.py`, `commands/`, `ui/`, `web/` | 11 top-level commands + 4 sub-command groups; Flask workbench |
| ML | `ml/` | `features` (27 shape features), `random_forest` (gated baseline) |
| Evaluation | `evaluation/` | 7 pillars, 2 corpora, adversarial linkage attack, regression harness, annotation tooling |

**Scale (measured 2026-08-20):** 10,230 lines of Python outside `tests/`, 5,834 lines of tests, 662 tests passing in 79 seconds.

### The genre it is in

This is an academic research artifact tied to a written proposal (`Project Implementation.pdf`) with numeric targets — 85%+ mapping accuracy, ≤5% privacy leakage, 80% utility preservation, 1,000 LOC/sec, a 100+ sample study and a 10-developer user study. The project's own documents are unusually direct about which of those it has met, which it has not, and which it has deliberately declined to fake. That register is carried through this report rather than smoothed over.

---

## 2. Work Completed

Each item below is backed by a named test file, a live command run, or a figure in the regenerated evaluation report — not by a status claim alone. **All of it is uncommitted** (§6).

**The privacy guarantee made true — done.**
The audit of 18 August reproduced a live Stripe key crossing the network at *every* privacy level including the strictest. Value-level redaction now judges the literal rather than only its binding: known credential formats (Stripe, AWS, GitHub, Slack, Google, OpenAI, JWT, PEM, connection strings, `Authorization` values), Shannon-entropy scoring for the unbranded tail, and placeholder suppression so `"your-api-key-here"` is not redacted. F-strings are flattened and classified as whole templates, so a credential split across a literal and an interpolation is still caught.
*Source: `core/secret_detector.py`, `algorithms/abstract.py` · 0 / 21 corpus secrets survive at all four levels, down from 8 / 21 at `low` and `medium`*

**Import and brand-reference abstraction — done.**
`config/allowlist.py` treats stdlib (via `sys.stdlib_module_names`) and ~200 public packages as public vocabulary; everything else becomes `MODULE_n`, and relative imports are always internal. Allowlisted names are preserved *at their use sites too*, which closes the alignment channel where a surviving `import` pinned a token.
*Source: `config/allowlist.py` · D3, L3*

**Collision-safe reconstruction — done.**
Replacement is a single word-bounded `re.sub` with longest-token-first alternation. Two independent guards: one pass means output is never re-scanned, and `\bVAR_1\b` cannot match inside `VAR_10`. Before this, any file with more than ten identifiers of one prefix corrupted the response and pointed the developer at the wrong line — the precise failure bidirectional mapping exists to prevent.
*Source: `algorithms/reconstruct.py` · D2*

**A real scoped symbol table — done.**
`core/symbol_table.py` builds a full lexical scope tree (module → class → function → comprehension) honouring `global`/`nonlocal` and the rule that class scopes sit outside a nested function's lookup chain. Tokens key on `(scope, name)`, so `alpha.result` and `beta.result` are distinct symbols with distinct definition lines. Literals and attributes get their own namespaces.
*Source: `core/symbol_table.py` · mapping accuracy 0.9975 against a 0.85 target · D4*

**Line-number translation, both directions — done.**
`ABSTRACT` emits an abstract→original line index by pairing the mutated tree against a re-parse of the emitted code; the walk stops where shapes disagree, so a partial index is possible but a wrong one is not. `RECONSTRUCT` rewrites "line 6", "lines 5-6" and "Line #6" before token substitution. Persisted in a `line_map_json` column behind a guarded `ALTER TABLE`, so pre-Phase-1 sessions keep working.
*Source: `algorithms/abstract.py`, `algorithms/reconstruct.py` · line-map accuracy 1.000*

**Four privacy levels that actually differ — done.**
`PRIVACY_LEVELS` was dead code read by nothing; `critical` and `high` produced byte-identical output. The table is now read by both `_should_abstract()` and `is_semantically_significant()`, and the four levels produce four distinct outputs.
*Source: `config/settings.py` · D5*

**Comment policy made explicit — done.**
Comments are stripped by default in *every* language — a comment is prose written by the owners of the code and is where business context lives most densely. `--keep-comments` re-injects them, and each one is screened: comments tripping the secret or business-value classifier are dropped, and identifiers named in survivors are rewritten to tokens. Re-injection is validated by re-parsing; if it would not parse, the un-injected code is used.
*Source: `core/comment_handler.py` · L2*

**Context-based detection — done.**
`core/context_features.py` scores eleven weighted usage signals — environment reads, auth headers, `password=` keyword arguments, credential sinks (`compare_digest`, `authenticate`), credential sources, callee signatures, secret-named returns — pooled *per symbol* rather than per node. Seven behavioural fixtures use identifiers a name-regex scores 0/7 on by construction (`blob`, `handle`, `material`, `supplied`, `payload`); the context detector redacts all seven and leaves three benign controls alone.
*Source: `core/context_features.py` · `tests/test_algorithms/test_phase2_detection.py`*

**Confidence-tiered hybrid routing — done.**
`classify_with_evidence()` returns a `Decision` carrying label, confidence, the detector that fired, and its reasons. Five tiers, highest precision first: vendor credential format (0.99) → binding context (0.90) → name pattern (0.75) → entropy (0.65) → literal type (0.55). Decisions below 0.60 are counted as `low_confidence_nodes` and recorded on the mapping entry, so uncertainty reaches the user rather than being rounded away.
*Source: `algorithms/classify.py`*

**Adversarial re-identification and Code Privacy Entropy — done.**
`evaluation/adversary.py` runs a linkage attack offline and deterministically: the adversary holds the originals and one abstracted file and must say which it came from. CPE is formalised as normalised Shannon entropy of the attacker's posterior, `H(posterior) / log2(N)`. Alignment channels and token-prefix leakage are inventoried separately. **This produced the sharpest result in the project — see §6, issue 4.**
*Source: `evaluation/adversary.py` · Pillar 7*

**A 120-file real corpus and a regression harness that discriminates — done.**
`corpus_real.py` builds a corpus from real Python already on the machine: 120 stdlib files, 24,737 LOC, mean 206 LOC, 18 domains, written by people with no knowledge of this project. It does not replace the synthetic corpus — stdlib holds no credentials, so leak ground truth still comes from the ten files where secrets are known by construction. The regression harness reports **5/5 defects detected at `47d91bc` and 0/5 against the current engine**, so the probes discriminate rather than always firing.
*Source: `evaluation/benchmarks/corpus_real.py`, `evaluation/regression_harness.py`*

**Dataset-integrity measurement — done, and it indicted the headline F1.**
`evaluation/benchmarks/annotation.py` provides the annotation schema, a Cohen's κ implementation, and a circularity audit measuring how far a dataset's labels are already determined by the detector under test. Run on the existing 150-node dataset it found: regex-baseline accuracy 0.8933 against a reported macro-F1 of 0.8937 (**the F1 *is* the baseline**), discriminative power 0.1067 (only 16 of 150 items can separate two detectors), rationale leakage 0.6133, blind-annotated 0.0000, provenance recorded 0.0000. The evaluation report now carries this as a *Dataset Integrity* section directly under the classification pillar, so the F1 cannot be read without the caveat that qualifies it.
*Source: `evaluation/benchmarks/annotation.py` · `evaluation_output/evaluation_report.md`*

**Three LLM providers behind one protocol — done.**
`pyproject.toml` had advertised `openai` and `anthropic` extras that no code imported, behind a factory that ignored its own provider argument. There is now a real `LLMClient` protocol with all three implementations, provider and model selectable per invocation. `codeabstract providers list` reports all three packages installed on this machine.
*Source: `llm/base.py`, `llm/{gemini,openai,anthropic}_client.py` · verified live*

**Privacy report, audit log and key handling — done.**
The privacy report (proposal output format #5) shows what was hidden, what was deliberately kept, and what the detector was unsure about, in terminal and JSON form with secrets masked by default. The audit log is append-only hash-chained JSONL recording metadata only — never content — with `verify_chain` naming where a chain breaks and exiting non-zero, so it works as a CI gate. Fernet keys moved out of the database row that held their own ciphertext into the OS keychain, with a documented weaker key-directory fallback and a `sessions migrate-keys` path for legacy rows.
*Source: `core/privacy_report.py`, `storage/audit_log.py`, `storage/key_store.py`*

**A second language — done.**
`core/languages/javascript.py` abstracts JS/TS via tree-sitter as a set of byte-range replacements over the original text rather than parse-and-reprint. Formatting, comments and blank lines survive; the line map is the identity, so an LLM's "line 34" needs no translation and cannot be translated wrongly. It refuses a file that misparses, because a misparsed region is exactly where a secret would be missed. It deliberately does not model hoisting, closures or `let`/`var` block scoping — two symbols may share a token, which costs mapping precision and never privacy, and the limitation is stated in the module rather than buried.
*Source: `core/languages/javascript.py`*

**Free-form queries, abstracted — done.**
The tool previously offered five fixed task presets. Arbitrary questions are now accepted, and the question text is abstracted with the same mapping as the code — a question naming `calculate_stripe_commission` and `STRIPE_API_KEY` reaches the provider as `Why does FUNC_0 mishandle SECRET_2 and SECRET_0?`
*Source: `core/query_abstractor.py`*

**Apply-fixes-back — done.**
`codeabstract apply` pulls fenced code blocks from a response, de-tokenises them with the same collision-safe substitution, and shows a unified diff before writing. Only whole-file rewrites are offered as applicable patches; fragments are restored and handed back for manual placement, because guessing where a fragment belongs writes broken code into someone's repository.
*Source: `algorithms/apply_fix.py`, `commands/apply_cmd.py`*

**User override that cannot be abused — done.**
`.codeabstractignore` is read upward from the source file and supports three glob-capable directives (`keep:`, `secret:`, `module:`). **A `keep` rule cannot rescue a real secret:** if the node still classifies `SECRET` on its own evidence the rule is ignored, so a config file can never put a credential on the wire.
*Source: `config/ignore_rules.py`*

**The web workbench — done.**
`codeabstract web` serves all five of the proposal's output formats as panes — abstracted code, local vault, raw LLM analysis, mapped feedback, privacy report — with per-token highlighting that scrolls the original pane to the source line. Flask rather than Streamlit for a stated reason: a Streamlit script has no seam a test can grip, whereas `app.test_client()` drives the whole pipeline in-process. Three boundaries are stricter in a browser than in a terminal: secret values are masked everywhere on the page including inside reconstructed source-context blocks and unmasking needs two gates; no path ever comes from the client (content plus a name used only to select a language adapter); mutating requests require `Content-Type: application/json`, which takes them out of the browser's simple-request class. It refuses to bind off-loopback without `--expose`.
*Source: `web/` · 201 tests · `tests/test_web/test_web_privacy.py`*

**Six further leak paths closed after the first fix pass — done.**
A second end-to-end audit on 19 August probed constructs the corpus does not contain and found six live leaks underneath a green suite and five successful pillars: `bytes` credentials undetected (`L1`), JavaScript comments never screened (`L2`, leaking at all four levels), vendor imports leaking in JS (`L3`), values flowing into a credential template untainted (`L4`), `config show` printing stored API keys (`L5`), endpoint literals never classified `VALUE` (`L6`). All six are fixed and covered by 122 regression tests.
*Source: `tests/test_algorithms/test_leak_regressions.py`*

**A documentation set written from a bare README — done.**
`docs/AUDIT.md` (469 lines, two dated passes with every finding reproduced on a running system), `docs/UPGRADE_PLAN.md` (381 lines, six phases with workstreams, exit criteria and verification) and `docs/README.md` did not exist before this work. The README was rewritten against measured behaviour.

---

## 3. Work Currently in Progress

| Item | What's real | What's still open |
|---|---|---|
| **Phase 2 — hybrid detection** | Context features, five-tier confidence routing, the Random Forest baseline, the annotation schema, Cohen's κ and the circularity audit all shipped and run. | The dataset they need does not exist. Everything downstream — the held-out test set, the recall-vs-precision comparison, the CodeBERT fine-tune — is blocked on it. |
| **Phase 3 — utility axis** | `evaluation/utility.py` implements paired raw-vs-abstracted collection, a content-addressed response cache, automatic proxies (issue overlap, line-citation agreement) and a blind rating-sheet exporter that keeps the raw/abstracted key in a separate file. | The proposal's 80% utility-preservation target has no instrument that can produce a number without an LLM and human raters. `collect_pairs` raises rather than returning zeros when given no client — deliberately. |
| **Random Forest baseline** | Trains, cross-validates 5-fold stratified, reports feature importances over 27 interpretable shape features that deliberately exclude the SECRET/VALUE regex matches. | It scores 0.70 against the 0.893 regex baseline — the expected consequence of excluding the patterns, since the labels *are* the patterns. `train_and_report` refuses to mark the result trustworthy because the labels were not assigned blind. It is a working harness waiting for real data. |
| **Packaging** | `--version` fixed with a single source of truth in `config/settings.py`; UTF-8 forced via `ensure_utf8_stdout()`, which the evaluation runner calls. | `pip install .` still installs **12 top-level package names** plus the `cli` module — up from the ten the audit found, because `core`, `evaluation`, `ml` and `web` were added since. Any project with its own `config` or `core` package collides. No `src/codeabstract/` layout, no dependency lockfile. |
| **Undeclared runtime dependencies** | The JS adapter, the key store and the RF baseline all work on this machine. | `tree-sitter`, `tree-sitter-javascript`, `keyring` and `scikit-learn` are **not declared** in `pyproject.toml` or `requirements.txt`. They are installed here by history, not by the manifest — a fresh clone gets a JS adapter that cannot parse and a key store with no keychain backend. |
| **Documentation drift** | The README's test-count claim is nearly right. | It says **650 tests**; a live run on 2026-08-20 gives **662**, because `test_leak_regressions.py` grew to 122. Small, but it is the class of claim the audit exists to police. |

---

## 4. Work Remaining / Pending

**Commit and publish the work — pending, and it dominates everything else.**
Twenty-seven modified files and forty untracked paths, including every module the last four months of work produced, exist only in one working tree. Nothing here is backed up, reviewable, or attributable until it is committed. See §6.

**Annotated detection dataset — blocked.**
Roughly 300–500 samples of real code, each labelled independently by two people who have not seen `config/patterns.py`, with provenance recorded. The schema, the κ calculation, the circularity audit, the comparison harness and the RF trainer all exist and will run against it unchanged. Writing it unaided would reproduce the exact defect the audit found, with a fabricated κ on top, so it was not written.

**CodeBERT fine-tune — blocked.** Strictly downstream of the dataset. Fine-tuning on circular labels produces a model that has learned the regexes, and reporting its F1 as detection accuracy would be worse than not building it.

**Utility measurement and the privacy–utility curve — blocked.** Needs an LLM and blind human raters. The apparatus is built; the raters are not a thing to simulate.

**Ten-developer user study — pending.** Named in the proposal. Not started. Same category as the annotators.

**Threat model document — pending, and now urgent.** Phase 3's linkage attack makes writing this a correctness issue rather than a documentation nicety: the system protects identifiers and secrets, and does *not* hide which code you are asking about. That sentence has to appear in a document a user reads before the tool is released.

**Batch mode and pre-commit hook — pending.** Directory scanning and a git hook are the "Compliance" and "Open Source maintainer" rows of the proposal's use-case table, and the CLI serves neither today.

**Paper, thesis, demo video — pending.** To be written against the Phase 3 tables.

**Release — pending.** No PyPI package, no tag (`git tag -l` is empty), no reproducible install from a clean clone.

**VS Code extension — pending.** Stretch goal, explicitly gated: a half-finished plugin costs more credibility than a missing one.

**Continuous integration — pending.** There is no `.github/` directory. The 662 tests, the leak checks and the audit-chain gate all run only when someone runs them by hand.

**Structural defences against re-identification — pending (research).** Noise injection, statement reordering, dead-branch insertion — the differential-privacy-for-syntax idea the proposal sketches. The linkage attack is the instrument that would measure whether they work; nothing has been built for it to measure.

**Repository hygiene — pending.** A dead virtualenv is committed: 2,991 of 3,116 tracked files, 96% of the repository. Its `pyvenv.cfg` points at `C:\Users\HP\OneDrive\Desktop\Projects\IM\.venv` and Python 3.12 on a machine that is not this one. `.gitignore` lists `.venv`, which does nothing for files already tracked.

**Dead code — pending.** `algorithms.abstract._build_inherited_labels` still reads as the authoritative label-propagation pass; `core.context_features.inherited_secret_labels` replaced it in Phase 2. During the audit a patch applied there had no effect at all until it was moved. Confirmed still uncalled on 2026-08-20.

**`f"{p!r:>20}"` where `p = "hunter2"` — limitation.** The flattened template is `{}` — no credential shape — and `p` carries no name signal. Undetectable at `low` and `medium` without abstracting every string literal; correctly abstracted at `high` and `critical`. A property of the level, not a defect.

**Structural re-identification — limitation.** Abstraction preserves AST shape by design, and shape is a fingerprint. This is not closable without giving up the property that makes the output useful to a model. It is a limitation to be *stated*, and the statement is what is missing.

---

## 5. Things Already Done (recap)

| Area | Status |
|---|---|
| Value-level credential redaction across all four privacy levels | done |
| F-string / template whole-value classification | done |
| Import and vendor-brand abstraction, both languages | done |
| Collision-safe token replacement (`VAR_1` vs `VAR_10`) | done |
| Scoped symbol table with occurrence records | done |
| Bidirectional line-number translation | done |
| Four privacy levels with four distinct outputs | done |
| Comment stripping and screened re-injection | done |
| Context-feature detection (11 signals, pooled per symbol) | done |
| Five-tier confidence routing with recorded low-confidence nodes | done |
| Random Forest baseline (gated, honest about its own dataset) | done |
| Adversarial linkage attack + Code Privacy Entropy | done |
| 120-file real corpus (24,737 LOC) | done |
| Regression harness — 5/5 at the old commit, 0/5 now | done |
| Dataset circularity audit + Cohen's κ tooling | done |
| Three LLM providers behind one protocol | done |
| Free-form abstracted queries | done |
| Privacy report (terminal + JSON) | done |
| Hash-chained append-only audit log | done |
| Keys out of the database, into the OS keychain | done |
| JavaScript / TypeScript via tree-sitter | done |
| `.codeabstractignore` overrides that cannot rescue a secret | done |
| Apply-fixes-back with a diff gate | done |
| Flask web workbench, 201 tests | done |
| D1–D5 and L1–L6 fixed with regression tests | done |
| Audit + upgrade-plan documentation set | done |

---

## 6. Issues / Problems Faced

**1. Four months of work is uncommitted, and `HEAD` is the leaking version.**
The last commit is `47d91bc`, 2026-08-08 — before the audit, before every fix. Phases 0 through 5 live entirely in an uncommitted working tree: 27 modified tracked files (+3,368 / −343) and 40 untracked paths including `core/`, `web/`, `ml/`, `docs/`, `llm/base.py`, and every phase test file. A clone of this repository today gets a tool that transmits live credentials at every privacy level, and none of the tests that would prove it.
**Open.** This is the highest-severity item in the report and the cheapest to fix.

**2. The privacy guarantee at the centre of the project did not hold.**
A live Stripe key inside an f-string was transmitted verbatim at every privacy level including `critical`; `db_pass = "hunter2"` was never flagged at any level because no pattern matched the *string* `db_pass`; the internal database host, port and production database name crossed the network at the strictest setting. `_should_abstract()` filtered on each node's own classification, and a variable *named* `api_key` is a different node from the string holding the key.
**Resolved** — value-level redaction plus whole-template f-string classification; 0/21 corpus secrets survive at any level, covered by 51 regression tests.

**3. The evaluation suite was structurally unable to detect its own system's leaks.**
Three of five pillars graded the system against its own assumptions. PIR measured the share of nodes *the classifier flagged* that were then abstracted — blind to a missed secret by construction. It read **0.0024 before the leaks were closed and 0.0024 after**: it did not move when the defects were introduced and did not move when they were fixed. Reconstruction's 100% "hit rate" counted lookups, not whether the substituted text or line number was right, so it was blind to the token-collision bug and the scope-blind mapping. Classification's macro-F1 of 0.894 was computed on labels whose ground-truth notes literally read *"Contains 'api_key'"*.
**Resolved in method, not yet in metric** — the circularity audit now publishes the numbers alongside the F1, and the regression harness demonstrates the suite can fail. PIR itself is unchanged and remains a metric that grades the classifier against itself.

**4. Perfect structural re-identification at every privacy level.**
The linkage attack re-identifies **every file** in the 120-file real corpus, at **every** privacy level, against a random-guess baseline of 0.0083. Identifier survival falls from 86% at `low` to 4.5% at `high` — the identifier-hiding machinery works well — while re-identification stays at 1.000 throughout, because privacy levels govern *names* and the attack reads *shape*.
Two things follow. **Pillar 4's success is Pillar 7's failure:** the AST isomorphism of 1.0000 reported since the first evaluation as evidence that abstraction preserves structure is simultaneously a perfect fingerprint, and the project had been reporting one half of that trade without the other. And **the privacy–utility curve the proposal promises has no trade-off to plot along this axis**, because the privacy term is constant across all four levels.
**Open by design** — not a bug to fix, a limit to write down (§4, threat model).

**5. A second wave of leaks under a green dashboard.**
After D1–D6 were fixed and all five pillars reported success, direct probing found six more live leaks. Four are D1's structural mistake — a value judged on the wrong node — reappearing on axes D1 did not cover: `bytes` rather than `str`, the argument rather than the template, the config file rather than the source file, `VALUE` rather than `SECRET`. Whether a credential was protected depended on whether it was spelled `"sk_live_…"` or `b"sk_live_…"`. The other two were the JavaScript adapter not inheriting a policy the Python path already enforced — including unscreened comments leaking at **all four** levels, worse than Python was before any of this work.
**Resolved** — all six fixed, 122 regression tests. The lesson is the first pass's lesson with a second set of examples: the corpus is what the suite can see, and the suite cannot fail on a construct the corpus does not contain.

**6. Encryption that was doing no work.**
`sessions.db` held the Fernet key in the same row as the ciphertext it unlocked. Anyone who could read the database file could decrypt every mapping table in it — which contains, by construction, every original identifier and every value the detector redacted.
**Resolved** — keys moved to the OS keychain with a documented weaker fallback; verified live, `encryption_key` is empty in every row and `sessions keys` reports 0 keys left in the database.

**7. A metric that penalised the engine for being right.**
The first draft of the new mapping-accuracy pillar scored shadow resolution at 0.59 — which turned out to be the metric penalising the engine for correctly never abstracting `self`. Grading now covers only names the engine actually maps.
**Resolved** — recorded because it is the same failure mode as the circular pillars: a metric measuring the wrong population is as misleading as one that grades itself.

**8. A dataset that was not merely circular but the wrong shape.**
Running the new comparison harness, the hybrid detector scored **identically** to the regex baseline — Δ exactly 0.0000 on every metric, bootstrap interval collapsed to zero. The dataset is node-level: bare `(name, type)` pairs with no surrounding code, so the context tier has nothing to read and the hybrid degrades to its name-pattern tier. The Random Forest scored 0.70 against the 0.893 baseline for the same reason — the labels are "does this name contain one of these substrings", which is not recoverable from morphology.
**Open** — capability is demonstrated by behavioural fixtures instead, and no accuracy figure is claimed from them.

**9. A dead virtualenv from another machine is the bulk of the repository.**
2,991 of 3,116 tracked files are `.venv/`, created under `C:\Users\HP\…\IM` against Python 3.12. The audit could not run the committed environment at all and used system Python 3.13 instead — where `questionary` is not installed, so **`codeabstract interactive` fails on a fresh clone**. Confirmed still true on 2026-08-20.
**Open.**

**10. Advertised extras that no code imported.**
`pyproject.toml` offered `openai` and `anthropic` extras behind a factory that ignored its own provider argument — only Gemini existed.
**Resolved** — all three implemented behind a shared protocol. The inverse problem now exists instead: four packages the shipped features genuinely require are not declared anywhere (§3).

---

## 7. Next Steps

In dependency order. The first three are hours of work each and unblock or de-risk everything else.

1. **Commit the work.** Stage the 27 modified files and the 40 untracked paths, in reviewable commits that map to the phases. Until this happens nothing below matters, because none of it exists anywhere but one disk.
2. **Purge `.venv` from tracking** (`git rm -r --cached .venv`) so the repository is 125 files rather than 3,116, and a clone is usable.
3. **Declare the real dependencies** — `tree-sitter`, `tree-sitter-javascript`, `keyring`, `scikit-learn` — and pin a lockfile. A shipped feature that depends on an undeclared package is a feature that works only on the machine that wrote it.
4. **Move to a `src/codeabstract/` layout** so `pip install .` claims one top-level name instead of thirteen. This is the last open item of Phase 0 and the only one still marked `[ ]`.
5. **Write the threat model.** State plainly that abstraction protects identifiers and secrets and does not hide which code is being asked about, with the Pillar 7 table as its evidence. This gates the release and is the one document Phase 3's finding makes mandatory.
6. **Stand up CI** — the 662 tests, the corpus leak check, the four-level stress run and `audit verify` as a gate. The regression harness already proves the suite discriminates; nothing runs it automatically.
7. **Commission the annotation dataset.** Two people, blind to `config/patterns.py`, 300–500 real samples with provenance. This unblocks the whole second half of Phase 2 and the honest half of Phase 3.
8. **Reconcile the README against measured numbers** — 662 tests, not 650 — and make every claim traceable to a figure in the evaluation report.
9. **Delete `_build_inherited_labels`** before it misleads someone else, as the audit already recommends.
10. **Then the deferred deliverables**: batch mode and the pre-commit hook, the paper and thesis written against the Phase 3 tables, and a tagged, installable release.

---

## 8. Responsibilities / Who Will Do What

**No ownership document exists.** There is no `CODEOWNERS`, no assignment of remaining tasks to named people, and no PR template or dependency-update configuration. This is stated plainly rather than filled in with assumptions.

| Contributor | Commits | Activity |
|---|---|---|
| Imafrah (`imafrah03@gmail.com`) | 14 | Authored the last commit (`47d91bc`, 2026-08-08) and most of the engine's original history — the four algorithms, the CLI, the evaluation metrics. |
| namita naik | 6 | Earlier project history. |
| SowmithShetty | 3 | Initial repository setup, 2026-05-05. |
| Mohammed Afrah Usman (GitHub noreply) | 1 | README edit — the same person as Imafrah, under a GitHub-provided address. |

Three distinct people, 24 commits, all on or before 2026-08-08. `docs/UPGRADE_PLAN.md` estimates effort against "the four-person team in the proposal"; the repository shows three.

**Everything in §2 is unattributed.** The Phase 0–5 work is uncommitted, so git records no author for any of it. Committing it is also what assigns it.

Three decisions in particular cannot be derived from the repository and need an explicit owner: **who commissions and pays for the annotation dataset** (it needs two people's time, blind to the pattern list); **who runs the ten-developer study**; and **who owns the threat model** — because it is the document that decides what the project is allowed to claim.

---

## 9. Timeline / Expected Completion

**No dates are committed anywhere in the repository.** There is no milestone file, no sprint schedule, and no target ship date. `git tag -l` is empty; no version has ever been cut, though `pyproject.toml` and `config/settings.py` both read `1.0.0`.

The only estimates that exist are the per-phase effort figures in `docs/UPGRADE_PLAN.md`, stated for a four-person team with Phases 3 and 4 partly in parallel:

| Phase | Estimated effort | State on 2026-08-20 |
|---|---|---|
| 0 — Make the privacy claim true | 2–3 weeks | Complete but for the packaging layout and lockfile |
| 1 — Rebuild the mapping as a real symbol table | 3–4 weeks | Complete |
| 2 — From regex to hybrid detection | 4–5 weeks | Partial — blocked on human annotation |
| 3 — Evaluation that can fail | 4–5 weeks | Mostly complete — utility axis blocked |
| 4 — Platform: providers, transparency, languages | 3–4 weeks | Complete |
| 5 — Delivery | 3–4 weeks | Partial — web interface shipped |

**Observed elapsed time:** first commit 2026-05-05, last commit 2026-08-08 — about fourteen weeks of committed history, plus roughly two further weeks of uncommitted work dated by the audit documents (18–19 August).

What remains splits cleanly into two kinds of time, and conflating them would produce a meaningless total:

- **Engineering that can be scheduled** — the ten items in §7 that do not need other people. Days to a small number of weeks, not months. Steps 1–4 and 9 are hours each.
- **Work gated on human participants** — the annotation dataset, the blind raters, the ten-developer study. This is calendar time governed by recruitment and other people's availability, not by engineering throughput, and no estimate for it exists in the repository.

Any completion date for this project is really a date for the second category. Setting one is a decision the team has to make; it cannot be read off the code.

---

## 10. Final Overall Status

**A working, well-tested research artifact whose central claim is now true — sitting uncommitted on one machine.**

The privacy guarantee holds where it is defined to hold. Zero of twenty-one corpus secrets survive abstraction at any of the four privacy levels, down from eight at `low` and `medium`; twelve reproduced defects across two audit passes are fixed and pinned by regression tests; mapping accuracy reads 0.9975 against a 0.85 target; throughput is 5,336 LOC/sec against a 1,000 target; 662 tests pass in 79 seconds. Providers, privacy report, audit log, keychain storage, JavaScript support, free-form queries, apply-fixes-back and a tested web workbench are all real and exercised. Phases 0, 1 and 4 are closed; 2, 3 and 5 are partial and each is honest about why.

Two findings define what the project actually is. The first is that the evaluation suite could not detect its own system's leaks — PIR read 0.0024 before and after the defects, and the classification F1 was the regex baseline scored against labels derived from the regexes. The second is that the linkage attack re-identifies every file at every privacy level, which means the AST isomorphism the project has always reported as a success is also a perfect fingerprint, and the privacy–utility curve the proposal promises has no trade-off to plot along that axis. Both are recorded rather than smoothed over, and the second needs to become a written threat model before anything is released.

What is blocked is blocked on people, not code: an annotated dataset needs two annotators working blind, the utility axis needs an LLM and human raters, and the user study needs ten developers. The tooling for all three is built and will run against real data unchanged. Declining to fabricate that data is the correct call and it is why those exit criteria are still open.

Against that, one operational fact outweighs the rest. **`HEAD` is `47d91bc` from 2026-08-08 — the pre-audit engine that leaks credentials at every privacy level.** Every fix, every test, every document in this report exists only in an uncommitted working tree. The project is in materially better shape than its repository is, and closing that gap is the first thing that should happen.

---

## 11. Phase-by-Phase Breakdown (Phase 0 → Phase 5)

Source: `docs/UPGRADE_PLAN.md`, with each status re-derived on 2026-08-20 against the working tree and a live test run rather than taken from the plan's own marks. Phases are ordered by dependency, not by appeal.

### Phase 0 — Make the privacy claim true · *complete but for packaging*

| Workstream | Status | What remains |
|---|---|---|
| Value-level redaction (D1) | done | — |
| F-string whole-template handling (D1) | done | — |
| Import abstraction (D3) | done | — |
| Collision-safe replacement (D2) | done | — |
| Privacy levels wired up (D5) | done | — |
| Housekeeping (D6) | partial | `--version`, UTF-8 and the regenerated report are done. `src/codeabstract/` layout and the lockfile are **the only Phase 0 items still open**. |
| Regression tests | done | 51 tests, one class per defect, asserting on the audit's exact inputs. |

**Exit criteria:** four of five met. Open: *`pip install .` adds exactly one top-level name* — it currently adds twelve packages plus `cli`.

**Verification:** 0/21 corpus secrets leak at every level (was 8/21); four levels produce four distinct outputs; a 30-identifier file round-trips with zero corrupted substitutions; all 70 project source files abstract to valid Python across four levels — 280 runs, zero failures.

### Phase 1 — Rebuild the mapping as a real symbol table · *complete*

| Workstream | Status |
|---|---|
| Scoped symbol table (D4) | done |
| Occurrence records at binding sites | done |
| Abstract ↔ original line translation | done |
| Comment and docstring policy | done |
| Allowlist and user override | done |
| Apply-fixes-back | done |

**Exit criteria:** all four met. Mapping accuracy **0.9975** (definition-site 0.9946, occurrence 0.9955, shadow resolution 1.000, line-map 1.000) against the proposal's 0.85 target.

**Verification:** 77 source files × 4 levels round-trip; the full loop runs end to end from abstract through a simulated response, de-tokenise, diff and apply, with the fix landing under the developer's original names.

### Phase 2 — From regex to hybrid detection · *partial — dataset blocked*

| Workstream | Status | What remains |
|---|---|---|
| De-circularise the dataset | **blocked** | 300–500 real samples, two blind annotators, provenance recorded. Schema, κ and circularity audit are built and waiting. |
| Context features | done | — |
| Random Forest baseline | done (gated) | Scores 0.70 vs a 0.893 regex baseline; refuses to mark itself trustworthy on non-blind labels. Needs the dataset to mean anything. |
| CodeBERT fine-tune | **blocked** | Strictly downstream of the dataset. |
| Confidence and hybrid routing | done | — |

**Exit criteria:** one of three met (zero credential-shaped values missed). The other two need the dataset.

**What the measurements showed:** the hybrid scores **identically** to the regex baseline — Δ 0.0000, bootstrap interval collapsed — because the dataset is node-level and the context tier has nothing to read. The dataset is not merely circular, it is the wrong shape to evaluate what this phase built. Capability is demonstrated behaviourally instead: 7/7 on fixtures a name-regex scores 0/7 on, 0/3 false positives on controls, with no accuracy figure claimed from them.

### Phase 3 — Evaluation that can fail · *mostly complete — utility axis blocked*

| Workstream | Status | What remains |
|---|---|---|
| Corpus to 100+ files | done | 120 stdlib files, 24,737 LOC, 18 domains. |
| Adversarial re-identification | done | — |
| Code Privacy Entropy | done | — |
| Utility measurement | partial | Apparatus complete; the number needs an LLM and blind raters. |
| Developer study | **blocked** | Ten human participants. |
| Reproducibility | done | Every stochastic component seeded (`20260818`); responses cached content-addressed. |

**Exit criteria:** two of three met. Open: a privacy–utility curve with confidence intervals — the privacy axis is measured at all four levels, the utility axis has no instrument.

**The finding (120-file real corpus, chance baseline 0.0083):**

| Privacy level | Top-1 | MRR | CPE | Advantage over chance | Identifiers surviving |
|---|---|---|---|---|---|
| `low` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.864 |
| `medium` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.582 |
| `high` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.045 |
| `critical` | 1.000 | 1.000 | 0.0006 | 1.000 | 0.045 |

A smaller third finding: the token scheme labels its own conclusions. `SECRET_n` announces where a credential sat, at ~11.6 positions per corpus file, information the original identifier may not have carried. A deliberate trade — distinct prefixes help the model reason and keep reconstruction unambiguous — now measured rather than assumed.

**Verification:** regression harness detects **5/5** defects at `47d91bc` and **0/5** on the current engine.

### Phase 4 — Platform: providers, transparency, languages · *complete*

| Workstream | Status |
|---|---|
| Provider abstraction (Gemini, OpenAI, Anthropic) | done |
| Free-form queries, themselves abstracted | done |
| Privacy report (terminal + JSON) | done |
| Hash-chained append-only audit log | done |
| Second language (JS/TS via tree-sitter) | done |
| Key handling (OS keychain + fallback) | done |

**Exit criteria:** three of four met, and the fourth is a matter of running it — *the same file reviewed through all three providers, compared in the evaluation* needs three API keys, and `providers list` reports none set on this machine. Every run emits a privacy report and an audit entry; a JS/TS file abstracts and reconstructs end to end; the database alone is useless without the keychain entry, verified against a live `sessions.db`.

### Phase 5 — Delivery · *partial — web interface shipped*

| Workstream | Status | What remains |
|---|---|---|
| Web interface | done | 201 tests; the privacy claim asserted at the request boundary at all four levels. |
| Batch and pre-commit | not started | Directory scanning and a git hook. |
| Paper and thesis | not started | Write against the Phase 3 tables. |
| Release | not started | PyPI package, tag, threat model, demo video. |
| VS Code extension | not started | Explicitly gated on Phases 0–4 being genuinely closed. |

**Exit criteria:** one of four met. Open: README claims traceable to evaluation figures; a stranger able to clone, install and reproduce the headline results from the docs alone (blocked by the uncommitted tree, the undeclared dependencies and the missing lockfile); the threat model stating the limits explicitly.

---

## 12. Everything Needed for the Project to Be "Complete"

Two definitions of done exist, aimed at the same target from different altitudes. Both are reproduced rather than one being chosen.

### The proposal's numeric targets

| Target | Status |
|---|---|
| ≤ 5% privacy leakage | **Met on the measurable axis** — 0/21 corpus secrets survive at any level. PIR reads 0.0024 against a ≤0.05 target, but PIR is the metric the audit showed cannot detect a miss; the ground-truth leak count is the number that carries the claim. |
| 85%+ mapping accuracy | **Met** — 0.9975. |
| 80% utility preservation | **No instrument.** Blocked on an LLM and blind raters. |
| ≥ 1,000 LOC/sec | **Met** — 5,336 LOC/sec, having paid ~64% of the original 11,916 for the scope analysis, line index and detection pre-passes. |
| 100+ sample evaluation study | **Met in corpus, not in dataset** — 120 real files for structure and adversarial work; the *labelled* dataset is still 150 synthetic nodes and is circular. |
| 10-developer user study | **Not started.** |
| Fine-tuned CodeBERT detector | **Blocked** on the dataset. |
| Random Forest classifier | **Built**, honest about scoring below the baseline and why. |
| Adversarial re-identification attack | **Built**, and it produced the project's sharpest result. |
| Code Privacy Entropy metric | **Built.** |
| Three LLM providers | **Met.** |
| Free-form user query | **Met.** |
| Privacy report | **Met.** |
| Audit log | **Met.** |
| Apply fixes back to source | **Met.** |
| Web UI | **Met** — Flask, 201 tests. |
| JavaScript/TypeScript support | **Met** — tree-sitter, with scoping limits stated. |
| Whitelist + user override | **Met** — and a `keep` rule cannot rescue a real secret. |
| Comment/docstring handling | **Met** — now a stated policy rather than a side effect of `ast.unparse`. |
| Line-number translation | **Met** — 1.000 line-map accuracy. |

### The plan's phase exit criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Phase 0 — no credential survives at any level, four distinct levels, clean packaging | ⚠️ Privacy criteria met; **packaging open** — twelve top-level names, no lockfile. |
| 2 | Phase 1 — scope-correct mapping ≥ 85%, line citations land correctly | ✅ Met — 0.9975. |
| 3 | Phase 2 — independently annotated test set with published κ; hybrid beats baseline with a confidence interval | ❌ **Blocked** on human annotation. |
| 4 | Phase 3 — suite reproduces every Phase 0 defect against the pre-fix commit | ✅ Met — 5/5 at `47d91bc`, 0/5 now. |
| 5 | Phase 3 — privacy–utility curve across four levels with confidence intervals | ❌ **Blocked** — privacy axis measured, utility axis has no instrument. |
| 6 | Phase 4 — three providers compared; privacy report and audit entry per run; JS end to end; database useless without the keychain | ⚠️ Three of four met; the provider comparison needs three API keys. |
| 7 | Phase 5 — browser drives the whole pipeline | ✅ Met. |
| 8 | Phase 5 — README traceable to evaluation figures; a stranger can reproduce from the docs; threat model states the limits | ❌ Open on all three. |

### The single biggest lever

**Commit the work.** Every claim in this report, all 662 tests, the twelve closed defects and the entire documentation set exist in one uncommitted working tree, while the repository's `main` still holds the engine that leaks credentials at every privacy level. It costs an afternoon, it is the prerequisite for review, backup, attribution and CI, and until it is done the honest one-line status of the *repository* is different from the honest one-line status of the *project*.

After that, the remaining work sorts into three piles of very different character:

1. **Hygiene and packaging** — purge the committed virtualenv, declare the four undeclared dependencies, pin a lockfile, move to a `src/` layout, delete the dead propagation pass, reconcile the README's numbers, stand up CI. Mechanical, days of work, and it is what makes "a stranger can clone and reproduce this" true.
2. **The threat model** — one document, gated on nothing, made mandatory by Phase 3's result. It has to say that abstraction protects identifiers and secrets and does not hide which code you are asking about. Writing it is also what decides what the paper is allowed to claim.
3. **Everything gated on people** — the annotated dataset, the blind raters, the ten developers. The tooling is built and will run against real data unchanged. This is the only category with genuinely unknown duration, and it is the one that decides when the *research* is finished rather than when the *software* is.
