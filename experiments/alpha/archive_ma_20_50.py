"""V5 — ingests MA 20/50's V4.1 falsification as a historical registry
record, without rerunning it.

Run:  python -m experiments.alpha.archive_ma_20_50

Per the phase brief: "Move or register the existing MA 20/50 strategy as
ARCHIVED, FALSIFIED. Do not delete its historical experiments or reports.
Add a metadata record pointing to f6cac64 and the V4.1 falsification
report." This script does exactly that and nothing else -- it does not
touch `experiments/v2_baseline.py`, `experiments/v4_regime.py`, or any of
the V2-V4.1 result JSON files, all of which remain exactly where they were
committed.
"""

from __future__ import annotations

import sys

from experiments.alpha.registry import ExperimentRegistry
from experiments.alpha.schema import ExperimentStatus, HypothesisMetadata

MA_HYPOTHESIS_ID = "ma_20_50_v1"
FALSIFICATION_COMMIT = "f6cac64"
FALSIFICATION_REPORT = "docs/V4_1_SIGNAL_FALSIFICATION_REPORT.md"


def ma_20_50_metadata() -> HypothesisMetadata:
    """Reconstructed from the V2/V4/V4.1 work, not a new hypothesis --
    this hypothesis predates the HypothesisMetadata schema, so this is a
    faithful after-the-fact record of what was actually tested, not a
    reformulation.
    """
    return HypothesisMetadata(
        hypothesis_id=MA_HYPOTHESIS_ID,
        hypothesis_name="Moving Average 20/50 Crossover",
        economic_mechanism=(
            "Single-name price trend persistence: a fast moving average "
            "crossing above a slow one signals an established uptrend "
            "worth participating in, on the premise that trends persist "
            "longer than a single crossing implies."
        ),
        expected_direction="long while fast SMA > slow SMA, flat otherwise",
        expected_holding_period="weeks to months, until the crossover reverses",
        expected_market_behavior=(
            "Expected to outperform in sustained trending markets and "
            "underperform (whipsaw) in range-bound, low-trend markets."
        ),
        required_features=("sma_20", "sma_50"),
        known_failure_modes=(
            "Whipsaws in sideways/range-bound markets.",
            "Lag: a crossover confirms a trend after a meaningful portion "
            "of the move has already happened.",
            "Concentration in whichever single name is trending hardest.",
        ),
        falsification_criteria=(
            "Does not beat matched random entry at the 95th percentile.",
            "Does not beat regime-matched random entry within a modeled regime.",
            "Result collapses when the largest P&L contributor is excluded.",
        ),
        researcher="TradingBrain research (V2-V4.1)",
        data_dependencies=("yahoo_daily_ohlcv",),
    )


def main() -> int:
    registry = ExperimentRegistry()
    if MA_HYPOTHESIS_ID in {e.metadata.hypothesis_id for e in registry.list_all()}:
        print(f"{MA_HYPOTHESIS_ID} is already archived.")
        return 0

    note = (
        f"FALSIFIED at commit {FALSIFICATION_COMMIT} "
        f"(see {FALSIFICATION_REPORT}). SIGNAL STATUS: D -- EVIDENCE OF "
        "FALSE EDGE. Win rate at or below the 1st percentile of matched "
        "random entry in all four periods (train/validation/test/full); "
        "regime-conditioned random control not beaten in any of the three "
        "HMM-modeled regimes (20.8th/32.4th/94.4th percentile); NVDA alone "
        "supplied 43.9% of total P&L. Not rerun by the V5 framework -- this "
        "is a historical negative result, ingested as-is per "
        "docs/RESEARCH_GOVERNANCE.md rule 5 (no deleting failed experiments) "
        "and rule 6 (no renaming failed hypotheses to hide lineage)."
    )
    registry.archive_historical(
        ma_20_50_metadata(), status=ExperimentStatus.FALSIFIED, note=note,
    )
    registry.save()
    print(f"Archived {MA_HYPOTHESIS_ID} as FALSIFIED, pointing to "
          f"{FALSIFICATION_COMMIT} / {FALSIFICATION_REPORT}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
