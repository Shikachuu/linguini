"""Run the prompt evals against the configured model: ``python -m evals [chat|summary|all]``."""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_core import to_json
from pydantic_evals import Dataset
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

from evals.chat import ChatInputs, ChatOutcome, chat_task
from evals.evaluators import CHAT_EVALUATORS, SUMMARY_EVALUATORS
from evals.summary import SummaryInputs, summary_task
from linguini.chat.agent import build_model, session_settings
from linguini.config import Settings

DATASETS = Path(__file__).parent / "datasets"
REPORTS = Path(__file__).parent / "reports"
DEFAULT_JUDGE = "glm-5.3"


def load_chat() -> Dataset[ChatInputs, ChatOutcome, None]:
    return Dataset[ChatInputs, ChatOutcome, None].from_file(
        DATASETS / "chat.yaml", custom_evaluator_types=CHAT_EVALUATORS
    )


def load_summary() -> Dataset[SummaryInputs, str, None]:
    return Dataset[SummaryInputs, str, None].from_file(
        DATASETS / "summary.yaml", custom_evaluator_types=SUMMARY_EVALUATORS
    )


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    parser.add_argument("dataset", nargs="?", choices=["chat", "summary", "all"], default="all")
    parser.add_argument("--model", help="model under test; defaults to LINGUINI_MODEL")
    parser.add_argument("--judge-model", default=os.environ.get("LINGUINI_EVAL_JUDGE_MODEL", DEFAULT_JUDGE))
    parser.add_argument("--repeat", type=positive, default=1, help="runs per case, to measure pass rates")
    parser.add_argument("--concurrency", type=positive, default=4)
    parser.add_argument("--case", action="append", default=[], help="only run cases with this name; repeatable")
    return parser.parse_args(argv)


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    settings = Settings(secret_key=SecretStr("eval"))
    model_name = args.model or settings.model
    if args.judge_model == model_name:
        print(f"warning: {model_name} is judging its own answers", file=sys.stderr)
    model = build_model(settings.model_copy(update={"model": model_name}))
    judge_session = session_settings(settings, f"linguini-eval-judge-{uuid.uuid7()}")
    set_default_judge_model(build_model(settings.model_copy(update={"model": args.judge_model}), judge_session))

    runs: list[tuple[Dataset[Any, Any, None], Any]] = []
    if args.dataset in {"chat", "all"}:
        runs.append((load_chat(), chat_task(model, settings)))
    if args.dataset in {"summary", "all"}:
        runs.append((load_summary(), summary_task(model, settings)))

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
        report = await dataset.evaluate(
            task, name=model_name, max_concurrency=args.concurrency, repeat=args.repeat, progress=False
        )
        report.print(include_input=False, include_output=False, include_durations=True, include_reasons=True)
        path = REPORTS / f"{stamp}-{dataset.name}-{model_name.replace('/', '_')}.json"
        path.write_bytes(to_json(report, indent=2))
        print(f"report: {path}")
        broken = report.failures or report.report_evaluator_failures or any(c.evaluator_failures for c in report.cases)
        failed = failed or bool(broken)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
