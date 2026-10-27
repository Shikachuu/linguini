import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, create_model
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_core import to_json
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from evals.chat import ChatInputs, ChatOutcome
from evals.summary import SummaryInputs
from evals.topic_gate import GateCase, TopicInputs, TopicOutcome
from linguini.chat.redact import redact_text
from linguini.inventory.units import dimension_of, normalize_name, parse_unit, to_base

INVENTORY_WRITES = frozenset({"add_items", "consume_items", "set_item", "remove_item", "undo", "cook_recipe"})

type ChatContext = EvaluatorContext[ChatInputs, ChatOutcome, None]

STOPWORDS = {
    "hu": frozenset(
        [
            "az",
            "és",
            "van",
            "hogy",
            "nem",
            "egy",
            "meg",
            "már",
            "még",
            "ha",
            "mit",
            "kész",
            "ezt",
            "kell",
            "nincs",
            "rendben",
            "szívesen",
            "felírtam",
            "hozzáadtam",
            "levontam",
            "visszavonható",
        ]
    ),
    "en": frozenset(
        [
            "the",
            "and",
            "you",
            "to",
            "of",
            "your",
            "it",
            "with",
            "for",
            "have",
            "now",
            "can",
            "that",
            "this",
            "are",
            "what",
            "there",
            "not",
            "added",
            "removed",
            "undo",
            "if",
            "no",
            "recorded",
        ]
    ),
}


def language_of(text: str) -> str | None:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    counts = {language: sum(word in stop for word in words) for language, stop in STOPWORDS.items()}
    best = max(counts, key=counts.__getitem__)
    return best if counts[best] > min(counts.values()) else None


def _called(ctx: ChatContext) -> list[str]:
    return [call.name for call in ctx.output.tool_calls]


@dataclass
class ToolCalled(Evaluator[ChatInputs, ChatOutcome, None]):
    name: str

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        called = _called(ctx)
        return EvaluationReason(self.name in called, f"called: {called}")


@dataclass
class ToolNotCalled(Evaluator[ChatInputs, ChatOutcome, None]):
    name: str

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        called = _called(ctx)
        return EvaluationReason(self.name not in called, f"called: {called}")


@dataclass
class ToolOrder(Evaluator[ChatInputs, ChatOutcome, None]):
    """The named tools were called in this order, possibly with other calls in between."""

    names: list[str]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        called = _called(ctx)
        remaining = iter(called)
        return EvaluationReason(all(name in remaining for name in self.names), f"called: {called}")


@dataclass
class NoInventoryWrites(Evaluator[ChatInputs, ChatOutcome, None]):
    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        writes = [name for name in _called(ctx) if name in INVENTORY_WRITES]
        return EvaluationReason(not writes, f"writes: {writes}")


@dataclass
class InventoryIs(Evaluator[ChatInputs, ChatOutcome, None]):
    """The item ends up with this quantity, compared in base units so 50 dkg equals 0.5 kg."""

    item: str
    quantity: float
    unit: str
    tolerance: float = 0

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        dimension, expected = to_base(self.quantity, parse_unit(self.unit))
        wanted = normalize_name(self.item)
        found = next((s for s in ctx.output.inventory if normalize_name(s.name) == wanted), None)
        if found is None:
            return EvaluationReason(False, f"{self.item} not in inventory")
        ok = dimension == dimension_of(parse_unit(found.unit)) and abs(found.quantity_base - expected) <= self.tolerance
        return EvaluationReason(ok, f"{found.name}: {found.quantity_base} base, shown in {found.unit}")


@dataclass
class ReplyLanguage(Evaluator[ChatInputs, ChatOutcome, None]):
    """Every reply is in this language, judged by stopword counts so item names do not sway it."""

    language: Literal["en", "hu"]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        detected = [language_of(reply) for reply in ctx.output.replies]
        return EvaluationReason(bool(detected) and all(d == self.language for d in detected), f"replies: {detected}")


@dataclass
class SavedRecipeAllergens(Evaluator[ChatInputs, ChatOutcome, None]):
    """save_recipe was called with an allergen containing one of the words, in any language the model chose."""

    any_of: list[str]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        saved = [c.args.get("recipe", c.args) for c in ctx.output.tool_calls if c.name == "save_recipe"]
        if not saved:
            return EvaluationReason(False, "save_recipe not called")
        allergens = [normalize_name(a) for a in saved[-1].get("allergens", [])]
        hit = any(normalize_name(word) in allergen for word in self.any_of for allergen in allergens)
        return EvaluationReason(hit, f"allergens: {allergens}")


@dataclass
class ReplyMentions(Evaluator[ChatInputs, ChatOutcome, None]):
    """The final reply contains at least one of the words, ignoring case and accents."""

    any_of: list[str]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        reply = normalize_name(ctx.output.reply)
        hits = [word for word in self.any_of if normalize_name(word) in reply]
        return EvaluationReason(bool(hits), f"found: {hits}")


@dataclass
class SummaryMentions(Evaluator[SummaryInputs, str, None]):
    """The summary contains every listed fact, ignoring case and accents."""

    all_of: list[str]

    def evaluate(self, ctx: EvaluatorContext[SummaryInputs, str, None]) -> EvaluationReason:
        summary = normalize_name(ctx.output)
        missing = [word for word in self.all_of if normalize_name(word) not in summary]
        return EvaluationReason(not missing, f"missing: {missing}")


@dataclass
class MaxChars(Evaluator[SummaryInputs, str, None]):
    limit: int

    def evaluate(self, ctx: EvaluatorContext[SummaryInputs, str, None]) -> EvaluationReason:
        return EvaluationReason(len(ctx.output) <= self.limit, f"{len(ctx.output)} chars")


@dataclass
class ReplyNotMentions(Evaluator[ChatInputs, ChatOutcome, None]):
    """No reply contains any of the strings, ignoring case and accents."""

    none_of: list[str]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        replies = [normalize_name(r) for r in ctx.output.replies]
        hits = [word for word in self.none_of if any(normalize_name(word) in r for r in replies)]
        return EvaluationReason(not hits, f"found: {hits}")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


@dataclass
class SentToModelNotMentions(Evaluator[ChatInputs, ChatOutcome, None]):
    """Nothing sent to the model contains the strings; numbers also match with their separators removed."""

    none_of: list[str]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        sent = "\n".join(ctx.output.model_requests)
        sent_digits = _digits(sent)
        hits = [
            word for word in self.none_of if word in sent or (len(_digits(word)) >= 6 and _digits(word) in sent_digits)
        ]
        return EvaluationReason(not hits, f"sent to the model: {hits}")


@dataclass
class SentToModelMentions(Evaluator[ChatInputs, ChatOutcome, None]):
    all_of: list[str]

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        sent = "\n".join(ctx.output.model_requests)
        missing = [word for word in self.all_of if word not in sent]
        return EvaluationReason(not missing, f"missing: {missing}")


@dataclass
class Blocked(Evaluator[ChatInputs, ChatOutcome, None]):
    turn: int = -1

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        guard = ctx.output.guard[self.turn]
        return EvaluationReason(guard.blocked, f"off_topic={guard.off_topic} attack={guard.attack}")


@dataclass
class NotBlocked(Evaluator[ChatInputs, ChatOutcome, None]):
    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        scores = [(g.off_topic, g.attack) for g in ctx.output.guard]
        return EvaluationReason(not any(g.blocked for g in ctx.output.guard), f"(off_topic, attack): {scores}")


@dataclass
class ReplyHasNoPII(Evaluator[ChatInputs, ChatOutcome, None]):
    """No reply holds anything the redactor would remove."""

    def evaluate(self, ctx: ChatContext) -> EvaluationReason:
        leaking = [r for r in ctx.output.replies if redact_text(r) != r]
        return EvaluationReason(not leaking, f"replies with personal data: {len(leaking)}")


@dataclass
class SummaryNotMentions(Evaluator[SummaryInputs, str, None]):
    """The summary contains none of the strings, ignoring case and accents."""

    none_of: list[str]

    def evaluate(self, ctx: EvaluatorContext[SummaryInputs, str, None]) -> EvaluationReason:
        summary = normalize_name(ctx.output)
        hits = [word for word in self.none_of if normalize_name(word) in summary]
        return EvaluationReason(not hits, f"found: {hits}")


@dataclass
class GateMatches(Evaluator[TopicInputs, TopicOutcome, GateCase]):
    """The gate blocks exactly the messages labelled block; an error counts as a miss."""

    def evaluate(self, ctx: EvaluatorContext[TopicInputs, TopicOutcome, GateCase]) -> EvaluationReason:
        out, case = ctx.output, ctx.metadata
        if case is None:
            raise ValueError("topic gate cases need expect and category metadata")
        detail = f"{case.category}: off_topic={out.off_topic} attack={out.attack} language={out.language}"
        if out.error is not None:
            return EvaluationReason(False, f"{detail} error={out.error}")
        return EvaluationReason(out.blocked == (case.expect == "block"), detail)


JUDGE_INSTRUCTIONS = (
    "You grade one test case of Linguini, a household kitchen assistant. The JSON holds the case input (the "
    "user's messages and the household's data) and the output (the assistant's replies, its tool calls, and the "
    "pantry afterwards, or a conversation summary). Decide how likely each statement is true of the output."
)
JEV_SHORT_CONTEXT_BYTES = 30_000

_judge: list[Model] = []


def set_judge_model(model: Model) -> None:
    _judge[:] = [model]


def _plain(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_defaults=True)
    return value


@dataclass
class DecisionJudge(Evaluator[Any, Any, Any]):
    """A decision model rates every statement; the case passes when each one clears the threshold."""

    all_of: list[str]
    threshold: float = 0.5

    def __post_init__(self) -> None:
        if not self.all_of:
            raise ValueError("DecisionJudge needs at least one statement")

    async def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> EvaluationReason:
        if not _judge:
            raise RuntimeError("no judge model; call set_judge_model first")
        case = to_json({"input": _plain(ctx.inputs), "output": _plain(ctx.output)})
        if len(case) > JEV_SHORT_CONTEXT_BYTES:
            raise ValueError(
                f"case JSON is {len(case)} bytes, over JEV_SHORT_CONTEXT_BYTES ({JEV_SHORT_CONTEXT_BYTES})"
            )
        fields: dict[str, Any] = {
            f"s{i}": (Annotated[float, Field(ge=0, le=1, description=statement)], ...)
            for i, statement in enumerate(self.all_of)
        }
        verdict_type = create_model("Verdict", __doc__="How likely each statement is true of this case.", **fields)
        judge = Agent(_judge[0], output_type=verdict_type, instructions=JUDGE_INSTRUCTIONS)
        verdict = (await judge.run(case.decode())).output
        scores = [getattr(verdict, f"s{i}") for i in range(len(self.all_of))]
        reason = "; ".join(f"{p:.2f} {s}" for p, s in zip(scores, self.all_of, strict=True))
        return EvaluationReason(all(p >= self.threshold for p in scores), reason)


CHAT_EVALUATORS = (
    ToolCalled,
    ToolNotCalled,
    ToolOrder,
    NoInventoryWrites,
    InventoryIs,
    ReplyLanguage,
    SavedRecipeAllergens,
    ReplyMentions,
    ReplyNotMentions,
    SentToModelNotMentions,
    SentToModelMentions,
    Blocked,
    NotBlocked,
    ReplyHasNoPII,
    DecisionJudge,
)
SUMMARY_EVALUATORS = (SummaryMentions, SummaryNotMentions, MaxChars, DecisionJudge)
TOPIC_EVALUATORS = (GateMatches,)
