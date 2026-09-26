"""How long the work is, and how the story is laid out across that length.

Without this, every stage that outlines an episode knew the arc and the ending
but not how far away the ending was — so a twelve-chapter outline dutifully
arrived at the ending by chapter twelve, and a serial meant to run four hundred
chapters was over in one sitting.

A structure is three things:

- **the target length** — the number of episodes the author is aiming for;
- **the parts** — contiguous stretches of episodes, each with a job, so that
  "episode 13" means "early in part one, still setting things up";
- **the planned threads** (떡밥) — what is planted, roughly when, and roughly
  when it is paid off, so that setup and payoff are placed across the whole
  length rather than resolved in the chapter after they appear.

It is a plan, not a contract. The author can edit any of it, and changing the
target redraws it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MIN_TARGET = 1
MAX_TARGET = 2000


class StoryPart(BaseModel):
    """One stretch of the work — 1부, 2부 — and what it is for."""

    title: str = Field(description="짧은 이름. 예: '귀환과 적응'")
    start: int = Field(description="이 부의 첫 회차 번호")
    end: int = Field(description="이 부의 마지막 회차 번호")
    purpose: str = Field(
        default="",
        description="이 부에서 일어나는 일과, 이 부가 끝날 때 이야기가 어디에 와 있어야 하는지. 2-4문장.",
    )

    @property
    def length(self) -> int:
        return max(0, self.end - self.start + 1)


class PlannedThread(BaseModel):
    """A 떡밥: a question or promise planted early and answered later."""

    name: str = Field(description="짧은 이름")
    description: str = Field(
        default="",
        description="무엇을 심고, 결국 어떻게 회수되는지. 작가용 메모이므로 답까지 적는다.",
    )
    plant: int = Field(description="이 회차 즈음에 처음 심는다")
    payoff: int = Field(description="이 회차 즈음에 회수한다")


class RelationshipTurn(BaseModel):
    """One point where a relationship changes."""

    episode: int = Field(description="이 회차 즈음에")
    change: str = Field(description="무엇이 어떻게 바뀌는지. 한 문장.")


class PlannedRelationship(BaseModel):
    """How two people's relationship runs across the work.

    A cast of thirty with only its opening relationships written down gives
    every planning stage a list of names and nothing between them. This is the
    thread between two of them: where it starts, where it goes, and the
    episodes where it turns — so alliances fracture, rivals come round and a
    romance takes its time, on a schedule the whole length was planned around.
    """

    characters: list[str] = Field(description="두 인물의 이름, 작품에 적힌 그대로")
    start: str = Field(default="", description="처음의 관계")
    arc: str = Field(default="", description="어떻게 변해 가서 결국 어디에 닿는지. 1-3문장.")
    turns: list[RelationshipTurn] = Field(default_factory=list)


class StoryStructure(BaseModel):
    """The whole work's length and layout."""

    target_episodes: int = Field(ge=MIN_TARGET, le=MAX_TARGET)
    parts: list[StoryPart] = Field(default_factory=list)
    threads: list[PlannedThread] = Field(default_factory=list)
    relationships: list[PlannedRelationship] = Field(default_factory=list)

    def part_for(self, episode_number: int) -> StoryPart | None:
        return next(
            (p for p in self.parts if p.start <= episode_number <= p.end), None
        )


class StructureDraft(BaseModel):
    """Structured-output envelope: a layout for the whole work."""

    parts: list[StoryPart]
    threads: list[PlannedThread] = Field(default_factory=list)
    relationships: list[PlannedRelationship] = Field(default_factory=list)


def tidy_structure(structure: StoryStructure) -> StoryStructure:
    """Make a structure consistent: parts in order, touching, covering 1..target.

    A model asked to lay out four hundred episodes will sometimes leave a gap
    between parts, overlap two, or stop at 380. Each of those would leave some
    episode with no part — no idea where it is — so they are closed up here
    rather than trusted.
    """
    target = max(MIN_TARGET, min(MAX_TARGET, structure.target_episodes))
    parts = sorted(
        (p for p in structure.parts if p.title.strip()),
        key=lambda p: (p.start, p.end),
    )

    tidied: list[StoryPart] = []
    next_start = 1
    for part in parts:
        if next_start > target:
            break
        end = max(next_start, min(part.end, target))
        tidied.append(part.model_copy(update={"start": next_start, "end": end}))
        next_start = end + 1
    if tidied and tidied[-1].end < target:
        tidied[-1] = tidied[-1].model_copy(update={"end": target})
    if not tidied:
        tidied = [StoryPart(title="전체", start=1, end=target)]

    threads = []
    for thread in structure.threads:
        if not thread.name.strip():
            continue
        plant = max(1, min(thread.plant, target))
        payoff = max(plant, min(thread.payoff, target))
        threads.append(thread.model_copy(update={"plant": plant, "payoff": payoff}))
    threads.sort(key=lambda t: (t.plant, t.payoff))

    relationships = []
    for relationship in structure.relationships:
        names = [n.strip() for n in relationship.characters if n.strip()]
        if len(names) < 2:
            continue
        turns = sorted(
            (
                turn.model_copy(update={"episode": max(1, min(turn.episode, target))})
                for turn in relationship.turns
                if turn.change.strip()
            ),
            key=lambda t: t.episode,
        )
        relationships.append(
            relationship.model_copy(update={"characters": names[:2], "turns": turns})
        )

    return StoryStructure(
        target_episodes=target, parts=tidied, threads=threads, relationships=relationships
    )


def thread_window(target: int) -> int:
    """How close to its planned episode a thread counts as due.

    Proportional to the length: "around episode 200" in a 400-episode work is
    looser than "around episode 20" in a 40-episode one.
    """
    return max(2, target // 50)


def describe_position(structure: StoryStructure | None, episode_number: int) -> str:
    """Where one episode sits in the whole, for any stage that plans it.

    Said in plain terms a model can pace by: how far through the work, which
    part and how far through it, what that part is for, and which threads are
    due to be planted or paid off around here — and, as firmly, which are not.
    """
    if structure is None:
        return ""

    target = structure.target_episodes
    lines = [
        f"이 작품은 전체 약 {target}화로 계획되어 있습니다. 이번은 {episode_number}화입니다 "
        f"(전체의 약 {round(100 * episode_number / target)}%)."
    ]
    if episode_number > target:
        lines.append(
            "계획된 분량을 넘어섰습니다. 결말을 향해 정리하되, 작가가 분량을 늘렸을 수 있으니 "
            "급하게 끝내지는 마세요."
        )

    part = structure.part_for(episode_number)
    if part is not None:
        index = structure.parts.index(part) + 1
        through = episode_number - part.start + 1
        lines.append(
            f"지금은 {index}부 '{part.title}'({part.start}~{part.end}화)의 "
            f"{through}번째 회차입니다 ({part.length}화 중). 이 부는 {part.end}화까지 이어집니다."
        )
        if part.purpose.strip():
            lines.append(f"이 부의 역할: {part.purpose.strip()}")
        following = structure.parts[index:index + 1]
        if following:
            lines.append(
                f"다음 부 '{following[0].title}'({following[0].start}화~)의 일은 아직 "
                "시작하지 마세요."
            )

    window = thread_window(target)
    plant_now = [t for t in structure.threads if abs(t.plant - episode_number) <= window]
    payoff_now = [t for t in structure.threads if abs(t.payoff - episode_number) <= window]
    live = [
        t for t in structure.threads
        if t.plant < episode_number - window and t.payoff > episode_number + window
    ]
    if plant_now:
        lines.append("이 즈음 심을 떡밥: " + "; ".join(
            f"{t.name} ({t.plant}화 즈음 심고 {t.payoff}화 즈음 회수) — {t.description}"
            for t in plant_now
        ))
    if payoff_now:
        lines.append("이 즈음 회수할 떡밥: " + "; ".join(
            f"{t.name} ({t.payoff}화 즈음) — {t.description}" for t in payoff_now
        ))
    if live:
        lines.append(
            "이미 심었고 아직 회수할 때가 아닌 떡밥(살짝 상기시키거나 키우는 건 좋지만, 답을 "
            "주면 안 됩니다): " + ", ".join(f"{t.name} ({t.payoff}화 즈음 회수)" for t in live)
        )

    turning = [
        (relationship, turn)
        for relationship in structure.relationships
        for turn in relationship.turns
        if abs(turn.episode - episode_number) <= window
    ]
    if turning:
        lines.append("이 즈음의 관계 변화: " + "; ".join(
            f"{'·'.join(r.characters)} — {t.change} ({t.episode}화 즈음)" for r, t in turning
        ))
    # Only each pair's next turn: enough to keep it from arriving early,
    # without listing the whole cast's future.
    upcoming, seen = [], set()
    for relationship in structure.relationships:
        for turn in relationship.turns:
            key = tuple(relationship.characters)
            if turn.episode > episode_number + window and key not in seen:
                seen.add(key)
                upcoming.append(f"{'·'.join(relationship.characters)} ({turn.episode}화 즈음)")
    if upcoming:
        lines.append(
            "아직 오지 않은 관계 변화(지금 일으키지 마세요): " + ", ".join(upcoming[:10])
        )

    remaining = target - episode_number
    if remaining > 0:
        lines.append(
            f"결말까지 약 {remaining}화가 남았습니다. 이 회차의 사건은 이 위치에 맞는 크기로만 "
            "다루고, 뒤에 올 전개를 당겨 쓰지 마세요."
        )
    return "\n".join(lines)


def describe_range(structure: StoryStructure | None, start: int, end: int) -> str:
    """Where a run of episodes sits in the whole, for outlining them together.

    The single-episode position says what is due around one episode; a batch of
    twenty needs the same for the whole stretch — which parts it crosses, which
    threads and relationship turns fall inside it and at which episode, and what
    lies beyond it that must not be reached yet.
    """
    if structure is None:
        return ""

    target = structure.target_episodes
    lines = [
        f"이 작품은 전체 약 {target}화로 계획되어 있습니다. 이번에 쓸 회차는 {start}~{end}화입니다 "
        f"(전체의 약 {round(100 * start / target)}%~{round(100 * end / target)}%)."
    ]
    for index, part in enumerate(structure.parts, start=1):
        if part.end < start or part.start > end:
            continue
        covered_from, covered_to = max(part.start, start), min(part.end, end)
        lines.append(
            f"{index}부 '{part.title}'({part.start}~{part.end}화) 중 {covered_from}~{covered_to}화가 "
            f"이번 범위입니다. 이 부의 역할: {part.purpose}"
        )
        if part.end > end:
            lines.append(
                f"  이 부는 {part.end}화까지 이어지므로, {end}화에서 이 부의 목표를 끝내지 마세요."
            )
    following = [p for p in structure.parts if p.start > end]
    if following:
        lines.append(f"다음 부 '{following[0].title}'({following[0].start}화~)의 일은 시작하지 마세요.")

    plant = [t for t in structure.threads if start <= t.plant <= end]
    payoff = [t for t in structure.threads if start <= t.payoff <= end]
    live = [t for t in structure.threads if t.plant < start and t.payoff > end]
    if plant:
        lines.append("이 범위에서 심을 떡밥: " + "; ".join(
            f"{t.plant}화 즈음 '{t.name}' (회수는 {t.payoff}화 즈음) — {t.description}" for t in plant
        ))
    if payoff:
        lines.append("이 범위에서 회수할 떡밥: " + "; ".join(
            f"{t.payoff}화 즈음 '{t.name}' — {t.description}" for t in payoff
        ))
    if live:
        lines.append(
            "이미 심었고 이 범위 뒤에 회수할 떡밥(상기시키거나 키우되 답은 주지 마세요): "
            + ", ".join(f"'{t.name}' ({t.payoff}화 즈음)" for t in live)
        )

    turns = [
        (relationship, turn)
        for relationship in structure.relationships
        for turn in relationship.turns
        if start <= turn.episode <= end
    ]
    if turns:
        lines.append("이 범위의 관계 전환점: " + "; ".join(
            f"{turn.episode}화 즈음 {'·'.join(r.characters)} — {turn.change}"
            for r, turn in sorted(turns, key=lambda item: item[1].episode)
        ))
    upcoming, seen = [], set()
    for relationship in structure.relationships:
        for turn in relationship.turns:
            key = tuple(relationship.characters)
            if turn.episode > end and key not in seen:
                seen.add(key)
                upcoming.append(f"{'·'.join(relationship.characters)} ({turn.episode}화 즈음)")
    if upcoming:
        lines.append(
            "이 범위 뒤에 올 관계 변화(이번 범위에서 일으키지 마세요): " + ", ".join(upcoming[:15])
        )

    remaining = target - end
    if remaining > 0:
        lines.append(f"이 범위가 끝나도 결말까지 약 {remaining}화가 남습니다.")
    return "\n".join(lines)


def describe_structure(structure: StoryStructure) -> str:
    """The whole layout, for a stage that redraws or extends it."""
    lines = [f"목표 분량: 약 {structure.target_episodes}화"]
    for index, part in enumerate(structure.parts, start=1):
        lines.append(f"{index}부 '{part.title}' ({part.start}~{part.end}화): {part.purpose}")
    for thread in structure.threads:
        lines.append(
            f"떡밥 '{thread.name}': {thread.plant}화 즈음 심고 {thread.payoff}화 즈음 회수 — "
            f"{thread.description}"
        )
    for relationship in structure.relationships:
        turns = "; ".join(f"{t.episode}화 즈음 {t.change}" for t in relationship.turns)
        lines.append(
            f"관계 {'·'.join(relationship.characters)}: 처음 {relationship.start} → "
            f"{relationship.arc}" + (f" (전환점: {turns})" if turns else "")
        )
    return "\n".join(lines)


__all__ = [
    "MAX_TARGET",
    "MIN_TARGET",
    "PlannedRelationship",
    "PlannedThread",
    "RelationshipTurn",
    "StoryPart",
    "StoryStructure",
    "StructureDraft",
    "describe_position",
    "describe_structure",
    "thread_window",
    "tidy_structure",
]
