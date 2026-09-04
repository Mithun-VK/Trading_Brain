"""V5 — the alpha hypothesis interface.

An `AlphaHypothesis` is a `backtesting.strategy.Strategy` plus everything a
strategy alone does not carry: its mechanism, its parameter provenance, and
a promise about determinism. It does not replace `Strategy` -- it wraps one
so the engine that already runs MA 20/50, buy-and-hold, and every V2-V4.1
backtest keeps running unchanged (`build_strategy()` hands back exactly the
object `BacktestEngine.run()` already knows how to consume).

**Determinism is a contract, not a hope.** `AlphaHypothesis.signature()`
hashes the hypothesis id, its parameter values, and its dataset dependency
list. `evaluator.py` uses this to detect the one failure mode this whole
exercise is meant to prevent silently: the same nominal experiment producing
different numbers on a rerun because something -- a parameter, a data
dependency, a code path -- was not actually fixed.
"""

from __future__ import annotations

import hashlib
import json
import random
from abc import ABC, abstractmethod

from backtesting.strategy import Strategy
from experiments.alpha.schema import HypothesisMetadata, ParameterSet


class AlphaHypothesis(ABC):
    """A deterministic alpha candidate.

    Subclasses implement `build_strategy()`, returning a fresh
    `backtesting.strategy.Strategy` each call -- fresh, because a strategy
    instance carries mutable state across a backtest run and reusing one
    across trials would leak state between them (this project has already
    hit that exact bug once, in the random-entry control's `on_start`
    contract).
    """

    def __init__(self, metadata: HypothesisMetadata, parameters: ParameterSet) -> None:
        self.metadata = metadata
        self.parameters = parameters

    @abstractmethod
    def build_strategy(self) -> Strategy:
        """A fresh, ready-to-run Strategy instance for the backtest engine."""

    def build_placebo_strategy(self, rng: random.Random) -> Strategy | None:
        """A feature-permutation placebo: the same trade structure (dates,
        holding periods, universe) as the real strategy, with the signal's
        actual information content severed -- e.g. ranking on a shuffled
        feature rather than the real one.

        Optional, and `None` by default. Not every hypothesis has a natural
        permutation (a single-ticker crossover has no cross-sectional
        ranking to shuffle); forcing one would produce a placebo that tests
        nothing. A hypothesis that returns `None` here is evaluated with
        the entry-timing placebo (Stage 4's random-entry control) alone --
        `evaluator.py` records which placebo(s) actually ran, so a report
        never implies a permutation test happened when it did not.
        """
        return None

    @property
    def hypothesis_id(self) -> str:
        return self.metadata.hypothesis_id

    def signature(self) -> str:
        """A content hash of everything that must be fixed for a rerun to
        be the same experiment: hypothesis id, parameter values, and
        declared data dependencies. Two runs with different signatures are
        not directly comparable, however similar their results look."""
        payload = json.dumps(
            {
                "hypothesis_id": self.metadata.hypothesis_id,
                "parameters": {
                    k: v for k, v in sorted(self.parameters.as_values().items())
                },
                "data_dependencies": sorted(self.metadata.data_dependencies),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(),
            "parameters": self.parameters.to_dict(),
            "signature": self.signature(),
        }
