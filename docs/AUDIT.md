# CodeAbstract — Codebase Audit

> Performed 18 August 2026 against `main` at `47d91bc`.
> Test suite, evaluation suite and all reproductions run locally on Python 3.13.

Every finding below was **reproduced on a running system**, not inferred from reading code.
Defect IDs `D1`–`D6` are referenced by [UPGRADE_PLAN.md](UPGRADE_PLAN.md) Phase 0.

## Status

| Defect | Severity | Status |
|---|---|---|
| [D1](#d1--secret-literals-are-transmitted-verbatim-at-every-privacy-level) Secret literals transmitted verbatim | Critical | **Fixed** — regression tests in `tests/test_algorithms/test_phase0_regressions.py` |
| [D2](#d2--reconstruct-corrupts-responses-through-token-prefix-collision) Token prefix collision | Critical | **Fixed** |
| [D3](#d3--import-statements-leak-vendor-and-internal-package-names) Import leakage | Critical | **Fixed** |
| [D4](#d4--scope-blind-token-cache-misdirects-every-duplicate-name) Scope-blind token cache | High | **Fixed** — Phase 1, regression tests in `tests/test_algorithms/test_phase1_mapping.py` |
| [D5](#d5--the-critical-privacy-level-is-a-no-op) `critical` is a no-op | High | **Fixed** |
| [D6](#d6--three-smaller-defects-each-a-one-line-fix) `--version`, packaging, stale report | Medium | Partially fixed — packaging layout still open |

Measured on the benchmark corpus, counting real secret literals that survive abstraction:

| Privacy level | Before | After |
|---|---|---|
| `low` | 8 / 21 leaked (38.1%) | **0 / 21** |
| `medium` | 8 / 21 leaked (38.1%) | **0 / 21** |
| `high` | 0 / 21 leaked * | **0 / 21** |
| `critical` | 0 / 21 leaked * | **0 / 21** |

\* The corpus contains no f-string secrets, so it never exercised the `high`-level leak.
That gap is why the hand-built probe in D1 was necessary, and it is the concrete case for
the corpus work in Phase 3.

---

## Current state

| | |
|---|---|
| Lines of Python | 6,590 |
| Tests | 82 / 82 passing (1.65s) |
| Evaluation pillars | 5 implemented |
| Benchmark corpus | 10 synthetic files, 31–48 LOC (proposal target: 100+) |
| LLM providers shipped | 1 of 3 advertised |
| Confirmed leak paths | 4 |

The four formal algorithms are implemented, the CLI works end to end, and the test suite is green.
The problem is not code quality. It is that **the privacy guarantee at the centre of the project does
not currently hold**, and the evaluation suite is structurally unable to detect that.

## What was run

- **Test suite** — `pytest tests/` → 82 passed, no failures, no skips.
- **Evaluation suite** — `python evaluation/run_eval.py` → all five pillars completed;
  performance measured at **11,916 LOC/sec** (12× the proposal's 1,000 LOC/sec target).
- **Direct probes** — called `abstract()` and `reconstruct()` on hand-built inputs covering
  secrets, f-strings, imports, scopes, decorators, async and type hints, at all four privacy levels.
- **Packaging** — inspected the installed `top_level.txt` and the checked-in virtualenv config.

### Environment note

The committed `.venv` is dead on this machine — `pyvenv.cfg` points at `C:\Program Files\Python312`
and was created under `C:\Users\HP\...\IM`. Everything was run against the system Python 3.13
instead, where `questionary` is not installed, so `codeabstract interactive` would fail on a fresh
clone. Fixing this is item one of Phase 0.

---

## D1 — Secret literals are transmitted verbatim at every privacy level

**Severity: Critical** · `algorithms/abstract.py`

`_should_abstract()` filters on each node's own classification label. A variable *named* `api_key` is
tokenised — but the string literal holding the key is a separate `Constant` node, judged on its own
text. At `low` and `medium` it is not abstracted at all. Separately, Step 5b skips every `Constant`
inside an f-string, so f-string secrets leak at **all four** levels.

**Input:**

```python
api_key = "sk_live_51H8xQ2eZvKYlo2C"
db_pass = "hunter2"
conn = f"postgres://admin:{db_pass}@10.2.3.4:5432/prod_billing"
header = f"Bearer sk_live_51H8xQ2eZvKYlo2C"
```

**Sent to the LLM at `privacy=low` and `privacy=medium`:**

```python
SECRET_0 = 'sk_live_51H8xQ2eZvKYlo2C'                            # <-- key in plaintext
db_pass = 'hunter2'                                              # <-- never flagged at all
conn = f'postgres://admin:{db_pass}@10.2.3.4:5432/prod_billing'  # <-- host, port, db name
header = f'Bearer sk_live_51H8xQ2eZvKYlo2C'                      # <-- key again
```

**Sent to the LLM at `privacy=high` and `privacy=critical` (the default):**

```python
SECRET_0 = CONST_0
VAR_0 = CONST_1
VAR_1 = f'postgres://admin:{VAR_0}@10.2.3.4:5432/prod_billing'   # <-- still leaking
VAR_2 = f'Bearer sk_live_51H8xQ2eZvKYlo2C'                       # <-- still leaking
```

Even at the strictest setting the live Stripe key, the internal database host, the port and the
production database name all cross the network. `db_pass` is never flagged at any level because no
pattern in `SECRET_PATTERNS` matches the string `db_pass`.

---

## D2 — RECONSTRUCT corrupts responses through token prefix collision

**Severity: Critical** · `algorithms/reconstruct.py:77`

Token *detection* is word-bounded (`\b(FUNC|VAR|...)_\d+\b`) but token *replacement* is a bare
`str.replace()`. Once a file exceeds ten identifiers of any one prefix, `VAR_1` substitutes itself
inside `VAR_10`.

Reproduced with 12 variables, LLM response mentioning both tokens:

```
in : Bug in VAR_1 and also VAR_10 is wrong.
out: Bug in variable_number_1 (line 2) and also variable_number_1 (line 2)0 is wrong.
```

The developer is pointed at the wrong line of their own code — the precise failure mode bidirectional
mapping exists to prevent. The evaluation's 100% token hit rate never catches it, because hit rate
counts lookups, not replacement correctness.

---

## D3 — Import statements leak vendor and internal package names

**Severity: Critical** · `algorithms/helpers.py`

`ast.alias` nodes are handled nowhere in `_extract_name()` or `_get_node_name()`, so the entire import
block passes through untouched.

Reproduced at `privacy=high`:

```python
import stripe                                # <-- verbatim
from acme_internal.billing import ledger     # <-- verbatim
VAR_0.FUNC_0(NUM_0)
```

"Brand references" are named in the proposal as a category the system protects, and the worked
example in the proposal is *literally Stripe*.

Import names also give an attacker a free alignment oracle: `from typing import Optional` survives
while its use site becomes `VAR_4[str]`, letting a re-identification attack pin `VAR_4` immediately.

---

## D4 — Scope-blind token cache misdirects every duplicate name

**Severity: High** · `algorithms/abstract.py`

The `seen` cache is a single flat `name -> token` dict for the whole module, and the mapping entry
stores only the *first* line number that name appeared on.

**Input:**

```python
def alpha(data):
    result = data * 2
    return result

def beta(data):
    result = data + 1
    return result
```

**Output — one token, two meanings:**

```python
def FUNC_0(VAR_0):
    VAR_1 = VAR_0 * NUM_0      # <-- VAR_1 recorded at this line
    return VAR_1

def FUNC_1(VAR_0):
    VAR_1 = VAR_0 + NUM_1      # <-- same token, this line never recorded
    return VAR_1
```

If the LLM reports a bug in `VAR_1` inside `FUNC_1`, reconstruction sends the developer to `alpha()`.
This is the direct blocker on the proposal's **85%+ mapping accuracy** target, and no metric currently
measures it.

---

## D5 — The `critical` privacy level is a no-op

**Severity: High** · `config/settings.py`

`critical` and `high` produce byte-identical output (verified). `_should_abstract()` returns `True`
for both, and `is_semantically_significant()` drops single-character names unconditionally, with no
access to the privacy level.

The entire `PRIVACY_LEVELS` table in `config/settings.py` — including the `abstract_short_names` flag
that defines the difference — is dead code, read by nothing.

---

## D6 — Three smaller defects, each a one-line fix

**Severity: Medium**

- **`--version` crashes.** `cli.py:202` does `from . import __version__`, but `cli` installs as a
  top-level module → `ImportError: attempted relative import with no known parent package`.
- **Installing the package pollutes site-packages.** `top_level.txt` confirms ten generic top-level
  names ship: `algorithms`, `cli`, `commands`, `config`, `core`, `llm`, `storage`, `tests`, `ui`,
  `utils`. Any project with its own `config` package collides.
- **The committed evaluation report is stale.** `evaluation_output/` shows `0 LOC/sec` and an empty
  Pillar 5 table; a fresh run gives `11,916 LOC/sec`. The runner also dies with `UnicodeEncodeError`
  on a cp1252 Windows console after the reports are written.

---

## Measurement integrity

The five-pillar suite is well-built and genuinely useful. Its problem is not code quality — it is that
three of the five pillars are graded against the system's own assumptions.

| Pillar | Reported | What it actually measures | Consequence |
|---|---|---|---|
| Privacy (PIR) | 0.0024 | The share of nodes *the classifier flagged* that were then abstracted | Blind to D1 by construction. Anything the classifier misses cannot appear in the denominator. |
| Reconstruction | 100% hit rate | Whether tokens are found in the mapping table | Blind to D2 and D4 — never checks that the substituted text or line number is right. |
| Classification | F1 0.894 | Regex self-consistency. Ground-truth notes in `labeled_nodes.py` literally read *"Contains 'api_key'"* | Labels were derived from the patterns under test. The number cannot fall much below 1.0 by design. |
| Structure | AST isomorphism 1.0 | Genuine and sound. Renaming preserves shape. | Keep as is. |
| Performance | 11,916 LOC/s | Genuine and sound; 12× the proposal's target. | Keep, but re-commit the report — the stored one reads 0. |
| Utility | — | Not measured anywhere | The proposal's 80% utility-preservation target has no instrument at all. |

**The corpus is also too small and too friendly.** Ten synthetic files of 31–48 LOC, authored
alongside the tool, against a proposal target of 100+ samples. Nothing in it contains an f-string
secret, a duplicate name across scopes, or more than ten variables — which is exactly why D1, D2 and
D4 survived to today with a green dashboard.

---

## Feature gaps against the proposal

| Promised in `Project Implementation.pdf` | Status |
|---|---|
| Fine-tuned CodeBERT secret detector | Not started |
| Random Forest sensitivity classifier | Not started |
| Adversarial re-identification attack | Not started |
| Code Privacy Entropy metric | Not started |
| OpenAI + Anthropic providers | Advertised in `pyproject.toml` extras; only Gemini implemented |
| Free-form user query | Only 5 fixed task presets |
| Privacy report output | Not started |
| Audit log | Not started |
| Apply suggested fixes back to source | Not started |
| Web UI (Streamlit/Flask) | Shipped in Phase 5 — Flask, see UPGRADE_PLAN.md |
| JavaScript/TypeScript support | Not started |
| 100+ sample evaluation study | 10 synthetic files |
| 10-developer user study | Not started |
| Whitelist + user override (stated risk mitigation) | Not started |
| Comment/docstring handling | `ast.unparse` discards all comments as a side effect, not a policy |
| Line-number translation abstract ↔ original | Missing entirely — LLM cites abstract line numbers that are never translated |

---

# Second pass — end-to-end audit, 19 August 2026

> Performed against `main` after the D1–D6 fixes, on Python 3.13.
> Method: the 526-test suite as a baseline, then direct probes of every
> command, the web API, both language adapters and all four privacy levels,
> with credential canaries planted in each.

The suite was green and the five pillars all reported success. These six
leaks were found underneath that, by probing constructs the corpus does not
contain. Each was reproduced, then fixed, then covered by a regression test
in `tests/test_algorithms/test_leak_regressions.py`.

| Defect | Severity | Levels affected | Status |
|---|---|---|---|
| [L1](#l1--bytes-literals-bypass-value-shape-detection) `bytes` credentials undetected | Critical | `low`, `medium` | **Fixed** |
| [L2](#l2--javascript-comments-are-never-screened) JavaScript comments unscreened | Critical | **all four** | **Fixed** |
| [L3](#l3--vendor-brand-references-leak-from-javascript-imports) Vendor imports leak in JS | High | **all four** | **Fixed** |
| [L4](#l4--values-flowing-into-a-credential-template-are-not-tainted) Credential-template taint | High | `low`, `medium` | **Fixed** |
| [L5](#l5--config-show-prints-stored-api-keys) `config show` prints API keys | Medium | n/a | **Fixed** |
| [L6](#l6--endpoint-literals-are-never-classified-value) Endpoint literals not VALUE | Medium | `medium` | **Fixed** |

**What connects them.** Four of the six are D1's structural mistake — a
value judged on the wrong node — reappearing on axes D1 did not cover:
`bytes` rather than `str` (L1), the argument rather than the template (L4),
the config file rather than the source file (L5), and VALUE rather than
SECRET (L6). The other two are the JavaScript adapter not inheriting a
policy the Python path already enforced. Neither pattern was visible from
the test suite that was passing, which is the same measurement-integrity
point the first pass made about the five pillars.

## L1 — bytes literals bypass value-shape detection

**Severity: Critical** · `core/secret_detector.py`

Every public entry point began `if not value or not isinstance(value, str)`,
so a `bytes` literal never reached the credential patterns at all:

```python
k = b'sk_live_51H8xQ2eZvKYlo2C'   # transmitted verbatim at low and medium
k =  'sk_live_51H8xQ2eZvKYlo2C'   # correctly abstracted at every level
```

Whether the credential was protected depended on the literal's *prefix*.
Every format in `_CREDENTIAL_PATTERNS` is an ASCII wire format, and the code
that handles one commonly holds it as bytes — `hmac.new(b"sk_live_...", ...)`
is the idiomatic spelling, not the exotic one. `TOKEN = b"ghp_..."` looked
fine only by accident: it was caught by its *name*, because `str(node.value)`
happened to contain the text.

**Fix.** `as_text()` coerces `str`/`bytes`/`bytearray` and returns `''` for
undecodable input; the four detectors and `classify._get_literal_text` route
through it.

## L2 — JavaScript comments are never screened

**Severity: Critical** · `algorithms/abstract_source.py`, `core/languages/javascript.py`

`core/comment_handler.py` states the policy in full — stripped by default,
screened when kept, because a comment is where business context lives most
densely. Python obeys it, but only because `ast.unparse` cannot reproduce
comments. A byte-range rewrite removes nothing it is not told to, and nothing
told it to:

```javascript
// key is sk_live_51H8xQ2eZvKYlo2C     <-- verbatim, including at critical
```

Worse than the Python path was before Phase 0, because it held at *every*
privacy level.

**Fix.** `JavaScriptAdapter.comments()` reads comment ranges from the parse
tree — not a regex, so `//` inside a string literal is not mistaken for a
comment — and `_screen_comments()` applies the stated policy for any adapter
exposing the method. `--keep-comments` now means something outside Python.

## L3 — Vendor brand references leak from JavaScript imports

**Severity: High** · `config/allowlist.py`

`is_safe_module('stripe')` is False. `is_safe_js_module('stripe')` was True:
the JavaScript list shipped `stripe`, `twilio` and `openai` as public
vocabulary, so the same import was hidden in one language and sent in the
other.

```javascript
import stripe from "stripe";   // verbatim at every level
```

The proposal names brand references as a protected category and its worked
example is Stripe; D3 made the same argument for Python. The allowlist's own
comment argued that the SDK name is public — true, and beside the point:
`import stripe` is the business fact that the company takes card payments.

**Fix.** Removed from `_JS_PUBLIC_PACKAGES`. Generic cloud SDKs (`aws-sdk`,
`firebase`, `googleapis`) stay, mirroring Python's `boto3`, `google`,
`azure`; a test now asserts the two lists agree about the vendors.

## L4 — Values flowing into a credential template are not tainted

**Severity: High** · `core/context_features.py`, `core/languages/javascript.py`

Phase 0 flattened `f"postgres://admin:{db_pass}@10.2.3.4/prod"` so the
connection-string detector could see it, and redacted the template's
*literal fragments*. So the system identified the placeholder as a password
position and then transmitted the password that filled it:

```python
p = 'hunter2'                                          # <-- verbatim
conn = f'postgres://admin:{p}@10.2.3.4:5432/prod'      # <-- correctly redacted
```

`db_pass` survived only because its own name matched a pattern. Rename it
`p` and every signal disappears — precisely the case flattening exists for.

A second gap sat beside it: `f"Bearer {token}"` was **never detected**,
although `_handle_template`'s docstring cites that exact string as its
motivating example. The `auth_header` pattern required 8+ literal characters
after the scheme word, and the placeholder supplies none.

**Fix.** A `credential_template` signal marks names interpolated into a
credential-shaped template, in both languages, and `.format()` / `%`
arguments alongside them. Marking stays shallow, as `_mark` already
documents: `f"...{build(user_id)}..."` names no binding, so `user_id` is not
dragged in. The `auth_header` pattern now accepts the `{}` placeholder, and
only that, so prose like "bearer of this note" stays unflagged.

## L5 — config show prints stored API keys

**Severity: Medium** · `commands/config_cmd.py`

Every value was rendered with `str(value)`, so a stored provider key was
printed in full — and `config set` echoed the key back into shell history as
it saved it. `config show` is what a user runs when something is wrong, and
pastes into a bug report.

**Fix.** Keys whose names contain `api_key`/`token`/`secret`/`password`/
`credential` are masked through the existing `mask_secret()`; `--reveal`
prints them in full. Substring matching means a provider added later is
covered on the day it is added rather than the day someone updates a list.

## L6 — Endpoint literals are never classified VALUE

**Severity: Medium** · `algorithms/classify.py`, `core/secret_detector.py`

`medium` is documented — in the README's table and in `PRIVACY_LEVELS` — as
abstracting "rates, fees, endpoints". It abstracted an endpoint only when
the *identifier* was named like one, and the literal was a separate node
judged on its own text:

```python
endpoint_url = "https://api.payment.com/v2"
# medium produced:  VAR_0 = 'https://api.payment.com/v2'
```

The name was tokenised and the URL it named was transmitted beside it —
D1's split between a binding and its value, on the axis D1 did not cover.

**Fix.** An `endpoint-literal` tier classifies URLs and dotted quads as
VALUE. Deliberately narrow: octet ranges are checked so `1.0` is a version
and not a host, and bare hostnames are excluded because `a.b.c` is as likely
to be a module path. Credentials are judged first, so a connection string
with an inline password is still a SECRET rather than a mere endpoint.
Endpoints correctly still survive at `low`, which is defined as secrets only.

## What was verified and found sound

Worth recording, because the first pass's finding was that green dashboards
can hide leaks. These were probed on a running system, not assumed:

- **Encryption at rest.** No plaintext secret appears in `sessions.db`; the
  `encryption_key` column is empty in every row, and every key lives in the
  OS keychain — `sessions keys` reports 0 keys still in the database.
- **Audit chain.** Editing one entry is detected and named, and the command
  exits non-zero, so it works as a CI gate.
- **Web layer.** No XSS across six payload families in the code panes, vault
  rows, translated feedback and error pages — checked by parsing the HTML
  for live tags and event-handler attributes, not by substring matching.
  CSRF is closed by the JSON-only rule for mutating requests; oversized
  bodies, bad privacy levels, non-integer context windows, unknown
  extensions and path-traversal filenames are all rejected with 4xx.
- **`reveal` needs two gates.** A browser request alone cannot unmask a
  secret; the server must also have been started with `--allow-reveal`.
- **Free-form queries are abstracted.** A question naming
  `calculate_stripe_commission` and `STRIPE_API_KEY` reaches the provider as
  `Why does FUNC_0 mishandle SECRET_2 and SECRET_0?`.
- **D2, D4 and D5 regressions hold.** `VAR_10` no longer collides with
  `VAR_1`, duplicate names in different scopes get distinct tokens, and
  `high` and `critical` produce different output.
- **Reconstruction is robust** against empty, unknown-token, malformed,
  20,000-token, regex-metacharacter, backslash-escape, NUL-byte and
  non-ASCII responses, and refuses a corrupt mapping or a wrong key.
- **Performance.** 5,300–7,800 LOC/sec against the proposal's 1,000 target —
  about 0.2s per 1,000 lines against a 3-second budget.

## Still open

- **Utility (the 80% target) has no instrument.** Unchanged from the first
  pass: it needs an LLM and human raters.
- **`f"{p!r:>20}"` where `p = "hunter2"`.** The flattened template is `{}` —
  no credential shape — and `p` carries no name signal. Undetectable at
  `low` and `medium` without abstracting every string literal; abstracted at
  `high` and `critical`. A limitation of the level, not a defect.
- **`algorithms.abstract._build_inherited_labels` is dead code.** Phase 2
  replaced it with `core.context_features`, and it still reads as the
  authoritative propagation pass — a patch applied there during this audit
  had no effect at all until it was moved. Worth deleting before it misleads
  someone else.
