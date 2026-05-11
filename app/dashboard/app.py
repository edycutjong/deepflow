"""
Silent Whale — Web Dashboard.
FastAPI + Jinja2 server for score visualization, project details, and health monitoring.
Designed to run on port 8081 alongside the healthcheck on 8080.
"""
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Project,
    ScoreHistory,
    SourceHealth,
    AlertQueue,
    ProjectOutcome,
)
from app.db.session import async_session

app = FastAPI(title="Silent Whale Dashboard", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory="app/dashboard/templates")


@app.get("/", response_class=HTMLResponse)
async def leaderboard(request: Request):
    """Score leaderboard — all projects ranked by score."""
    async with async_session() as session:
        result = await session.execute(
            select(Project).order_by(Project.latest_score.desc().nullslast())
        )
        projects = result.scalars().all()

        # Get recent alert count
        alert_result = await session.execute(
            select(func.count(AlertQueue.id)).where(AlertQueue.sent.is_(True))
        )
        total_alerts = alert_result.scalar() or 0

        # Get source health summary
        health_result = await session.execute(select(SourceHealth))
        sources = health_result.scalars().all()

    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "projects": projects,
            "total_alerts": total_alerts,
            "sources": sources,
            "now": datetime.now(timezone.utc),
        },
    )


@app.get("/project/{slug}", response_class=HTMLResponse)
async def project_detail(request: Request, slug: str):
    """Project detail — score history, chain TVL, alerts."""
    async with async_session() as session:
        result = await session.execute(
            select(Project).where(Project.slug == slug)
        )
        project = result.scalar_one_or_none()

        if not project:
            return HTMLResponse("<h1>Project not found</h1>", status_code=404)

        # Score history (last 30 entries)
        history_result = await session.execute(
            select(ScoreHistory)
            .where(ScoreHistory.project_id == project.id)
            .order_by(ScoreHistory.scored_at.desc())
            .limit(30)
        )
        history = list(reversed(history_result.scalars().all()))

        # Parse chain TVL
        chain_tvl = {}
        if project.chain_tvl:
            try:
                chain_tvl = json.loads(project.chain_tvl)
            except (json.JSONDecodeError, TypeError):
                pass

        # Outcomes
        outcome_result = await session.execute(
            select(ProjectOutcome)
            .where(ProjectOutcome.project_id == project.id)
            .order_by(ProjectOutcome.created_at.desc())
        )
        outcomes = outcome_result.scalars().all()

        # Recent alerts
        alert_result = await session.execute(
            select(AlertQueue)
            .where(AlertQueue.project_id == project.id)
            .order_by(AlertQueue.created_at.desc())
            .limit(10)
        )
        alerts = alert_result.scalars().all()

    return templates.TemplateResponse(
        "project_detail.html",
        {
            "request": request,
            "project": project,
            "history": history,
            "chain_tvl": chain_tvl,
            "outcomes": outcomes,
            "alerts": alerts,
            "now": datetime.now(timezone.utc),
        },
    )


@app.get("/health-status", response_class=HTMLResponse)
async def health_status(request: Request):
    """Source health dashboard."""
    async with async_session() as session:
        result = await session.execute(
            select(SourceHealth).order_by(SourceHealth.source_name)
        )
        sources = result.scalars().all()

    return templates.TemplateResponse(
        "health_status.html",
        {
            "request": request,
            "sources": sources,
            "now": datetime.now(timezone.utc),
        },
    )


@app.get("/api/scores/{slug}")
async def api_score_history(slug: str):
    """JSON API for chart data."""
    async with async_session() as session:
        project_result = await session.execute(
            select(Project).where(Project.slug == slug)
        )
        project = project_result.scalar_one_or_none()
        if not project:
            return {"error": "not found"}

        history_result = await session.execute(
            select(ScoreHistory)
            .where(ScoreHistory.project_id == project.id)
            .order_by(ScoreHistory.scored_at.asc())
            .limit(100)
        )
        history = history_result.scalars().all()

    return {
        "slug": slug,
        "labels": [h.scored_at.strftime("%m/%d %H:%M") for h in history],
        "total": [h.total_score for h in history],
        "tvl": [h.tvl_points for h in history],
        "growth": [h.growth_points for h in history],
        "funding": [h.funding_points for h in history],
        "github": [h.github_points for h in history],
    }
