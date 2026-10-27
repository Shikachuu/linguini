"""Run the prompt evals against the configured model: ``python -m evals [chat|summary|guardrails|topic_gate|all]``."""

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_core import to_json
from pydantic_evals import Dataset

from evals.chat import ChatInputs, ChatOutcome, chat_task
from evals.evaluators import CHAT_EVALUATORS, SUMMARY_EVALUATORS, TOPIC_EVALUATORS, set_judge_model
from evals.summary import SummaryInputs, summary_task
from evals.topic_gate import GateCase, TopicInputs, TopicOutcome, topic_task
from linguini.chat.agent import build_decision_model, build_model
from linguini.config import Settings

DATASETS = Path(__file__).parent / "datasets"
REPORTS = Path(__file__).parent / "reports"
DEFAULT_JUDGE = "typesafe/jev-1.14"
DATASET_NAMES = ["chat", "summary", "guardrails", "topic_gate"]


def load_chat() -> Dataset[ChatInputs, ChatOutcome, None]:
    return Dataset[ChatInputs, ChatOutcome, None].from_file(
        DATASETS / "chat.yaml", custom_evaluator_types=CHAT_EVALUATORS
    )


def load_summary() -> Dataset[SummaryInputs, str, None]:
    return Dataset[SummaryInputs, str, None].from_file(
        DATASETS / "summary.yaml", custom_evaluator_types=SUMMARY_EVALUATORS
    )


def load_guardrails() -> Dataset[ChatInputs, ChatOutcome, None]:
    return Dataset[ChatInputs, ChatOutcome, None].from_file(
        DATASETS / "guardrails.yaml", custom_evaluator_types=CHAT_EVALUATORS
    )


def load_topic_gate() -> Dataset[TopicInputs, TopicOutcome, GateCase]:
    return Dataset[TopicInputs, TopicOutcome, GateCase].from_file(
        DATASETS / "topic_gate.yaml", custom_evaluator_types=TOPIC_EVALUATORS
    )


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    parser.add_argument("dataset", nargs="?", choices=[*DATASET_NAMES, "all"], default="all")
    parser.add_argument("--model", help="model under test; defaults to LINGUINI_MODEL")
    parser.add_argument(
        "--judge-model",
        default=os.environ.get("LINGUINI_EVAL_JUDGE_MODEL", DEFAULT_JUDGE),
        help="decision model that grades replies, served over the System One API",
    )
    parser.add_argument("--guard-model", help="topic gate decision model; defaults to LINGUINI_GUARD_MODEL")
    parser.add_argument("--repeat", type=positive, default=1, help="runs per case, to measure pass rates")
    parser.add_argument("--concurrency", type=positive, default=4)
    parser.add_argument("--case", action="append", default=[], help="only run cases with this name; repeatable")
    return parser.parse_args(argv)


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    settings = Settings(secret_key=SecretStr("eval"))
    model_name = args.model or settings.model
    guard_name = args.guard_model or settings.guard_model
    if args.judge_model == guard_name:
        print(f"note: {guard_name} both gates and grades; the gate is graded by deterministic checks", file=sys.stderr)
    model = build_model(settings.model_copy(update={"model": model_name}))
    try:
        guard_model = build_decision_model(settings, guard_name) if guard_name else None
        set_judge_model(build_decision_model(settings, args.judge_model))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2

    selected = DATASET_NAMES if args.dataset == "all" else [args.dataset]
    if guard_model is None and {"guardrails", "topic_gate"} & set(selected):
        if args.dataset != "all":
            print(f"the {args.dataset} dataset needs a guard model", file=sys.stderr)
            return 2
        print("note: no guard model, skipping guardrails and topic_gate", file=sys.stderr)
        selected = ["chat", "summary"]
    runs: list[tuple[Dataset[Any, Any, Any], Any]] = []
    if "chat" in selected:
        runs.append((load_chat(), chat_task(model, settings, guard_model)))
    if "summary" in selected:
        runs.append((load_summary(), summary_task(model, settings)))
    if "guardrails" in selected and guard_model is not None:
        runs.append((load_guardrails(), chat_task(model, settings, guard_model)))
    if "topic_gate" in selected and guard_model is not None:
        runs.append((load_topic_gate(), topic_task(guard_model)))

    unknown = set(args.case) - {c.name for dataset, _ in runs for c in dataset.cases}
    if unknown:
        print(f"unknown case: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if args.case:
        for dataset, _ in runs:
            dataset.cases = [c for c in dataset.cases if c.name in args.case]
        runs = [(dataset, task) for dataset, task in runs if dataset.cases]

    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    failed = False
    for dataset, task in runs:
        name = guard_name if dataset.name == "topic_gate" else model_name
        report = await dataset.evaluate(
            task, name=name, max_concurrency=args.concurrency, repeat=args.repeat, progress=False
        )
        report.print(include_input=False, include_output=False, include_durations=True, include_reasons=True)
        path = REPORTS / f"{stamp}-{dataset.name}-{name.replace('/', '_')}.json"
        path.write_bytes(to_json(report, indent=2))
        print(f"report: {path}")
        broken = report.failures or report.report_evaluator_failures or any(c.evaluator_failures for c in report.cases)
        failed = failed or bool(broken)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
