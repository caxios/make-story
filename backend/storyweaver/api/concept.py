"""The concept session: proposing a novel, refining it, and committing it.

Everything here works on one session held on disk, so an author can close the
browser mid-thought and come back to it. The model is called in three places —
proposing a spread, drawing the chapter outline for the one that was kept, and
revising it — and never sees the transcript: the concept carries the state, so
the fiftieth refinement costs what the first did.

`/commit` is the only call that writes to the project, and the only one that
can destroy anything. It is refused on a project that already has a story in
it, and it runs under one lock.
"""

from __future__ import annotations

import logging

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from storyweaver.agents import concept as agent
from storyweaver.api import deps
from storyweaver.concept_store import ConceptStore
from storyweaver.models.concept import ConceptSession, ConceptTurn, StoryConcept
from storyweaver.wiki import commit_concept

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/concept", tags=["concept"])

Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# A spread the author has to read. Three is enough to be a choice and few
# enough to hold in the head; more is a list to skim rather than weigh.
MAX_PROPOSALS = 5
MAX_EPISODES = 40


class ProposeRequest(BaseModel):
    seed: str = ""
    count: int = Field(default=agent.DEFAULT_COUNT, ge=1, le=MAX_PROPOSALS)


class ChooseRequest(BaseModel):
    index: int = Field(ge=0, description="Which of the proposals to keep")
    episodes: int = Field(default=agent.DEFAULT_EPISODES, ge=1, le=MAX_EPISODES)


class OutlineRequest(BaseModel):
    episodes: int = Field(default=agent.DEFAULT_EPISODES, ge=1, le=MAX_EPISODES)


class RefineRequest(BaseModel):
    instruction: Instruction


class SessionView(BaseModel):
    """The session, plus what the last round changed."""

    session: ConceptSession | None = None
    changed: list[str] = Field(default_factory=list)


class CommitResponse(BaseModel):
    characters: list[str]
    rules: list[str]
    locations: list[str]
    episodes: int
    chronicle_entries: int
    dropped: list[str]


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


def _store() -> ConceptStore:
    return ConceptStore(deps.get_store().state_dir)


def _require_session() -> ConceptSession:
    session = _store().load()
    if session is None:
        raise HTTPException(status_code=404, detail="진행 중인 기획 세션이 없습니다")
    return session


def _require_chosen(session: ConceptSession) -> StoryConcept:
    if session.chosen is None:
        raise HTTPException(
            status_code=409, detail="먼저 제안 중 하나를 골라 주세요"
        )
    return session.chosen


def _model_failed(error: Exception, what: str) -> HTTPException:
    logger.exception("The concept agent failed while %s", what)
    return HTTPException(status_code=502, detail=f"기획을 {what} 실패했습니다: {error}")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@router.get("", response_model=SessionView)
def read_session() -> SessionView:
    """The session in progress, or nothing.

    This is what survives a browser restart: working out what a novel is takes
    more than one sitting, and closing a tab must not cost an afternoon.
    """
    return SessionView(session=_store().load())


# ---------------------------------------------------------------------------
# Proposing
# ---------------------------------------------------------------------------


@router.post("/propose", response_model=SessionView)
def propose(body: ProposeRequest = Body(default_factory=ProposeRequest)) -> SessionView:
    """Open a session with a spread of concepts, from a hint or from nothing.

    Starting over replaces whatever was there. A session the author has
    abandoned is not worth protecting; one they have committed already wrote
    itself into the project, and that is not undone by this.
    """
    try:
        concepts = agent.propose(seed=body.seed, count=body.count)
    except Exception as error:  # noqa: BLE001 — reported to the author
        raise _model_failed(error, "만드는 데") from error

    session = ConceptSession(seed=body.seed.strip(), proposals=concepts, status="proposing")
    session.turns.append(ConceptTurn(turn=0, instruction="", changed=[]))
    return SessionView(session=_store().save(session))


@router.post("/choose", response_model=SessionView)
def choose(body: ChooseRequest) -> SessionView:
    """Keep one proposal, and draw its chapter outline.

    The outline is drawn here rather than for the whole spread: twelve lines
    across three concepts is two dozen written to be thrown away, and asking
    for all of it in one call is what made the model ration its output and
    return a third concept that was a title and nothing else.
    """
    session = _require_session()
    if not 0 <= body.index < len(session.proposals):
        raise HTTPException(
            status_code=404,
            detail=f"{body.index}번 제안이 없습니다 (0~{len(session.proposals) - 1})",
        )

    chosen = session.proposals[body.index]
    try:
        chosen = agent.outline(chosen, count=body.episodes)
    except Exception as error:  # noqa: BLE001
        raise _model_failed(error, "회차로 펼치는 데") from error

    session.chosen = chosen
    session.status = "refining"
    session.turns.append(
        ConceptTurn(
            turn=len(session.turns),
            instruction=f"'{chosen.title}'(으)로 시작",
            changed=[f"회차 구상 {len(chosen.episodes)}개를 만들었습니다"],
        )
    )
    return SessionView(session=_store().save(session), changed=session.turns[-1].changed)


@router.post("/outline", response_model=SessionView)
def redraw_outline(body: OutlineRequest = Body(default_factory=OutlineRequest)) -> SessionView:
    """Draw the chapter outline again, at a different length."""
    session = _require_session()
    chosen = _require_chosen(session)

    try:
        redrawn = agent.outline(chosen, count=body.episodes)
    except Exception as error:  # noqa: BLE001
        raise _model_failed(error, "회차로 펼치는 데") from error

    changed = agent.describe_changes(chosen, redrawn)
    session.chosen = redrawn
    session.turns.append(
        ConceptTurn(
            turn=len(session.turns),
            instruction=f"회차 구상을 {body.episodes}개로 다시",
            changed=changed,
        )
    )
    return SessionView(session=_store().save(session), changed=changed)


# ---------------------------------------------------------------------------
# Refining
# ---------------------------------------------------------------------------


@router.post("/refine", response_model=SessionView)
def refine(body: RefineRequest) -> SessionView:
    """Revise the chosen concept once. As many times as the author wants."""
    session = _require_session()
    chosen = _require_chosen(session)

    try:
        revised, changed = agent.refine(chosen, body.instruction)
    except Exception as error:  # noqa: BLE001
        raise _model_failed(error, "다듬는 데") from error

    session.chosen = revised
    session.turns.append(
        ConceptTurn(turn=len(session.turns), instruction=body.instruction, changed=changed)
    )
    return SessionView(session=_store().save(session), changed=changed)


# ---------------------------------------------------------------------------
# Committing
# ---------------------------------------------------------------------------


@router.post("/commit", response_model=CommitResponse)
def commit(force: bool = Query(default=False)) -> CommitResponse:
    """Write the concept into the project: world, cast, story page and queue.

    Refused on a project that already has a story in it. Committing over one
    would merge two novels quietly — the world replaced, a second cast added,
    a second queue appended — and the author would have no way to tell by
    looking what had happened. Starting a new story is `ProjectStore.reset()`,
    which the author already has.

    No model calls: everything was settled while refining.
    """
    session = _require_session()
    chosen = _require_chosen(session)

    with deps.write_lock():
        project = deps.get_project()
        if not force and (project.characters or project.world.overview.strip()):
            raise HTTPException(
                status_code=409,
                detail="이미 설정이 있는 작품입니다. 기획을 반영하면 세계관이 덮이고 "
                "인물과 회차가 섞입니다. 새 작품으로 시작하시려면 먼저 초기화해 주세요.",
            )

        memory = deps.get_memory()
        report = commit_concept(
            project,
            memory.chronicle if memory is not None else None,
            chosen,
            session.turns,
        )
        deps.save_project(project)

    session.status = "committed"
    from datetime import datetime, timezone

    session.committed_at = datetime.now(timezone.utc)
    _store().save(session)

    return CommitResponse(**report.as_dict())


@router.delete("", status_code=204)
def discard() -> None:
    """Throw the session away. The project is untouched."""
    _store().clear()
