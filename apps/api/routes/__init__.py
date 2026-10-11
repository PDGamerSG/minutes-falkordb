"""Route modules; ``all_routers`` is what ``main.create_app`` mounts."""

from __future__ import annotations

from fastapi import APIRouter

from . import bench, board, chat, email, health, meetings, memory, skills, tenants, impact


def all_routers() -> list[APIRouter]:
    return [health.router, tenants.router, meetings.router, email.router, memory.router, chat.router, board.router, skills.router, bench.router, impact.router]
