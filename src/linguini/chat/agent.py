"""The household agent: model wiring and instructions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pydantic import SecretStr
from pydantic_ai import Agent, ModelSettings, RunContext, UsageLimits
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import Model, ModelRequestContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.system_one import SystemOneModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.system_one import SystemOneProvider
from pydantic_ai.toolsets import AbstractToolset

from linguini.chat.deps import AgentDeps
from linguini.chat.guard import GuardConfig, guard_capabilities
from linguini.chat.prompts import CHAT_CONTEXT, CHAT_SPEC, REPLY_LANGUAGE, SUMMARY_SPEC
from linguini.chat.tools import inventory_toolset, recipe_toolset
from linguini.config import Settings

USAGE_LIMITS = UsageLimits(request_limit=25, tool_calls_limit=40)
RUN_TIMEOUT = 180.0


def build_model(settings: Settings, model_settings: ModelSettings | None = None) -> Model:
    """Construct the chat model for the configured OpenAI-compatible server.

    Returns:
        A chat-completions model.
    """
    provider = OpenAIProvider(
        base_url=str(settings.openai_base_url) if settings.openai_base_url else None,
        api_key=settings.openai_api_key.get_secret_value(),
    )
    profile = OpenAIModelProfile(
        openai_supports_strict_tool_definition=settings.model_profile.get("strict_tools", True),
        supports_json_schema_output=settings.model_profile.get("json_schema_output", True),
    )
    return OpenAIChatModel(settings.model, provider=provider, profile=profile, settings=model_settings)


def decisions_key(settings: Settings) -> SecretStr | None:
    """The key for the decisions server: its own, or the chat key when both URLs point at the same host.

    Returns:
        The key, or None when using the chat key would send it to another host.
    """
    if settings.decisions_api_key is not None and settings.decisions_api_key.get_secret_value():
        return settings.decisions_api_key
    if settings.openai_base_url is not None and settings.openai_base_url.host == settings.decisions_base_url.host:
        return settings.openai_api_key
    return None


def build_decision_model(settings: Settings, name: str) -> Model:
    """Construct a decision model served over the System One API, such as the topic gate's.

    Returns:
        A decision model.

    Raises:
        ValueError: when no key for the decisions server is configured.
    """
    key = decisions_key(settings)
    if key is None:
        raise ValueError(
            f"{settings.decisions_base_url.host} differs from the chat server; set LINGUINI_DECISIONS_API_KEY"
        )
    provider = SystemOneProvider(base_url=str(settings.decisions_base_url), api_key=key.get_secret_value())
    return SystemOneModel(name, provider=provider)


def session_settings(settings: Settings, session_id: str) -> ModelSettings | None:
    """Per-conversation request headers for servers that route or cache by session.

    Returns:
        Settings adding the session header, or None when no header is configured.
    """
    if settings.session_header is None:
        return None
    return ModelSettings(extra_headers={settings.session_header: session_id})


def chat_context(ctx: RunContext[AgentDeps]) -> str:
    """Render the per-run facts appended to the static chat instructions.

    Returns:
        The rendered context block.
    """
    return CHAT_CONTEXT.render(ctx.deps.prompt_context())


@dataclass
class ReplyLanguageReminder(AbstractCapability[AgentDeps]):
    """Repeat the reply-language rule right after the newest message of every model request."""

    async def before_model_request(
        self, ctx: RunContext[AgentDeps], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        """Append the reminder to the last request sent to the model.

        Returns:
            The request context with the reminder added.
        """
        messages = list(request_context.messages)
        if messages and isinstance(messages[-1], ModelRequest):
            messages[-1] = replace(messages[-1], parts=[*messages[-1].parts, UserPromptPart(REPLY_LANGUAGE)])
        return replace(request_context, messages=messages)


UNSET_CANARY = "lgn-unconfigured"


def build_agent(
    model: Model, guard: GuardConfig | None = None, capabilities: Sequence[AbstractCapability[AgentDeps]] = ()
) -> Agent[AgentDeps, str]:
    """Create the household agent bound to ``model``.

    Without ``guard`` the topic gate is off; redaction, tool screening and the output buffer always run.

    Returns:
        The agent, with the inventory and recipe toolsets attached.
    """
    agent = Agent.from_file(
        CHAT_SPEC,
        deps_type=AgentDeps,
        model=model,
        instructions=chat_context,
        toolsets=[inventory_toolset, recipe_toolset],
        capabilities=[
            ReplyLanguageReminder(),
            *guard_capabilities(guard or GuardConfig(UNSET_CANARY)),
            *capabilities,
        ],
    )

    @agent.toolset(per_run_step=False, id="kifli-mcp")
    def kifli_tools(ctx: RunContext[AgentDeps]) -> AbstractToolset[AgentDeps] | None:
        d = ctx.deps
        if d.kifli_server is not None:
            return MCPToolset(d.kifli_server, id="kifli", tool_error_behavior="failed").prefixed("kifli")
        if d.kifli is None:
            return None
        return MCPToolset(
            d.kifli.mcp_url, id="kifli", auth=d.kifli.access_token, tool_error_behavior="failed"
        ).prefixed("kifli")

    return agent


def build_summarizer(model: Model, capabilities: Sequence[AbstractCapability[None]] = ()) -> Agent[None, str]:
    """Create the agent that condenses old thread history.

    Returns:
        A plain text agent.
    """
    return Agent.from_file(SUMMARY_SPEC, deps_type=type(None), model=model, capabilities=list(capabilities))
