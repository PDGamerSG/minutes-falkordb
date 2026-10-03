"""Agent registry: the five agents, their ids, capabilities and task kinds."""

from __future__ import annotations

from typing import Any

from .answer_agent import AnswerAgent
from .base import AgentResult, BaseAgent
from .fact_agent import FactAgent
from .followup_agent import FollowUpAgent
from .scheduler_agent import SchedulerAgent
from .standup_agent import StandupAgent

AGENT_CLASSES: list[type[BaseAgent]] = [FactAgent, FollowUpAgent, SchedulerAgent, StandupAgent, AnswerAgent]

__all__ = ["AGENT_CLASSES", "AgentResult", "AnswerAgent", "BaseAgent", "FactAgent", "FollowUpAgent", "SchedulerAgent", "StandupAgent", "build_agents"]


def build_agents(tenant: str, hive: Any, llm: Any, embedder: Any, settings: Any) -> dict[str, BaseAgent]:
    """Instantiate every agent for one tenant, keyed by agent id."""
    return {cls.agent_id: cls(tenant, hive, llm, embedder, settings) for cls in AGENT_CLASSES}
