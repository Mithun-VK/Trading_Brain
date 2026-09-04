"""V5 — the research CLI.

    python -m experiments.alpha.cli list
    python -m experiments.alpha.cli show <hypothesis_id>
    python -m experiments.alpha.cli run <hypothesis_id> [--unlock-test] [--trials N]
    python -m experiments.alpha.cli report <run_id>
    python -m experiments.alpha.cli compare <run_a> <run_b>

Follows the same `argparse` subcommand convention as
`apps/worker/main.py` (`python -m <package>.<module> <verb> [args]`)
rather than introducing a second CLI framework.

This module never runs on import and never runs automatically -- it is only
ever invoked as `python -m experiments.alpha.cli`, by a human, at the
command line.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from experiments.alpha.registry import ExperimentRegistry, UnknownHypothesisError

MANIFEST_DIR = pathlib.Path("experiments/.manifests")
REPORT_ROOT = pathlib.Path("docs/research")


def cmd_list(args: argparse.Namespace) -> int:
    registry = ExperimentRegistry()
    entries = registry.list_all()
    if not entries:
        print("No hypotheses registered.")
        return 0
    print(f"{'hypothesis_id':<24}{'status':<24}{'decision':<10}{'runs':>6}")
    for entry in entries:
        decision = str(entry.decision) if entry.decision else "-"
        print(f"{entry.metadata.hypothesis_id:<24}{str(entry.status):<24}"
              f"{decision:<10}{len(entry.runs):>6}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    registry = ExperimentRegistry()
    try:
        entry = registry.get(args.hypothesis_id)
    except UnknownHypothesisError:
        print(f"Unknown hypothesis: {args.hypothesis_id}", file=sys.stderr)
        return 1
    print(json.dumps(entry.to_dict(), indent=1, default=str))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    matches = list(pathlib.Path(REPORT_ROOT).glob(f"*/{args.run_id}.md"))
    if not matches:
        print(f"No report found for run {args.run_id}.", file=sys.stderr)
        return 1
    print(matches[0].read_text(encoding="utf-8"))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    def _load(run_id: str) -> dict:
        path = MANIFEST_DIR / f"{run_id}.json"
        if not path.exists():
            print(f"No manifest for run {run_id}.", file=sys.stderr)
            raise SystemExit(1)
        return json.loads(path.read_text(encoding="utf-8"))

    a, b = _load(args.run_a), _load(args.run_b)
    print(f"{'field':<28}{args.run_a[:24]:<26}{args.run_b[:24]:<26}")
    for key in ("hypothesis_id", "hypothesis_signature", "git_commit",
                "dataset_snapshot", "random_seed", "test_contaminated"):
        print(f"{key:<28}{str(a.get(key)):<26}{str(b.get(key)):<26}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    print(
        "Interactive `run` requires a hypothesis-specific data-loading and "
        "config-construction script (see experiments/alpha/candidates/ and "
        "the reference runner in tests/experiments/alpha/test_evaluator.py "
        "for the pattern) -- this CLI does not itself decide which universe, "
        "cost model, or period split to use for an arbitrary hypothesis id.\n"
        f"Requested: {args.hypothesis_id} (unlock_test={args.unlock_test}, "
        f"trials={args.trials})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="experiments.alpha.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all registered hypotheses").set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one hypothesis's registry entry")
    p_show.add_argument("hypothesis_id")
    p_show.set_defaults(func=cmd_show)

    p_run = sub.add_parser("run", help="run the standardized protocol against a hypothesis")
    p_run.add_argument("hypothesis_id")
    p_run.add_argument("--unlock-test", action="store_true", default=False)
    p_run.add_argument("--trials", type=int, default=5000)
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="print a run's markdown report")
    p_report.add_argument("run_id")
    p_report.set_defaults(func=cmd_report)

    p_compare = sub.add_parser("compare", help="compare two runs' manifests")
    p_compare.add_argument("run_a")
    p_compare.add_argument("run_b")
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
