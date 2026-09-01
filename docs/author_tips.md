# Author tips

How to get good output from StoryWeaver. Most of what makes a chapter work is
decided before you press Generate — in the rules, the speech styles, and the
outline. This is what to put where.

---

## World rules

**A rule is only useful if it can be broken.** The Lore Checker validates every
scene against your rules and re-runs the turns that violate one. "The world is
magical" can never be violated, so it never catches anything. "Deliberate magic
requires a wand" catches a character waving a hand.

Good rules are specific, testable, and constrain *characters*:

> Students may not perform magic outside school during the holidays, and the
> Ministry detects when they do.

**Write the exceptions.** They are how you keep the interesting scene without a
false positive. The rule above has one that matters enormously:

> Detection is by location, not by person, so it cannot tell a child from an
> adult in a wizarding house.

**Ten to fifteen rules is plenty.** Past that they compete for attention in the
prompt and the marginal ones dilute the load-bearing ones. Prefer few rules that
constrain everything to many that constrain one scene each.

**Rules are for consequences, not decoration.** "Gringotts is run by goblins"
belongs in Additional lore. "Gringotts vaults are guarded by charms that trap
thieves inside" is a rule, because a character can be caught by it.

---

## Characters

**Speech style is the single highest-leverage field.** It is quoted to the
character every turn and the Writer is told to preserve it exactly. Write it so
that you could pick the character out of an unlabelled transcript.

Weak:

> Talks like a schoolboy.

Strong:

> Casual and slangy, full of 'blimey' and 'mental'. Blurts things out and then
> regrets them. Explains the wizarding world as if everyone already knows it.

Name the register, the tics, the rhythm, and one habit. Three specifics beat a
paragraph of adjectives.

**Personality summary should contain a tension.** A character who is only brave
has one move. A character who is brave *and* certain he does not deserve to be
has a scene in every situation.

> Warm, funny and fiercely loyal, with a streak of insecurity about being the
> sixth son of a family that has already done everything first.

**Traits earn their intensity.** The number reaches the prompt, so 0.9 reads
louder than 0.4. Do not set everything to 0.9 — a character whose every trait is
maximal is a character with no shape. Three to five traits is right.

**Goals must be current and achievable-ish.** "Defeat the dark lord" gives the
agent nothing to do this Tuesday. "Find out who his parents really were" produces
a question in nearly any scene.

**Secrets are for dramatic irony.** They go into that character's own prompt with
an instruction not to reveal them unless the story demands it, and are never
shown to the other characters. A secret nobody could plausibly discover is inert;
a secret that could slip out at any moment is a scene waiting to happen.

**Relationships are directed, and the sentiment is the part you tune.** "Rival"
tells you the shape; −0.3 tells you it is warming and −0.8 tells you it is not.
Give the nuance field the *reason*:

> Her corrections land on exactly the nerve he is trying to protect.

**Author notes are your instructions to the system.** Use them for the thing you
keep having to fix:

> The dialect is the character. Never let him speak in clean standard English,
> even when frightened.

---

## Episode outlines

**Rough is right.** The Director's job is to invent the connective tissue between
your beats. If you specify every scene, you have done the Director's job worse
than it would have.

Aim for three to six sentences that say: what must happen, roughly in what order,
and what the episode should end on.

> Snape's first lesson is an ambush aimed squarely at Harry, and Hermione's
> raised hand makes everything worse. Afterwards Hagrid tries to explain Snape
> away and lets slip that the third-floor corridor is about something being kept
> safe. Harry connects it to the vault Hagrid emptied.

**Name the ending.** "End on X" is the most useful sentence you can write. It
gives the Director something to build toward and stops episodes trailing off.

**Plant deliberately.** If you want a thread tracked across the story, put it in
an outline explicitly — "Hagrid also collects something small from a vault and
refuses to say what. Plant that vault." The Summarizer opens threads from what
happens, so make it happen.

**Do not write dialogue in the outline.** The characters will produce better
lines than your placeholder, and a quoted line in the outline tends to come back
verbatim and flat.

**Use pacing rather than fighting the prose.** An episode of people talking in a
room wants `slow`; a troll in a corridor wants `fast`. This is more effective
than asking for shorter sentences in the style notes.

---

## Style settings

**Set the POV character deliberately for limited perspective.** If you leave it
blank, the scene's opening character is used, which changes chapter to chapter.
That is fine for an ensemble and wrong for a single-POV novel.

**Dialogue ratio and word count are targets, not quotas.** The prompt says so.
Treat them as a nudge; if scenes come back consistently short, the outline is
probably thin rather than the number wrong.

**Style notes are for voice, not plot.** "Write like Diana Wynne Jones. Short
paragraphs. No adverbs in dialogue tags." Not "make sure Harry finds the
trapdoor" — that belongs in the outline.

---

## Reading the output

**When a scene feels wrong, read the interaction log first.** Reading Room →
Side by side shows what the characters actually did before the Writer got to it.
Almost every disappointing chapter is a disappointing log, and the fix is in the
character sheets or the outline — not in the style settings.

**When a character forgets something, search the memory.** Memory Inspector →
Search uses exactly the retrieval the agents use. If the memory does not surface
there, it never reached a prompt. Usually it was never recorded, which means the
Summarizer did not judge it memory-worthy — make it more consequential in the
outline.

**When a thread is dropped, look at Going Cold.** The Director is told about
threads untouched for five episodes, but it will not force one in if your
outline leaves no room. Name it in an outline to bring it back.

**⚠️ lore warnings are the system working.** They mean a violation was caught and
the turns re-run. Persistent warnings on the same rule usually mean the rule is
ambiguous, or that it needs an exception you have not written.

---

## Working economically

The Character agent is the overwhelming majority of the spend — roughly one call
per turn per scene. The levers, in order of effect:

1. **Lower the turn cap.** 12 is a reasonable default; 20 rarely produces a
   better scene than 12, it produces a longer one.
2. **Fewer characters per scene.** Three is a conversation, five is a queue.
   The Director takes its casting from your outline.
3. **Fewer scenes.** A tighter outline yields 3 scenes instead of 5.

Each generation reports its measured cost per stage. Look before you optimise —
the guess is usually wrong.

---

## A workflow that holds up over many episodes

1. Write the world and cast first. Do not start with one character intending to
   add more; relationships are what make scenes, and they need somebody to point
   at.
2. Queue three or four episodes before generating any. Reading them together
   catches arc problems early.
3. Generate one, read it, and fix the *inputs* rather than the output. A speech
   style corrected at episode 2 improves every episode after it; a hand-edited
   chapter improves one.
4. Check the Memory Inspector every few episodes. Threads going cold and
   relationships drifting somewhere you did not intend are both easier to fix
   early.
5. Back up the memory directory before any large change to the world or cast.
