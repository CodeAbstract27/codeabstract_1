# CodeAbstract Documentation

| Document | What it covers |
|---|---|
| [AUDIT.md](AUDIT.md) | Two passes. **First:** six reproduced defects (`D1`–`D6`) as of `47d91bc`, why the evaluation suite reports success on a leaking system, and the feature gaps against `Project Implementation.pdf`. **Second (19 Aug):** six further leak paths (`L1`–`L6`) found by end-to-end probing after the D-fixes landed, plus what was probed and found sound. |
| [UPGRADE_PLAN.md](UPGRADE_PLAN.md) | Six-phase upgrade plan with workstreams, effort estimates, dependencies and exit criteria per phase. |

## Status

| Phase | State |
|---|---|
| 0 — Make the privacy claim true | Complete except the `src/codeabstract/` layout and lockfile |
| 1 — Rebuild the mapping as a real symbol table | Complete |
| 2 — From regex to hybrid detection | Partial — context detection and hybrid routing shipped; the dataset, and everything downstream of it, is blocked on human annotation |
| 3 — Evaluation that can fail | Mostly complete — adversarial evaluation, CPE, 120-file real corpus and the historical regression harness shipped; the utility axis needs an LLM and human raters |
| 4 — Platform: providers, transparency, languages | Complete |
| 5 — Delivery | Partial — the web interface shipped; batch/pre-commit, the paper and the release have not |

Defects D1–D5 are fixed and covered by regression tests; D6 is partially fixed (the stale
evaluation report has been regenerated; the packaging layout is still open). L1–L6 from the
second pass are fixed and covered by `tests/test_algorithms/test_leak_regressions.py`.
**650 tests pass.**

## Start here

Read the audit first — the plan's phase ordering only makes sense once the evidence is clear.

**What the audit found:** the privacy guarantee did not hold. A live API key inside an f-string was
transmitted verbatim at *every* privacy level, including the strictest, and the evaluation suite could
not detect it. See [D1](AUDIT.md#d1--secret-literals-are-transmitted-verbatim-at-every-privacy-level).

**Where it stands now:** 0 of 21 corpus secrets survive abstraction at any level, and mapping accuracy
is 0.9975 against the proposal's 0.85 target. The one metric that has *not* moved through any of this
is PIR — it read 0.0024 before the fixes and 0.0024 after, which is the case for the evaluation
rebuild in Phase 3.

**What the second pass adds to that case.** Six more leak paths were live while every pillar reported
success, and PIR did not move for those either. Two of them (`L2`, `L3`) leaked at *every* privacy
level including `critical`, and one (`L1`) made protection depend on whether a credential was spelled
`"sk_live_…"` or `b"sk_live_…"`. None is exotic; none appears in the corpus. That is the same finding
as before, now with a second set of examples: the corpus is what the suite can see, and the suite
cannot fail on a construct the corpus does not contain.

**What Phase 2 could not do.** Its first workstream needs a dataset labelled by two people working blind
to the pattern list. Writing that dataset unaided would reproduce the exact defect the audit found, so it
was not written. The tooling it needs — annotation schema, Cohen's κ, and a circularity audit — shipped
instead, and running the audit put numbers on the problem: 61% of the existing dataset's labels are
justified by quoting the patterns they are used to grade, and only 16 of 150 items can tell two detectors
apart. See [UPGRADE_PLAN.md](UPGRADE_PLAN.md#phase-2--from-regex-to-hybrid-detection) for what would
unblock it.

**What Phase 3 found.** The suite is now demonstrably capable of failing: run against the pre-fix commit
it reports 5/5 defects, and 0/5 against the current engine. The new adversarial pillar produced the
sharpest result in the project so far — a linkage attack re-identifies **every** file in a 120-file real
corpus, at **every** privacy level, against a random-guess baseline of 0.0083. The AST isomorphism of
1.0000 that Pillar 4 has always reported as a success is simultaneously a perfect fingerprint. See
[UPGRADE_PLAN.md](UPGRADE_PLAN.md#the-finding).
