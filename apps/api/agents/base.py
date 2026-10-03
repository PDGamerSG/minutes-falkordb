"""Agent base: system prompt + tool schemas -> model -> validated tool call -> execute -> repeat.

``max_steps`` defaults to 6; invalid JSON or tool args get one retry inside the LLM client, after
which the run fails loudly (the worker marks the task ``failed`` with the reason).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .tools import ToolSet, build_tools

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Read ``agents/prompts/<name>.md``."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


@dataclass
class AgentResult:
    """What the worker needs to close a task."""

    final: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    failed: bool = False
    reason: str | None = None
    artifact: dict[str, Any] | None = None
    handed_off: bool = False
    used_skill_id: str | None = None
    model: str = ""
    latency_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "final": self.final,
            "steps": self.steps,
            "failed": self.failed,
            "reason": self.reason,
            "artifact": self.artifact,
            "handed_off": self.handed_off,
            "used_skill_id": self.used_skill_id,
            "model": self.model,
            "latency_ms": self.latency_ms,
        }


class BaseAgent:
    """One agent identity bound to a tenant. Subclasses set ``agent_id``, ``capabilities``,
    ``handles`` (task kinds), ``tool_names`` and ``prompt_name``."""

    agent_id = "base_agent"
    name = "BaseAgent"
    capabilities: list[str] = []
    handles: tuple[str, ...] = ()
    tool_names: list[str] = ["finish"]
    prompt_name = "base"
    max_steps = 6

    def __init__(self, tenant: str, hive: Any, llm: Any, embedder: Any, settings: Any) -> None:
        self.tenant = tenant
        self.hive = hive
        self.llm = llm
        self.embedder = embedder
        self.settings = settings

    # -- hooks --------------------------------------------------------------------------------
    def system_prompt(self, task: dict[str, Any]) -> str:
        return load_prompt(self.prompt_name)

    def task_message(self, task: dict[str, Any]) -> str:
        """The user turn: a machine-readable header (used by the fake policy) plus the task JSON."""
        payload = task.get("payload") or {}
        lines = [f"TASK_KIND: {task.get('kind')}", f"TASK_ID: {task.get('id')}", f"TENANT: {self.tenant}"]
        for key, value in payload.items():
            if isinstance(value, (str, int, float)) and len(str(value)) < 200:
                lines.append(f"{str(key).upper()}: {value}")
        lines.append("")
        lines.append("Task payload (JSON):")
        lines.append(json.dumps(payload, default=str, indent=2)[:4000])
        if task.get("about"):
            lines.append(f"About node ids: {task['about']}")
        lines.append("")
        lines.append(self.task_instructions(task))
        return "\n".join(lines)

    def task_instructions(self, task: dict[str, Any]) -> str:
        return "Work through the task with the tools, then call finish (or hand_off)."

    def context_for(self, task: dict[str, Any]) -> str:
        """Extra context prepended to the task message (facts the agent will need)."""
        return ""

    def tools_for(self, task: dict[str, Any]) -> ToolSet:
        return build_tools(self, task, self.tool_names)

    # -- run ----------------------------------------------------------------------------------
    def run(self, task: dict[str, Any]) -> AgentResult:
        """Deterministic subclasses override this; the default drives the LLM tool loop."""
        toolset = self.tools_for(task)
        context = self.context_for(task)
        message = (context + "\n\n" if context else "") + self.task_message(task)
        loop = self.llm.tool_loop(
            self.system_prompt(task),
            [{"role": "user", "content": message}],
            toolset.specs,
            toolset.execute,
            max_steps=self.max_steps,
        )
        result = AgentResult(
            final=loop.final,
            steps=loop.steps,
            failed=loop.failed,
            reason=loop.reason,
            artifact=toolset.artifact,
            handed_off=toolset.handed_off,
            used_skill_id=toolset.used_skill_id,
            model=loop.model,
            latency_ms=loop.latency_ms,
        )
        if result.failed:
            log.warning("%s failed task %s: %s", self.agent_id, task.get("id"), result.reason)
        return result
