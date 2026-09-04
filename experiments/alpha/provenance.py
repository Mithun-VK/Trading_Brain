"""V5 — the reproducibility manifest.

A run's manifest is what makes "rerun this and check" a real option instead
of a request nobody can act on. It records the git commit, the exact data
snapshot (reusing `experiments.runner.snapshot_bars`, not a second hashing
scheme), the parameter set with its provenance, the cost model, the random
seed, and the dataset contract -- everything named in the phase brief's
example schema.

The manifest is written once per run and never edited. A changed
configuration is a new run, not a patched manifest -- editing history is
exactly what a reproducibility record exists to make impossible.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
from dataclasses import dataclass, field

from data.ingestion.schemas import PriceBar
from experiments.alpha.schema import DatasetContract, ParameterSet
from experiments.config import CostModel, Period
from experiments.runner import snapshot_bars

MANIFEST_DIR = pathlib.Path("experiments/.manifests")


def current_git_commit() -> str:
    """The commit the run was executed against.

    Falls back to an explicit 'unknown' string rather than raising --
    a manifest that cannot be written because git is unavailable would
    lose the rest of the run's record over a detail the run's actual
    result does not depend on. The fallback is still visibly a failure,
    never a fabricated hash.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001 -- git unavailability must not lose the run
        return "unknown"


def is_working_tree_dirty() -> bool | None:
    """Whether uncommitted changes were present when the run executed.

    Returns None (unknown) rather than guessing when git itself is
    unavailable -- a manifest asserting a clean tree it never actually
    checked would be worse than one admitting it could not tell.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return bool(result.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class RunManifest:
    """Everything needed to reproduce one experiment run."""

    run_id: str
    hypothesis_id: str
    hypothesis_signature: str
    git_commit: str
    working_tree_dirty: bool | None
    dataset_snapshot: str
    dataset_contract: DatasetContract
    universe: tuple[str, ...]
    periods: dict[str, Period]
    parameters: ParameterSet
    cost_model: CostModel
    random_seed: int
    controls: dict[str, object] = field(default_factory=dict)
    regime_model: dict[str, object] | None = None
    test_contaminated: bool = False
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_signature": self.hypothesis_signature,
            "git_commit": self.git_commit,
            "working_tree_dirty": self.working_tree_dirty,
            "dataset_snapshot": self.dataset_snapshot,
            "dataset_contract": {
                "provider": self.dataset_contract.provider,
                "universe_type": str(self.dataset_contract.universe_type),
                "survivorship_bias_risk": str(self.dataset_contract.survivorship_bias_risk),
                "corporate_action_quality": str(self.dataset_contract.corporate_action_quality),
                "delisted_security_coverage": str(
                    self.dataset_contract.delisted_security_coverage
                ),
                "timezone": self.dataset_contract.timezone,
                "adjusted_prices": self.dataset_contract.adjusted_prices,
                "interval": self.dataset_contract.interval,
                "note": self.dataset_contract.note,
                "warnings": self.dataset_contract.warnings(),
            },
            "universe": list(self.universe),
            "periods": {name: p.to_dict() for name, p in self.periods.items()},
            "parameters": self.parameters.to_dict(),
            "cost_model": {
                "commission_bps": self.cost_model.commission_bps,
                "slippage_bps": self.cost_model.slippage_bps,
                "spread_bps": self.cost_model.spread_bps,
                "execution_delay_bars": self.cost_model.execution_delay_bars,
            },
            "random_seed": self.random_seed,
            "controls": self.controls,
            "regime_model": self.regime_model,
            "test_contaminated": self.test_contaminated,
            "created_at": self.created_at.isoformat(),
        }

    def content_hash(self) -> str:
        """A hash of the manifest's own content, for the reproducibility
        test: two runs with identical inputs must produce identical
        manifests apart from `run_id` and `created_at`."""
        payload = self.to_dict()
        payload.pop("run_id", None)
        payload.pop("created_at", None)
        import hashlib

        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    def save(self, directory: pathlib.Path = MANIFEST_DIR) -> pathlib.Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=1, default=str), encoding="utf-8")
        return path


def dataset_snapshot_for(bars_by_ticker: dict[str, list[PriceBar]]) -> str:
    """The one hashing scheme for 'what data was this' -- reused, not
    reimplemented, from the runner that already backs V2-V4.1."""
    return snapshot_bars(bars_by_ticker)


def make_run_id(hypothesis_id: str, signature: str, seed: int) -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
    return f"{hypothesis_id}-{signature}-seed{seed}-{stamp}"
