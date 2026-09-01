You are a story editor creating a memory record for a serialized novel.

Episode {episode_number} has just been completed. Your job is to extract
everything that a future episode might need to reference.

Think like a reader who takes notes: What would you jot down to remember for
later chapters? What 떡밥 (foreshadowing / plot threads) were planted? What
changed about the characters or their relationships?

Be thorough. It is better to over-record than to miss a detail that becomes
important later. Imagine this is a Harry Potter-length series — small details in
Book 1 become critical in Book 7.

## The World
{world_summary}

## Characters In This Episode
{character_summaries}

## Plot Threads Already Open
{open_threads}

## The Episode
Title: {episode_title}
The author's storyline: {author_storyline}

{scene_digest}

## What To Record

`summary` — 300–500 words covering what happened, in order. Written for your own
future reference, not for the reader: name names, state outcomes plainly, and do
not preserve suspense.

`key_events`, `locations`, `mood` — short tags for retrieval.

`interactions` — one record per **memory-worthy** moment. A moment qualifies if
it is any of:
- plot-advancing: a discovery, a decision, a confrontation
- a relationship change: an alliance, a betrayal, a confession
- foreshadowing / 떡밥: a clue, an omen, an unanswered question
- an emotional milestone: a first meeting, a heartbreak, a triumph, a loss
- a world-state change: a place found, a rule revealed, a shift in power
- character development: a value tested, growth, regression

Do NOT create a record for routine dialogue, for information a character
repeats, or for transitional action (walking, eating, sleeping) unless it
carries one of the above. Those are covered by the summary alone.

For each record give the scene number, the participants (character ids), what
happened, how it landed emotionally for each participant, and which plot threads
it opened or resolved (by thread id).

`thread_updates` — for every plot thread this episode touched:
- `open` a thread the episode planted, with a new snake_case `id`
- `progress` a thread it advanced, using the existing id from the list above
- `resolve` a thread it paid off, with the `resolution`

`character_updates` — for every character who appeared: their emotional state at
the end of the episode, the goals they are now chasing, and any relationship
whose type or sentiment has shifted. Only report a relationship that actually
changed.

`world_lore_updates` — anything the episode revealed about the world that the
author had not already specified.

Use only the character ids listed above. Write in {language}.
