"""MemoryManager — the one surface agents and the pipeline talk to.

Three stores sit behind it: a vector store for "what does this remind you of",
a JSON store for questions with exactly one right answer, and a plot tracker for
threads awaiting a payoff. Callers should not need to know which is which.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from storyweaver import config
from storyweaver.agents import context
from storyweaver.memory import vector_store as vs
from storyweaver.memory.plot_tracker import PlotThread, PlotThreadTracker
from storyweaver.memory.structured_store import StructuredStore
from storyweaver.memory.summarizer import EpisodeMemory, summarize_episode
from storyweaver.memory.vector_store import Memory, VectorStore
from storyweaver.models import (
    CharacterMemory,
    CharacterProfile,
    Episode,
    InteractionRecord,
    Scene,
    WorldLore,
)

logger = logging.getLogger(__name__)

NOTHING_YET = "(nothing recorded yet)"
# How many memories each agent's context packet gets. The Director sees the
# story broadly; a character sees only what they were present for.
DIRECTOR_MEMORIES = 8
CHARACTER_MEMORIES = 5
WRITER_MEMORIES = 4
# Trailing prose handed to the Writer for voice continuity.
STYLE_SAMPLE_WORDS = 500
# The tail of an episode's prose, kept as its closing situation. Long enough to
# carry where everyone stands and what the last beat was; short enough that the
# next Director reads it rather than skimming it.
CLOSING_PASSAGE_CHARS = 700
# How many episodes back the Director sees in full, in order.
ARC_EPISODES = 3


def _closing_passage(episode: Episode) -> str:
    """The last stretch of an episode's prose — where it left everyone standing.

    Built by taking whole paragraphs from the end until the budget is spent, so
    the passage always opens on a paragraph rather than halfway through a
    sentence. A single paragraph longer than the budget is truncated, because
    some of it beats none of it.
    """
    text = (episode.final_text or "").strip()
    if not text:
        return ""

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    kept: list[str] = []
    budget = CLOSING_PASSAGE_CHARS
    for paragraph in reversed(paragraphs):
        if kept and len(paragraph) > budget:
            break
        kept.insert(0, paragraph)
        budget -= len(paragraph) + 2
        if budget <= 0:
            break

    passage = "\n\n".join(kept).strip()
    return passage[-CLOSING_PASSAGE_CHARS:].strip()


class MemoryManager:
    """Read/write access to everything the story remembers."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        data_dir: Path | str | None = None,
        chroma_client=None,
        embedding_function=None,
    ):
        data_dir = Path(data_dir) if data_dir is not None else config.STATE_DIR
        self.data_dir = data_dir
        self.vector_store = vector_store or VectorStore(
            client=chroma_client, embedding_function=embedding_function
        )
        self.structured_store = StructuredStore(data_dir)
        self.plot_tracker = PlotThreadTracker(data_dir)

    # ======================================================================
    # WRITE
    # ======================================================================

    def seed_world(self, world: WorldLore) -> int:
        """Load the author's world into the lore collection. Idempotent."""
        return self.vector_store.seed_world_lore(world)

    def record_episode_completion(
        self, episode: Episode, memory: EpisodeMemory
    ) -> EpisodeMemory:
        """Commit a finished episode to every store.

        Ordering matters: threads are opened before the interactions that cite
        them are indexed, so a retrieved memory never names a thread the tracker
        has never heard of.
        """
        number = episode.episode_number
        opened, resolved = self._apply_thread_updates(memory, number)

        for update in memory.character_updates:
            self.update_character_state(
                update.character_id,
                {
                    "internal_state": update.internal_state or None,
                    "current_goals": update.current_goals or None,
                    "relationship_updates": update.relationship_updates or None,
                    "episode": number,
                },
            )

        by_character = _interactions_by_character(memory.interactions)
        for character_id, records in by_character.items():
            self.structured_store.update_character(
                character_id, interactions=records, episode=number
            )

        self.structured_store.record_episode_summary(
            number,
            memory.summary,
            world_lore_updates=memory.world_lore_updates,
            opened_threads=opened,
            resolved_threads=resolved,
            closing=_closing_passage(episode),
        )

        self.vector_store.add_episode_summary(
            number,
            memory.summary,
            characters_involved=memory.characters_involved(),
            locations=memory.locations,
            key_events=memory.key_events,
            mood=memory.mood,
        )
        stored = self.vector_store.add_interaction_records(memory.interactions)

        for index, lore in enumerate(memory.world_lore_updates):
            self.vector_store.add_lore(
                f"lore_ep{number}_{index}", lore, episode_introduced=number
            )

        logger.info(
            "Episode %d recorded: %d interactions, %d thread updates, %d lore updates",
            number,
            stored,
            len(memory.thread_updates),
            len(memory.world_lore_updates),
        )
        return memory

    def summarize_and_record(
        self,
        episode: Episode,
        world: WorldLore,
        characters: Mapping[str, CharacterProfile],
        language: str = "ko",
        llm=None,
    ) -> EpisodeMemory:
        """Summarize a finished episode and commit the result."""
        memory = summarize_episode(
            episode,
            world,
            characters,
            open_threads=self.get_active_plot_threads(),
            language=language,
            llm=llm,
        )
        return self.record_episode_completion(episode, memory)

    def update_character_state(self, character_id: str, updates: Mapping) -> CharacterMemory:
        """Update a character's emotional state, goals, or relationships."""
        return self.structured_store.update_character(
            character_id,
            internal_state=updates.get("internal_state"),
            current_goals=updates.get("current_goals"),
            relationship_updates=updates.get("relationship_updates"),
            interactions=updates.get("interactions"),
            episode=updates.get("episode"),
        )

    def open_plot_thread(
        self,
        thread_name: str,
        description: str,
        episode: int,
        thread_id: str | None = None,
        linked_characters: Sequence[str] = (),
    ) -> PlotThread:
        """Register a new 떡밥."""
        return self.plot_tracker.open(
            PlotThread(
                id=thread_id or _slug(thread_name),
                name=thread_name,
                description=description,
                opened_in_episode=episode,
                linked_characters=list(linked_characters),
            )
        )

    def resolve_plot_thread(self, thread_name: str, resolution: str, episode: int) -> PlotThread:
        """Mark a 떡밥 as resolved. Accepts either the thread id or its name."""
        return self.plot_tracker.resolve(self._thread_id(thread_name), resolution, episode)

    def progress_plot_thread(self, thread_name: str, event: str, episode: int) -> PlotThread:
        return self.plot_tracker.progress(self._thread_id(thread_name), event, episode)

    # ======================================================================
    # READ
    # ======================================================================

    def get_relevant_memories(
        self, query: str, character_id: str | None = None, top_k: int = 10
    ) -> list[str]:
        """Semantic search across all memory, optionally filtered by character."""
        found = self.vector_store.search(query, top_k=top_k, character_id=character_id)
        return [m.render() for m in found]

    def search(
        self,
        query: str,
        collections: Sequence[str] = vs.COLLECTIONS,
        top_k: int = 10,
        character_id: str | None = None,
    ) -> list[Memory]:
        """As `get_relevant_memories`, but returning the records themselves."""
        return self.vector_store.search(
            query, collections=collections, top_k=top_k, character_id=character_id
        )

    def get_character_state(self, character_id: str) -> CharacterMemory:
        """Exact current state: relationships, goals, emotional state."""
        return self.structured_store.get_character(character_id)

    def get_active_plot_threads(self) -> list[PlotThread]:
        """All unresolved 떡밥."""
        return self.plot_tracker.get_active()

    def get_stale_plot_threads(
        self, episodes_since_last_ref: int | None = None, current_episode: int | None = None
    ) -> list[PlotThread]:
        """Threads that have gone quiet long enough to risk reading as dropped."""
        return self.plot_tracker.get_stale(
            episodes_since_last_ref
            if episodes_since_last_ref is not None
            else config.STALE_THREAD_EPISODES,
            current_episode=current_episode,
        )

    def get_episode_summary(self, episode_number: int) -> str:
        return self.structured_store.get_episode_summary(episode_number)

    def get_recent_context(self, n_episodes: int | None = None) -> str:
        """Summaries of the last N episodes, oldest first, for context injection."""
        n = n_episodes if n_episodes is not None else config.RECENT_EPISODE_CONTEXT
        summaries = self.structured_store.recent_episode_summaries(n)
        if not summaries:
            return NOTHING_YET
        return "\n\n".join(f"### Episode {number}\n{text}" for number, text in summaries)

    # ======================================================================
    # CONTEXT PACKETS (§4.5)
    # ======================================================================

    def build_continuity_brief(self) -> str:
        """Tier 1: exactly where the previous episode left off.

        The summary of an episode says what happened; this is the prose itself,
        so the Director can open on the same room, the same mood and the same
        unfinished sentence rather than restarting the story.
        """
        closing = self.structured_store.get_episode_closing()
        if closing is None:
            return ""
        number, passage = closing
        return (
            f"Episode {number} ended here — this is its final passage, verbatim:\n\n"
            f"{passage}\n\n"
            "Scene 1 of this episode must follow on from that moment: the same "
            "place or a clearly motivated move from it, the same emotional "
            "temperature, and the immediate consequence of whatever just happened."
        )

    def build_director_context(
        self, characters: Mapping[str, CharacterProfile], episode: Episode | None = None
    ) -> str:
        """What the Director needs, in three tiers.

        The tiers are ordered by how binding they are, and labelled so the model
        can tell the difference: what it must pick up from, what it should stay
        consistent with, and what it may draw on.
        """
        if self.is_empty():
            return NOTHING_YET

        sections = []

        brief = self.build_continuity_brief()
        if brief:
            sections.append("## Tier 1 — Where The Last Episode Left Off (pick up from here)\n" + brief)

        sections.append(
            f"## Tier 2 — The Story So Far (stay consistent with this)\n"
            f"{self.get_recent_context(ARC_EPISODES)}"
        )

        active = self.get_active_plot_threads()
        sections.append(
            "## Active Plot Threads (떡밥)\n"
            + (context.format_bullets(t.summary_line() for t in active) if active else NOTHING_YET)
        )

        current = episode.episode_number if episode else None
        stale = self.get_stale_plot_threads(current_episode=current)
        if stale:
            sections.append(
                "## Threads Going Cold\n"
                "These have not been touched in a while. Weave one back in if the "
                "storyline allows it.\n"
                + context.format_bullets(t.summary_line() for t in stale)
            )

        graph = self._relationship_graph(characters)
        if graph:
            sections.append(f"## Character Relationships (current state)\n{graph}")

        if episode is not None:
            relevant = self.recall_for_episode(episode, characters)
            if relevant:
                sections.append(
                    "## Tier 3 — Past Events This Episode Touches (draw on these)\n"
                    + context.format_bullets(relevant)
                )

        return "\n\n".join(sections)

    def recall_for_episode(
        self,
        episode: Episode,
        characters: Mapping[str, CharacterProfile] | None = None,
        top_k: int = DIRECTOR_MEMORIES,
    ) -> list[str]:
        """Tier 3: semantic recall, asked several ways rather than once.

        One query against the author's outline finds what the outline already
        says. The episode also needs what it does *not* say — what these
        characters have been through, and what the open threads were about — so
        each is asked separately and the results are merged nearest-first.
        """
        queries = [episode.author_storyline]
        if characters:
            # Names, not ids: the stored documents are prose about people.
            queries.append(" ".join(c.name for c in characters.values()))
        queries.extend(thread.description for thread in self.get_active_plot_threads()[:3])

        best: dict[str, tuple[float, Memory]] = {}
        for query in queries:
            if not query or not query.strip():
                continue
            for found in self.vector_store.search(query, top_k=top_k):
                # A memory that several queries reach is kept at its best score,
                # which is what floats it above one that only matched narrowly.
                distance = found.distance if found.distance is not None else float("inf")
                if found.id not in best or distance < best[found.id][0]:
                    best[found.id] = (distance, found)

        ordered = sorted(best.values(), key=lambda item: item[0])
        return [memory.render() for _, memory in ordered[:top_k]]

    def build_character_context(
        self, character: CharacterProfile, scene: Scene, characters: Mapping[str, CharacterProfile]
    ) -> str:
        """What this character personally remembers, and how they feel right now."""
        state = self.get_character_state(character.id)
        recalled = self.get_relevant_memories(
            f"{scene.objective} {scene.title}",
            character_id=character.id,
            top_k=CHARACTER_MEMORIES,
        )

        if not recalled and not state.internal_state and not state.current_goals:
            return NOTHING_YET

        sections = [f"## Your Memory ({character.name})"]
        sections.append(
            "Recent events you remember:\n"
            + (context.format_bullets(recalled) if recalled else NOTHING_YET)
        )
        if state.internal_state:
            sections.append(f"Your current emotional state: {state.internal_state}")
        if state.current_goals:
            sections.append(
                "What you are chasing right now:\n" + context.format_bullets(state.current_goals)
            )

        present = set(scene.participating_character_ids) - {character.id}
        changed = [r for r in state.relationship_updates if r.target_character_id in present]
        if changed:
            sections.append(
                "How you feel about the others here now (this supersedes your original sheet):\n"
                + context.format_bullets(
                    f"{characters[r.target_character_id].name if r.target_character_id in characters else r.target_character_id}"
                    f" — {r.type}, sentiment {r.sentiment:+.1f}"
                    + (f": {r.description}" if r.description else "")
                    for r in changed
                )
            )
        return "\n\n".join(sections)

    def build_writer_context(self, scene: Scene, previous_episode: int | None = None) -> str:
        """Voice continuity plus the callbacks a reader would expect the prose to make."""
        sections = []

        sample = self._previous_prose_sample(previous_episode)
        if sample:
            sections.append(
                "## Established Prose Tone\n"
                "The end of the previous episode. Match its voice, not its content.\n\n"
                + sample
            )

        references = self.get_relevant_memories(
            f"{scene.objective} {scene.title}", top_k=WRITER_MEMORIES
        )
        if references:
            sections.append(
                "## Relevant Past References\n"
                "The reader remembers these. Echo them where it is natural; do not explain them.\n"
                + context.format_bullets(references)
            )

        return "\n\n".join(sections) if sections else NOTHING_YET

    # ======================================================================
    # Internals
    # ======================================================================

    def is_empty(self) -> bool:
        """True when nothing has been recorded — the first episode of a story."""
        return not self.structured_store.get_story().episode_summaries

    def _apply_thread_updates(
        self, memory: EpisodeMemory, episode: int
    ) -> tuple[list[str], list[str]]:
        opened, resolved = [], []
        for update in memory.thread_updates:
            existing = self.plot_tracker.get(update.id)
            if update.action == "open" or existing is None:
                if existing is None:
                    self.plot_tracker.open(
                        PlotThread(
                            id=update.id,
                            name=update.name or update.id.replace("_", " "),
                            description=update.description or update.event,
                            opened_in_episode=episode,
                            linked_characters=update.linked_characters,
                        )
                    )
                    opened.append(update.id)
                if update.action == "open":
                    continue
            if update.action == "progress":
                self.plot_tracker.progress(update.id, update.event or update.description, episode)
            elif update.action == "resolve":
                self.plot_tracker.resolve(
                    update.id, update.resolution or update.event or "resolved", episode
                )
                resolved.append(update.id)
        return opened, resolved

    def _thread_id(self, thread_name: str) -> str:
        if self.plot_tracker.get(thread_name) is not None:
            return thread_name
        for thread in self.plot_tracker.all():
            if thread.name == thread_name:
                return thread.id
        return _slug(thread_name)

    def _relationship_graph(self, characters: Mapping[str, CharacterProfile]) -> str:
        """Every character's current stance on every other, from memory not the sheet."""
        lines = []
        for character_id in sorted(characters):
            state = self.get_character_state(character_id)
            if not state.relationship_updates:
                continue
            name = characters[character_id].name
            for relationship in state.relationship_updates:
                target = characters.get(relationship.target_character_id)
                target_name = target.name if target else relationship.target_character_id
                lines.append(
                    f"{name} -> {target_name}: {relationship.type}, "
                    f"sentiment {relationship.sentiment:+.1f}"
                    + (f" ({relationship.description})" if relationship.description else "")
                )
        return context.format_bullets(lines) if lines else ""

    def _previous_prose_sample(self, previous_episode: int | None) -> str:
        """The tail of an earlier episode's prose, for the Writer to match.

        The recorded closing passage is real prose; the stored summary is not,
        and handing the Writer a summary to "match the voice of" teaches it to
        write summaries. So the summary is only a fallback for episodes recorded
        before closings were kept.
        """
        closing = self.structured_store.get_episode_closing(previous_episode)
        if closing is not None:
            return closing[1]

        summaries = self.structured_store.get_story().episode_summaries
        if previous_episode is None:
            previous_episode = max(summaries, default=None)
        if previous_episode is None:
            return ""
        entry = self.vector_store.get_episode_summary(previous_episode)
        if entry is None:
            return ""
        words = entry.document.split()
        return " ".join(words[-STYLE_SAMPLE_WORDS:])


def _interactions_by_character(
    records: Iterable[InteractionRecord],
) -> dict[str, list[InteractionRecord]]:
    """Fan each record out to everyone who took part in it."""
    grouped: dict[str, list[InteractionRecord]] = {}
    for record in records:
        for participant in record.participants:
            grouped.setdefault(participant, []).append(record)
    return grouped


def _slug(name: str) -> str:
    return "_".join(name.lower().split())
