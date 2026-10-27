import pytest
from chat_models import streamed
from pydantic import SecretStr
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_evals import Case, Dataset

from evals.__main__ import load_chat, load_summary
from evals.chat import ChatInputs, ChatOutcome, Stock, StockLevel, ToolCall, Turn, chat_task
from evals.evaluators import (
    InventoryIs,
    MaxChars,
    NoInventoryWrites,
    ReplyLanguage,
    ReplyMentions,
    SavedRecipeAllergens,
    SummaryMentions,
    ToolCalled,
    ToolNotCalled,
    ToolOrder,
    language_of,
)
from evals.summary import Line, SummaryInputs, summary_task
from linguini.chat.prompts import REPLY_LANGUAGE
from linguini.config import Settings
from linguini.recipes.service import Ingredient, RecipeData

pytestmark = pytest.mark.anyio

SETTINGS = Settings(secret_key=SecretStr("eval"))


def test_datasets_load_with_their_evaluators() -> None:
    assert load_chat().cases
    assert load_summary().cases


def pantry_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    last = messages[-1]
    assert isinstance(last, ModelRequest)
    prompt = next((p.content for p in last.parts if isinstance(p, UserPromptPart)), None)
    if prompt == "add":
        args = {"items": [{"name": "tej", "quantity": 2, "unit": "l"}]}
        return ModelResponse(parts=[ToolCallPart("add_items", args)])
    if prompt == "undo":
        return ModelResponse(parts=[ToolCallPart("undo", {})])
    return ModelResponse(parts=[TextPart("Kész, visszavonható.")])


async def test_chat_task_runs_each_message_as_its_own_turn() -> None:
    task = chat_task(streamed(pantry_model), SETTINGS)
    outcome = await task(ChatInputs(messages=["add", "undo"], inventory=[Stock(name="tej", quantity=1, unit="l")]))
    assert [c.name for c in outcome.tool_calls] == ["add_items", "undo"]
    assert outcome.inventory == [StockLevel(name="tej", quantity_base=1000, unit="l")]
    assert outcome.replies == ["Kész, visszavonható.", "Kész, visszavonható."]
    assert outcome.reply == "Kész, visszavonható."


async def test_chat_task_seeds_history_recipes_and_expiry() -> None:
    seen: list[ModelRequest] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        assert isinstance(last, ModelRequest)
        seen.append(last)
        if any(isinstance(p, UserPromptPart) and p.content != REPLY_LANGUAGE for p in last.parts):
            return ModelResponse(parts=[ToolCallPart("list_recipes", {})])
        returned = next(p for p in last.parts if isinstance(p, ToolReturnPart))
        return ModelResponse(parts=[TextPart(str(returned.content))])

    inputs = ChatInputs(
        messages=["what can I cook?"],
        history=[Turn(role="user", text="no gluten"), Turn(role="assistant", text="noted")],
        inventory=[Stock(name="joghurt", quantity=2, unit="pcs", expires_in_days=1, notes="opened")],
        recipes=[RecipeData(title="Lecsó", ingredients=[Ingredient(name="paprika", quantity=1, unit="kg")])],
    )
    outcome = await chat_task(streamed(model), SETTINGS)(inputs)
    assert "- joghurt: 2 pcs (expires in" in str(seen[0].instructions)
    assert "Lecsó" in outcome.reply


async def test_chat_task_rejects_a_case_with_invalid_inventory() -> None:
    inputs = ChatInputs(messages=["hi"], inventory=[Stock(name="tej", quantity=0, unit="l")])
    with pytest.raises(ValueError, match="case inventory rejected"):
        await chat_task(streamed(pantry_model), SETTINGS)(inputs)


async def test_summary_task_sends_rendered_conversation() -> None:
    prompts: list[str] = []

    def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        assert isinstance(last, ModelRequest)
        prompts.extend(str(p.content) for p in last.parts if isinstance(p, UserPromptPart))
        return ModelResponse(parts=[TextPart("SUMMARY")])

    inputs = SummaryInputs(
        previous="old",
        conversation=[
            Line(role="user", text="hi"),
            Line(role="call", tool="list_items"),
            Line(role="result", tool="list_items", text="[]"),
            Line(role="assistant", text="empty"),
        ],
    )
    assert await summary_task(FunctionModel(capture), SETTINGS)(inputs) == "SUMMARY"
    assert prompts == [
        "Earlier summary:\nold\n\nConversation:\n<conversation>\n"
        "User: hi\nAssistant called list_items({})\nTool list_items returned: []\nAssistant: empty\n</conversation>"
    ]


OUTCOME = ChatOutcome(
    reply="Hozzáadtam: 50 dkg Trappista sajt.",
    replies=["Megvan, ez is kész.", "Hozzáadtam: 50 dkg Trappista sajt."],
    tool_calls=[
        ToolCall(name="list_recipes", args={}),
        ToolCall(name="add_items", args={}),
        ToolCall(name="save_recipe", args={"recipe": {"allergens": ["Tejtermék"]}}),
    ],
    inventory=[StockLevel(name="Trappista sajt", quantity_base=500, unit="dkg")],
)


@pytest.mark.parametrize(
    ("evaluator", "passed"),
    [
        (ToolCalled("add_items"), True),
        (ToolCalled("undo"), False),
        (ToolNotCalled("remove_item"), True),
        (ToolNotCalled("add_items"), False),
        (ToolOrder(["list_recipes", "save_recipe"]), True),
        (ToolOrder(["save_recipe", "list_recipes"]), False),
        (NoInventoryWrites(), False),
        (InventoryIs("trappista sajt", 0.5, "kg"), True),
        (InventoryIs("trappista sajt", 0.5, "l"), False),
        (InventoryIs("tej", 1, "l"), False),
        (SavedRecipeAllergens(["tej"]), True),
        (SavedRecipeAllergens(["gluten"]), False),
        (ReplyMentions(["trappista", "gouda"]), True),
        (ReplyMentions(["gouda"]), False),
        (ReplyLanguage("hu"), True),
        (ReplyLanguage("en"), False),
    ],
)
async def test_chat_evaluators(evaluator, passed: bool) -> None:
    def fixed(inputs: ChatInputs) -> ChatOutcome:
        return OUTCOME

    dataset = Dataset[ChatInputs, ChatOutcome, None](
        name="t", cases=[Case(inputs=ChatInputs(messages=[]))], evaluators=[evaluator]
    )
    report = await dataset.evaluate(fixed, progress=False)
    assert [a.value for a in report.cases[0].assertions.values()] == [passed]


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("I added the tej and the trappista, you can undo it.", "en"),
        ("Felírtam a tejet és a trappistát, visszavonható.", "hu"),
        ("I added a tomato.", "en"),
        ("az the", None),
        ("tej, trappista", None),
        ("", None),
    ],
)
def test_language_of_ignores_item_names(text: str, language: str | None) -> None:
    assert language_of(text) == language


@pytest.mark.parametrize(
    ("replies", "passed"),
    [
        (["I added it.", "Done, you can undo it."], True),
        (["I added it.", "Felírtam, visszavonható."], False),
        (["tej"], False),
        ([], False),
    ],
)
def test_reply_language_checks_every_turn(replies: list[str], passed: bool) -> None:
    def fixed(inputs: ChatInputs) -> ChatOutcome:
        return ChatOutcome(reply="", replies=replies, tool_calls=[], inventory=[])

    dataset = Dataset[ChatInputs, ChatOutcome, None](
        name="t", cases=[Case(inputs=ChatInputs(messages=[]))], evaluators=[ReplyLanguage("en")]
    )
    report = dataset.evaluate_sync(fixed, progress=False)
    assert [a.value for a in report.cases[0].assertions.values()] == [passed]


@pytest.mark.parametrize(
    ("evaluator", "passed"),
    [
        (SummaryMentions(["bela", "Glutén"]), True),
        (SummaryMentions(["bela", "laktóz"]), False),
        (MaxChars(40), True),
        (MaxChars(10), False),
    ],
)
async def test_summary_evaluators(evaluator, passed: bool) -> None:
    def fixed(inputs: SummaryInputs) -> str:
        return "Béla gluténmentes."

    dataset = Dataset[SummaryInputs, str, None](
        name="t", cases=[Case(inputs=SummaryInputs(conversation=[]))], evaluators=[evaluator]
    )
    report = await dataset.evaluate(fixed, progress=False)
    assert [a.value for a in report.cases[0].assertions.values()] == [passed]
