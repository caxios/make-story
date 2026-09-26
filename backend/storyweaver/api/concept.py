"""The concept session: proposing a novel, refining it, and committing it.

Everything here works on one session held on disk, so an author can close the
browser mid-thought and come back to it.

There are two ways in. **Proposing** hands the author a spread of finished
concepts to choose between; **talking** starts from nothing and finds the book
in the conversation. They meet at `chosen`: from there the concept is refined
and committed the same way, whichever way it arrived.

Refining never sees a transcript — the concept carries the state, so the
fiftieth refinement costs what the first did. The conversation is the one
exception, because a conversation that forgets what was said is not one.

`/commit` is the only call that writes to the project, and the only one that
can destroy anything. It is refused on a project that already has a story in
it, and it runs under one lock.
"""

from __future__ import annotations

import logging

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from storyweaver.agents import concept as agent
from storyweaver.agents import structure as layout
from storyweaver.api import deps
from storyweaver.concept_store import ConceptStore
from storyweaver.models.concept import (
    ConceptMessage,
    ConceptSession,
    ConceptTurn,
    StoryConcept,
)
from storyweaver.models.structure import MAX_TARGET, StoryStructure
from storyweaver.ui.project import Project
from storyweaver.wiki import commit_concept
from storyweaver.wiki.sync import sync_concept

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


Target = Annotated[int, Field(ge=1, le=MAX_TARGET)]


class ChooseRequest(BaseModel):
    index: int = Field(ge=0, description="Which of the proposals to keep")
    episodes: int = Field(default=agent.DEFAULT_EPISODES, ge=1, le=MAX_EPISODES)
    # How long the whole work is meant to run. The opening `episodes` are paced
    # as the start of a work this long, not as the whole of it.
    target_episodes: Target = agent.DEFAULT_TARGET


class OutlineRequest(BaseModel):
    episodes: int = Field(default=agent.DEFAULT_EPISODES, ge=1, le=MAX_EPISODES)
    target_episodes: Target | None = None


class RefineRequest(BaseModel):
    instruction: Instruction


class TalkRequest(BaseModel):
    message: Instruction


class DistillRequest(BaseModel):
    """Turning the conversation into a concept, optionally with its outline."""

    episodes: int = Field(default=0, ge=0, le=MAX_EPISODES)
    target_episodes: Target | None = None


class SessionView(BaseModel):
    """The session, plus what the last round changed."""

    session: ConceptSession | None = None
    changed: list[str] = Field(default_factory=list)
    # Committed, and edited since it was last carried into the work.
    unsynced: bool = False

    def model_post_init(self, _context) -> None:
        session = self.session
        self.unsynced = bool(
            session is not None
            and session.status == "committed"
            and session.committed_concept is not None
            and session.chosen is not None
            and session.chosen != session.committed_concept
        )


class EditRequest(BaseModel):
    """The author's own edit of the whole concept, field by field."""

    concept: StoryConcept


class SyncResponse(BaseModel):
    applied: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    session: ConceptSession | None = None


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


def _keep_baseline(session: ConceptSession) -> None:
    """Before the first edit after commit, remember what the work was given.

    Sessions committed before this existed have no baseline; the concept as it
    stands right before the edit is the best one available.
    """
    if session.status == "committed" and session.committed_concept is None:
        session.committed_concept = session.chosen


def _model_failed(error: Exception, what: str) -> HTTPException:
    logger.exception("The concept agent failed while %s", what)
    return HTTPException(status_code=502, detail=f"기획을 {what} 실패했습니다: {error}")


def _check_lengths(episodes: int, target: int) -> None:
    if episodes > target:
        raise HTTPException(
            status_code=422,
            detail=f"처음 구상할 회차({episodes}화)가 전체 분량({target}화)보다 많습니다",
        )


def _lay_out_and_outline(
    concept: StoryConcept, episodes: int, target: int
) -> tuple[StoryConcept, StoryStructure]:
    """Two calls: the whole work's layout, then its opening paced by it."""
    try:
        structure = layout.lay_out(target, layout.describe_concept(concept))
    except Exception as error:  # noqa: BLE001
        raise _model_failed(error, f"{target}화 분량으로 배치하는 데") from error
    try:
        outlined = agent.outline(concept, count=episodes, structure=structure)
    except Exception as error:  # noqa: BLE001
        raise _model_failed(error, "회차로 펼치는 데") from error
    return outlined, structure


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

    Asking again replaces the spread — a set of proposals the author did not
    pick is not worth protecting. It does **not** touch the conversation. The
    two ways in sit side by side on one screen, and an author who has spent an
    afternoon talking must be able to glance at three proposals without that
    glance costing them the afternoon.
    """
    existing = _store().load()
    try:
        concepts = agent.propose(seed=body.seed, count=body.count)
    except Exception as error:  # noqa: BLE001 — reported to the author
        raise _model_failed(error, "만드는 데") from error

    session = ConceptSession(
        seed=body.seed.strip(),
        proposals=concepts,
        status="proposing",
        messages=existing.messages if existing else [],
    )
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

    _check_lengths(body.episodes, body.target_episodes)
    chosen, structure = _lay_out_and_outline(
        session.proposals[body.index], body.episodes, body.target_episodes
    )

    session.chosen = chosen
    session.structure = structure
    session.target_episodes = body.target_episodes
    session.status = "refining"
    session.turns.append(
        ConceptTurn(
            turn=len(session.turns),
            instruction=f"'{chosen.title}'(으)로 시작",
            changed=[
                f"전체 {structure.target_episodes}화를 {len(structure.parts)}부로 나누고 "
                f"떡밥 {len(structure.threads)}개를 배치했습니다",
                f"처음 {len(chosen.episodes)}화의 회차 구상을 만들었습니다",
            ],
        )
    )
    return SessionView(session=_store().save(session), changed=session.turns[-1].changed)


@router.post("/outline", response_model=SessionView)
def redraw_outline(body: OutlineRequest = Body(default_factory=OutlineRequest)) -> SessionView:
    """Draw the chapter outline again, at a different length."""
    session = _require_session()
    chosen = _require_chosen(session)
    target = body.target_episodes or session.target_episodes or agent.DEFAULT_TARGET
    _check_lengths(body.episodes, target)

    # The layout is drawn again too: a redraw is usually because the length
    # changed, or because the concept was refined since it was last laid out.
    redrawn, structure = _lay_out_and_outline(chosen, body.episodes, target)

    changed = [
        f"전체 {target}화를 {len(structure.parts)}부로 나누고 "
        f"떡밥 {len(structure.threads)}개를 배치했습니다",
        *agent.describe_changes(chosen, redrawn),
    ]
    session.chosen = redrawn
    session.structure = structure
    session.target_episodes = target
    session.turns.append(
        ConceptTurn(
            turn=len(session.turns),
            instruction=f"전체 {target}화 기준으로 처음 {body.episodes}화 구상을 다시",
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

    _keep_baseline(session)
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
# Working it out by talking
# ---------------------------------------------------------------------------


@router.post("/talk", response_model=SessionView)
def talk(body: TalkRequest) -> SessionView:
    """Say one thing to the model, and get one thing back.

    The other way in hands the author three finished concepts to choose
    between. This one starts with nothing and finds the book in the
    conversation, which is what an author who cannot answer "what do you want
    to write?" actually needs.

    The author's message is saved before the model is called, so a failed or
    slow call never costs them what they typed.
    """
    store = _store()
    session = store.load() or ConceptSession(status="talking")
    session.messages.append(ConceptMessage(role="author", text=body.message))
    store.save(session)

    try:
        reply = agent.talk(session.messages)
    except Exception as error:  # noqa: BLE001 — reported to the author
        raise _model_failed(error, "이어 가는 데") from error

    session.messages.append(ConceptMessage(role="ai", text=reply))
    return SessionView(session=store.save(session))


@router.post("/talk/build", response_model=SessionView)
def build_from_talk(
    body: DistillRequest = Body(default_factory=DistillRequest),
) -> SessionView:
    """Write the conversation down as a concept, and refine it from there.

    This is where the two ways in meet: from here the concept behaves exactly
    as a chosen proposal does, and the author has the same refinement loop.

    The chapter outline is a second model call, so it is only drawn when the
    author asks for one. They may well want to reshape the concept first.
    """
    store = _store()
    session = _require_session()
    if not any(message.role == "author" for message in session.messages):
        raise HTTPException(status_code=409, detail="아직 나눈 대화가 없습니다")

    try:
        concept = agent.distill(session.messages)
    except Exception as error:  # noqa: BLE001
        raise _model_failed(error, "정리하는 데") from error

    if body.episodes:
        target = body.target_episodes or session.target_episodes or agent.DEFAULT_TARGET
        _check_lengths(body.episodes, target)
        concept, session.structure = _lay_out_and_outline(concept, body.episodes, target)
        session.target_episodes = target

    changed = [f"대화 {len(session.messages)}개를 '{concept.title}'(으)로 정리했습니다"]
    # What the conversation never settled, said plainly rather than left as a
    # blank the author only notices at commit.
    missing = agent.missing_parts(concept)
    if missing:
        changed.append(f"대화에서 정해지지 않은 것: {', '.join(missing)}")
    if concept.episodes:
        changed.append(f"회차 구상 {len(concept.episodes)}개를 만들었습니다")

    session.chosen = concept
    session.status = "refining"
    session.turns.append(
        ConceptTurn(turn=len(session.turns), instruction="대화한 내용으로 정리", changed=changed)
    )
    return SessionView(session=store.save(session), changed=changed)


@router.delete("/talk", response_model=SessionView)
def clear_talk() -> SessionView:
    """Throw the conversation away, keeping whatever it already produced."""
    store = _store()
    session = _require_session()
    session.messages = []
    return SessionView(session=store.save(session))


# ---------------------------------------------------------------------------
# Editing by hand
# ---------------------------------------------------------------------------


@router.put("/chosen", response_model=SessionView)
def edit_chosen(body: EditRequest) -> SessionView:
    """Replace the concept with the author's own edit. No model call.

    Refining asks the model to change something; this is for when the author
    knows exactly what they want written — a name, a line of the arc, one
    episode. Works before commit and after it.
    """
    session = _require_session()
    chosen = _require_chosen(session)
    _keep_baseline(session)

    edited = agent._tidy(body.concept)
    if edited == chosen:
        return SessionView(session=session, changed=["바뀐 것이 없습니다"])
    changed = agent.describe_changes(chosen, edited)

    session.chosen = edited
    session.turns.append(
        ConceptTurn(turn=len(session.turns), instruction="직접 수정", changed=changed)
    )
    return SessionView(session=_store().save(session), changed=changed)


# ---------------------------------------------------------------------------
# Carrying edits into a committed work
# ---------------------------------------------------------------------------


def _sync_pair(session: ConceptSession) -> tuple[StoryConcept, StoryConcept]:
    if session.status != "committed":
        raise HTTPException(status_code=409, detail="아직 작품에 반영하지 않은 기획입니다")
    chosen = _require_chosen(session)
    return session.committed_concept or chosen, chosen


@router.post("/sync/preview", response_model=SyncResponse)
def preview_sync(project: Project = Depends(deps.get_project)) -> SyncResponse:
    """What carrying the edits over would do. Nothing is written."""
    session = _require_session()
    before, after = _sync_pair(session)
    report = sync_concept(project.model_copy(deep=True), None, before, after)
    return SyncResponse(**report.as_dict(), session=session)


@router.post("/sync", response_model=SyncResponse)
def apply_sync() -> SyncResponse:
    """Carry what changed in the concept since it was last applied into the work."""
    session = _require_session()
    before, after = _sync_pair(session)

    with deps.write_lock():
        project = deps.get_project()
        memory = deps.get_memory()
        report = sync_concept(
            project, memory.chronicle if memory is not None else None, before, after
        )
        deps.save_project(project)

    session.committed_concept = after
    if report.applied:
        session.turns.append(
            ConceptTurn(
                turn=len(session.turns), instruction="작품에 반영", changed=report.applied
            )
        )
    return SyncResponse(**report.as_dict(), session=_store().save(session))


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
            session.messages,
            structure=session.structure,
        )
        deps.save_project(project)

    session.status = "committed"
    session.committed_concept = chosen
    from datetime import datetime, timezone

    session.committed_at = datetime.now(timezone.utc)
    _store().save(session)

    return CommitResponse(**report.as_dict())


@router.delete("", status_code=204)
def discard() -> None:
    """Throw the session away. The project is untouched."""
    _store().clear()
