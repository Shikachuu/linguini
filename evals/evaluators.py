import re
from dataclasses import dataclass
from typing import Literal

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from evals.chat import ChatInputs, ChatOutcome
from evals.summary import SummaryInputs
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
        saved = [c.args.get("recipe", {}) for c in ctx.output.tool_calls if c.name == "save_recipe"]
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


CHAT_EVALUATORS = (
    ToolCalled,
    ToolNotCalled,
    ToolOrder,
    NoInventoryWrites,
    InventoryIs,
    ReplyLanguage,
    SavedRecipeAllergens,
    ReplyMentions,
)
SUMMARY_EVALUATORS = (SummaryMentions, MaxChars)
