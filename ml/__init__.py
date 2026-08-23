"""
Machine-learning detectors for CodeAbstract (Phase 2).

Contains the feature extractor and the Random Forest baseline the proposal
calls for. Both are gated on a non-circular annotated dataset: see
``docs/UPGRADE_PLAN.md`` Phase 2 for why training on the shipped dataset
produces a model that only relearns the regexes it was labelled from.
"""
