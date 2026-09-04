"""V5 — the experiment registry.

A JSON-file-backed ledger of every hypothesis this pipeline has ever
evaluated, and the one place status transitions are enforced rather than
assumed. Two rules carry the whole module:

**No path back from a terminal status to `PROPOSED`.** `FALSIFIED`,
`TEST_CONTAMINATED`, and `ARCHIVED` are terminal: `ALLOWED_TRANSITIONS` has
no outgoing edge from any of them. A falsified hypothesis is archived, not
quietly retried under the same id -- "a materially changed hypothesis must
receive a new hypothesis ID" is enforced here by making the old id a dead
end, not by asking a researcher to remember the rule.

**A registry never deletes.** `record_run` appends; nothing in this module
removes a hypothesis or a run once written. Research governance rule 5
("no deleting failed experiments") is a property of what operations this
module exposes, not a policy someone could forget to follow.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import dataclass, field

from experiments.alpha.schema import DecisionStatus, ExperimentStatus, HypothesisMetadata

REGISTRY_PATH = pathlib.Path("experiments/.registry/hypotheses.json")

# The complete transition graph. Absence of an edge is the enforcement --
# there is no separate "is this allowed" rule list to fall out of sync with
# this one.
ALLOWED_TRANSITIONS: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.PROPOSED: frozenset({ExperimentStatus.IN_DEVELOPMENT}),
    ExperimentStatus.IN_DEVELOPMENT: frozenset({ExperimentStatus.VALIDATION}),
    ExperimentStatus.VALIDATION: frozenset({
        ExperimentStatus.TEST_READY, ExperimentStatus.FALSIFIED,
    }),
    ExperimentStatus.TEST_READY: frozenset({
        ExperimentStatus.TESTED, ExperimentStatus.TEST_CONTAMINATED,
    }),
    ExperimentStatus.TESTED: frozenset({
        ExperimentStatus.SURVIVED_FALSIFICATION, ExperimentStatus.FALSIFIED,
        ExperimentStatus.TEST_CONTAMINATED,
    }),
    ExperimentStatus.SURVIVED_FALSIFICATION: frozenset({
        ExperimentStatus.PAPER_TRADING_CANDIDATE, ExperimentStatus.ARCHIVED,
    }),
    ExperimentStatus.PAPER_TRADING_CANDIDATE: frozenset({ExperimentStatus.ARCHIVED}),
    # Terminal: no outgoing edges.
    ExperimentStatus.FALSIFIED: frozenset(),
    ExperimentStatus.TEST_CONTAMINATED: frozenset(),
    ExperimentStatus.ARCHIVED: frozenset(),
}


class InvalidTransitionError(ValueError):
    """A status change that the lifecycle does not permit."""


class UnknownHypothesisError(KeyError):
    pass


@dataclass
class RunRecord:
    run_id: str
    manifest_path: str
    stage: str  # e.g. "validation", "test", "control", "regime", "robustness"
    result_summary: dict = field(default_factory=dict)
    recorded_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "manifest_path": self.manifest_path,
            "stage": self.stage,
            "result_summary": self.result_summary,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunRecord:
        return cls(
            run_id=data["run_id"], manifest_path=data["manifest_path"],
            stage=data["stage"], result_summary=data.get("result_summary", {}),
            recorded_at=dt.datetime.fromisoformat(data["recorded_at"]),
        )


@dataclass
class RegistryEntry:
    metadata: HypothesisMetadata
    status: ExperimentStatus = ExperimentStatus.PROPOSED
    dataset_snapshot: str | None = None
    runs: list[RunRecord] = field(default_factory=list)
    decision: DecisionStatus | None = None
    decision_reasons: list[str] = field(default_factory=list)
    test_observed: bool = False
    archived_note: str = ""
    superseded_by: str | None = None
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(),
            "status": str(self.status),
            "dataset_snapshot": self.dataset_snapshot,
            "runs": [r.to_dict() for r in self.runs],
            "decision": str(self.decision) if self.decision else None,
            "decision_reasons": self.decision_reasons,
            "test_observed": self.test_observed,
            "archived_note": self.archived_note,
            "superseded_by": self.superseded_by,
            "history": self.history,
        }


class ExperimentRegistry:
    """The ledger. Load, mutate through the methods below, save."""

    def __init__(self, path: pathlib.Path = REGISTRY_PATH) -> None:
        self.path = path
        self._entries: dict[str, RegistryEntry] = {}
        if path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for hid, data in raw.items():
            meta = data["metadata"]
            metadata = HypothesisMetadata(
                hypothesis_id=meta["hypothesis_id"],
                hypothesis_name=meta["hypothesis_name"],
                economic_mechanism=meta["economic_mechanism"],
                expected_direction=meta["expected_direction"],
                expected_holding_period=meta["expected_holding_period"],
                expected_market_behavior=meta["expected_market_behavior"],
                required_features=tuple(meta["required_features"]),
                known_failure_modes=tuple(meta["known_failure_modes"]),
                falsification_criteria=tuple(meta["falsification_criteria"]),
                researcher=meta["researcher"],
                data_dependencies=tuple(meta["data_dependencies"]),
                creation_timestamp=dt.datetime.fromisoformat(meta["creation_timestamp"]),
            )
            self._entries[hid] = RegistryEntry(
                metadata=metadata,
                status=ExperimentStatus(data["status"]),
                dataset_snapshot=data.get("dataset_snapshot"),
                runs=[RunRecord.from_dict(r) for r in data.get("runs", [])],
                decision=DecisionStatus(data["decision"]) if data.get("decision") else None,
                decision_reasons=data.get("decision_reasons", []),
                test_observed=data.get("test_observed", False),
                archived_note=data.get("archived_note", ""),
                superseded_by=data.get("superseded_by"),
                history=data.get("history", []),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {hid: e.to_dict() for hid, e in self._entries.items()}
        self.path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")

    def register(self, metadata: HypothesisMetadata) -> RegistryEntry:
        if metadata.hypothesis_id in self._entries:
            raise ValueError(
                f"Hypothesis {metadata.hypothesis_id!r} is already registered. "
                "A materially changed hypothesis must receive a new hypothesis "
                "id, not overwrite this one."
            )
        entry = RegistryEntry(metadata=metadata)
        self._entries[metadata.hypothesis_id] = entry
        self._log(entry, f"registered as {ExperimentStatus.PROPOSED}")
        return entry

    def get(self, hypothesis_id: str) -> RegistryEntry:
        try:
            return self._entries[hypothesis_id]
        except KeyError as exc:
            raise UnknownHypothesisError(hypothesis_id) from exc

    def list_all(self) -> list[RegistryEntry]:
        return sorted(self._entries.values(), key=lambda e: e.metadata.hypothesis_id)

    def transition(self, hypothesis_id: str, to: ExperimentStatus) -> RegistryEntry:
        entry = self.get(hypothesis_id)
        allowed = ALLOWED_TRANSITIONS.get(entry.status, frozenset())
        if to not in allowed:
            raise InvalidTransitionError(
                f"{hypothesis_id}: {entry.status} -> {to} is not a permitted "
                f"transition. Allowed from {entry.status}: {sorted(allowed) or 'none (terminal)'}."
            )
        self._log(entry, f"{entry.status} -> {to}")
        entry.status = to
        return entry

    def record_run(self, hypothesis_id: str, run: RunRecord) -> RegistryEntry:
        entry = self.get(hypothesis_id)
        entry.runs.append(run)
        return entry

    def mark_test_observed(self, hypothesis_id: str) -> RegistryEntry:
        """Once a hypothesis's TEST period has been looked at, it is
        permanently marked -- a second TEST run against the same test
        window is not a fresh out-of-sample result, it is data leakage
        through the researcher.
        """
        entry = self.get(hypothesis_id)
        if entry.test_observed:
            self._log(
                entry,
                "TEST observed again on an already-observed hypothesis -- "
                "forcing TEST_CONTAMINATED",
            )
            if entry.status not in (ExperimentStatus.FALSIFIED, ExperimentStatus.ARCHIVED):
                entry.status = ExperimentStatus.TEST_CONTAMINATED
            return entry
        entry.test_observed = True
        self._log(entry, "TEST observed for the first time")
        return entry

    def record_decision(
        self, hypothesis_id: str, decision: DecisionStatus, reasons: list[str]
    ) -> RegistryEntry:
        entry = self.get(hypothesis_id)
        if entry.test_observed and decision in (
            DecisionStatus.SUPPORTED, DecisionStatus.PROMISING_BUT_INSUFFICIENT
        ) and entry.status is ExperimentStatus.TEST_CONTAMINATED:
            raise ValueError(
                f"{hypothesis_id} is TEST_CONTAMINATED; it cannot be recorded "
                f"as {decision} -- a contaminated test result is not clean "
                "out-of-sample evidence, however good the numbers look."
            )
        entry.decision = decision
        entry.decision_reasons = list(reasons)
        self._log(entry, f"decision recorded: {decision} ({', '.join(reasons)})")
        return entry

    def archive_historical(
        self, metadata: HypothesisMetadata, *, status: ExperimentStatus, note: str
    ) -> RegistryEntry:
        """Ingest a hypothesis that was already decided outside this
        registry -- MA 20/50's V4.1 falsification, specifically -- without
        rerunning it. `status` must already be terminal-reachable."""
        if metadata.hypothesis_id in self._entries:
            raise ValueError(f"{metadata.hypothesis_id} is already registered.")
        entry = RegistryEntry(metadata=metadata, status=status, archived_note=note)
        self._entries[metadata.hypothesis_id] = entry
        self._log(entry, f"ingested as historical record, status={status}: {note}")
        return entry

    def _log(self, entry: RegistryEntry, message: str) -> None:
        entry.history.append({
            "at": dt.datetime.now(dt.UTC).isoformat(),
            "event": message,
        })
