"""Where one episode sits in the run of episodes around it.

Every agent that writes an episode used to see what had already happened and
nothing of what was planned next. That is how a Director stages, in episode 13,
the confrontation the queue has planned for 14 — and how a Writer lets a scene
resolve a tension that the next chapter is built on.

So each of them is shown the episodes on both sides: the ones before as what
happened (their summary, once written), this one, and the ones after as plans.
The plans are labelled as plans. Knowing where the story goes next is for
pacing and setup; no character knows the future, and nothing planned for a
later episode is to happen early.
"""

from __future__ import annotations

from collections.abc import Sequence

from storyweaver.models import Episode

BEFORE = 2
AFTER = 3

NO_FLOW = ""


def _gist(episode: Episode) -> tuple[str, str]:
    written = episode.status == "completed" and episode.summary.strip()
    text = (episode.summary if written else episode.author_storyline).strip()
    return ("이미 쓴 회차 — 실제로 일어난 일" if written else "계획"), " ".join(text.split())


def episode_flow(
    episodes: Sequence[Episode],
    episode_number: int,
    before: int = BEFORE,
    after: int = AFTER,
) -> str:
    """The episodes around `episode_number`, in Korean, for any writing agent.

    Empty when there is nothing on either side worth saying.
    """
    ordered = sorted(episodes, key=lambda e: e.episode_number)
    index = next((i for i, e in enumerate(ordered) if e.episode_number == episode_number), None)
    if index is None:
        return NO_FLOW

    earlier = ordered[max(0, index - before):index]
    later = ordered[index + 1:index + 1 + after]
    if not earlier and not later:
        return NO_FLOW

    lines = []
    if earlier:
        lines.append("앞 회차:")
        for episode in earlier:
            label, text = _gist(episode)
            if text:
                lines.append(f"- {episode.episode_number}화 ({label}): {text}")
    current = ordered[index]
    lines.append(f"이번 회차 — {current.episode_number}화: {' '.join(current.author_storyline.split())}")
    if later:
        lines.append("다음 회차 (아직 일어나지 않은 계획):")
        for episode in later:
            label, text = _gist(episode)
            if text:
                lines.append(f"- {episode.episode_number}화 ({label}): {text}")
    return "\n".join(lines)


# What each consumer is told about the plans, appended wherever the flow goes.
FLOW_RULES = (
    "이 흐름은 이번 회차를 앞뒤와 맞물리게 하기 위한 참고입니다. 다음 회차의 사건은 "
    "이번 회차에서 일어나지 않습니다 — 당겨 쓰지 말고, 다음 회차가 설 자리를 남겨 두세요. "
    "인물은 미래를 알지 못합니다. 앞으로 일어날 일을 아는 듯이 말하거나 행동하지 않습니다."
)


def flow_block(flow: str) -> str:
    """The flow with its rules, or nothing."""
    return f"{flow}\n\n{FLOW_RULES}" if flow.strip() else "(앞뒤 회차 정보가 없습니다.)"
