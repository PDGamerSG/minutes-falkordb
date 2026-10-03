"""FactAgent: ingestion-time extraction and supersession detection (capability ``extract``).

``extract_episode`` tasks re-run the ingest pipeline for one stored episode (Gemma 4 extraction +
"contradiction or refinement?" judgement). Other kinds fall back to the tool loop with
``write_fact``/``recall`` so a human can ask it to record something by hand.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ingest.extract import GoldExtractor, hinted_supersession
from ingest.fakes import new_id
from ingest.gold import find_gold
from ingest.pipeline import SourceContext, ingest_episode_record

from .base import AgentResult, BaseAgent

log = logging.getLogger(__name__)


class FactAgent(BaseAgent):
    agent_id = "fact_agent"
    name = "FactAgent"
    capabilities = ["extract"]
    handles = ("extract_episode", "extract", "record_fact")
    tool_names = ["recall", "active_facts", "write_fact", "finish"]
    prompt_name = "fact"

    def task_instructions(self, task: dict[str, Any]) -> str:
        return "Record the statement(s) in the payload with write_fact (one per statement), then call finish."

    def run(self, task: dict[str, Any]) -> AgentResult:
        if task.get("kind") == "extract_episode":
            return self._extract_episode(task)
        return super().run(task)

    def _extract_episode(self, task: dict[str, Any]) -> AgentResult:
        payload = task.get("payload") or {}
        episode_id = payload.get("episode_id") or next(iter(task.get("about") or []), None)
        if not episode_id:
            return AgentResult(failed=True, reason="extract_episode needs payload.episode_id")
        episode = self.hive.get_episode(self.tenant, episode_id)
        if episode is None:
            return AgentResult(failed=True, reason=f"episode {episode_id!r} not found")
        container_id = episode.get("container_id") or ""
        container = self.hive.get_meeting(self.tenant, container_id) or self.hive.get_thread(self.tenant, container_id) or {}
        started = container.get("started_at") or episode.get("t_occurred") or 0
        source = SourceContext(
            container_id=container_id,
            container_kind="thread" if episode.get("source_kind") == "email" else "meeting",
            title=container.get("title") or container.get("subject") or container_id,
            day=datetime.fromtimestamp(int(started) / 1000, tz=UTC).date(),
            speakers=self.hive.list_persons(self.tenant),
        )
        extractor = None
        judge = None
        if getattr(self.llm, "backend", "") == "fake":
            gold = find_gold(self.settings.data_path / "gold", container_id=container_id)
            if gold is None:
                return AgentResult(failed=True, reason=f"fake backend: no gold labels for {container_id!r}")
            extractor, judge = GoldExtractor(gold), hinted_supersession
        stats = ingest_episode_record(
            self.tenant, self.hive, self.embedder, episode, source, llm=self.llm, extractor=extractor, judge=judge
        )
        summary = f"extracted {stats['items']} items from {episode_id} ({stats['superseded']} superseded)"
        return AgentResult(
            final=summary,
            steps=[{"tool": "extract", "args": {"episode_id": episode_id}, "result": stats}],
            artifact={"id": new_id("art"), "kind": "extraction", "text": json.dumps(stats, default=str)},
            model=getattr(self.llm, "model", ""),
        )
