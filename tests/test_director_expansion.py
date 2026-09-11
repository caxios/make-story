"""The Director must drop nothing, and must expand what is too thin.

Both failures look the same from the outside — a short, flat chapter — but they
have opposite causes: one collapses the author's beats into the climax, the
other has too few beats to work with. The prompt has to carry a rule for each,
and these assert the rules are actually in the prompt the model receives, and
that whatever it returns survives validation intact.
"""

from __future__ import annotations

from storyweaver.agents import director
from storyweaver.agents.director import DirectorOutput, DraftScene
from storyweaver.models import Episode

MULTI_BEAT = (
    "(1) 연회장에서 말포이와 시비가 붙음 -> "
    "(2) 스네이프 교수에게 걸려 감점을 받음 -> "
    "(3) 기숙사로 돌아와 복수를 다짐함"
)

SINGLE_SENTENCE = "해리가 비밀의 방 입구를 찾아 기숙사를 몰래 빠져나온다."


def _episode(storyline: str) -> Episode:
    return Episode(episode_number=4, author_storyline=storyline)


def _drafts(*titles: str, character_id: str) -> DirectorOutput:
    return DirectorOutput(
        scenes=[
            DraftScene(
                title=title,
                objective=f"Accomplish {title}",
                participating_character_ids=[character_id],
            )
            for title in titles
        ]
    )


# ==========================================================================
# The prompt carries both rules
# ==========================================================================


def test_the_prompt_forbids_collapsing_the_authors_beats(world, harry, hermione):
    prompt = director.build_prompt(_episode(MULTI_BEAT), world, [harry, hermione])

    # The rule itself, and the author's beats intact for it to apply to.
    assert "Drop Nothing" in prompt
    assert "at least one dedicated scene" in prompt
    assert "말포이" in prompt
    assert "스네이프" in prompt
    assert "복수" in prompt


def test_the_prompt_tells_the_director_how_to_expand_a_sparse_outline(
    world, harry, hermione
):
    prompt = director.build_prompt(_episode(SINGLE_SENTENCE), world, [harry, hermione])

    assert "Expand A Sparse Outline" in prompt
    # The four-beat arc, each step nameable in the prompt.
    for step in ("aftermath", "Inciting movement", "core event", "Falling action"):
        assert step in prompt


def test_the_scene_budget_matches_a_korean_web_novel_chapter(world, harry, hermione):
    """3–4 developed scenes is what 4,500–5,500자 carries."""
    prompt = director.build_prompt(_episode(SINGLE_SENTENCE), world, [harry, hermione])

    assert director.DEFAULT_MIN_SCENES == 3
    assert director.DEFAULT_MAX_SCENES == 4
    assert "3–4 scenes" in prompt


def test_the_prompt_tells_it_to_continue_rather_than_restart(world, harry, hermione):
    prompt = director.build_prompt(
        _episode(SINGLE_SENTENCE),
        world,
        [harry, hermione],
        memory_context="Episode 3 ended with Harry alone in the corridor.",
    )

    assert "Continue, Do Not Restart" in prompt
    assert "Episode 3 ended with Harry alone in the corridor." in prompt


# ==========================================================================
# What comes back survives intact
# ==========================================================================


def test_every_beat_of_a_multi_event_outline_keeps_its_own_scene(
    world, harry, hermione, scripted_llm
):
    """Three authored events, three scenes — numbered in order, none merged."""
    llm = scripted_llm(
        DirectorOutput=lambda prompt, index: _drafts(
            "연회장의 시비", "스네이프의 감점", "기숙사의 다짐", character_id=harry.id
        )
    )

    scenes = director.decompose_episode(
        _episode(MULTI_BEAT), world, [harry, hermione], llm=llm
    )

    assert [s.title for s in scenes] == ["연회장의 시비", "스네이프의 감점", "기숙사의 다짐"]
    assert [s.scene_number for s in scenes] == [1, 2, 3]


def test_a_single_sentence_outline_still_yields_a_full_arc(
    world, harry, hermione, scripted_llm
):
    llm = scripted_llm(
        DirectorOutput=lambda prompt, index: _drafts(
            "기숙사의 밤", "복도의 인기척", "2층 화장실", "돌아오는 길",
            character_id=harry.id,
        )
    )

    scenes = director.decompose_episode(
        _episode(SINGLE_SENTENCE), world, [harry, hermione], llm=llm
    )

    assert len(scenes) == 4
    # Distinct objectives: four scenes that accomplish the same thing are one scene.
    assert len({s.objective for s in scenes}) == 4


def test_the_scene_budget_reaches_the_model(world, harry, scripted_llm):
    """The caller's min/max must appear in the prompt, not just in the defaults."""
    seen: list[str] = []

    def capture(prompt, index):
        seen.append(prompt)
        return _drafts("Only scene", character_id=harry.id)

    director.decompose_episode(
        _episode(SINGLE_SENTENCE),
        world,
        [harry],
        llm=scripted_llm(DirectorOutput=capture),
        min_scenes=2,
        max_scenes=6,
    )

    assert "2–6 scenes" in seen[0]
