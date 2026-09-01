# User guide

StoryWeaver is a writer's workbench. You supply the world, the cast, and a rough
outline per episode; it casts the scenes, plays them out in character, checks its
own continuity, and writes the chapter.

```bash
streamlit run src/storyweaver/ui/app.py
```

You need a `GOOGLE_API_KEY` in `.env` before anything will generate. **⚙️ Settings
→ Model & cost** tells you plainly whether it found one.

---

## Starting out

The fastest way to see the whole pipeline work is to load a bundled story:

**⚙️ Settings → Project → Start over**

- **Small sample** — 3 characters, 1 episode. Good for a first run.
- **The Wizarding World** — 8 characters, 15 rules, 10 locations, 10 episodes.
  This is the dataset the system is stress-tested against.

Then go to **📝 Episode Queue** and press Generate.

To start from nothing instead, work left to right: 🌍 World Builder → 👤
Character Workshop → 📝 Episode Queue.

---

## 🌍 World Builder

Everything here reaches every agent on every turn, so it is worth doing well.

**Overview** — title, genre, tone, era, and a few paragraphs of setting. This is
the first thing every agent reads.

**Rules** — the promises your world makes. These matter more than anything else
on this page: the Lore Checker validates every scene against them and re-runs the
turns that break one. A rule is a good rule when it can be *violated* — "magic
requires a wand" can be broken; "the world is magical" cannot.

Give each rule exceptions where they exist. An exception is how you get the
interesting scene without a false positive.

**Locations** — nest them with the *Inside* field, and the tree view shows the
hierarchy. Delete a parent and its children are re-parented rather than orphaned.

**Factions** and **Additional lore** — free-form; use them for anything the
structured fields have no room for.

---

## 👤 Character Workshop

**Identity** — appearance, personality, and *speech style*. Speech style is the
field that does the most work: it is quoted to the character every turn and the
Writer is told to preserve it exactly. Write it so you could recognise the
character from an unlabelled line.

> Broad West Country dialect written phonetically — 'yeh', 'ter', 'don' yeh
> worry'. Warm, rambling, trails off when he realises what he has let slip.

**Traits & goals** — intensity sliders reach the prompt as numbers, so 0.9 really
does read louder than 0.4. Goals are what the character is chasing *now*; the
memory layer updates them as the story moves.

**Relationships** — directed, so A's view of B is separate from B's view of A.
Sentiment runs from −1.0 to +1.0. The Mermaid graph shows the whole web.

**Secrets** — placed in that character's own prompt with an instruction not to
reveal them unless the story demands it, and never shown to the other characters.

**Clone** — start a new character from an existing one when they share a
background.

---

## 📝 Episode Queue

**Add an episode.** The storyline is the core input. Rough is right: give the
beats you care about and let the Director invent the connective tissue between
them. A good outline names what must happen and what the episode should end on.

> Snape's first lesson is an ambush aimed squarely at Harry, and Hermione's
> raised hand makes everything worse. Afterwards Hagrid tries to explain Snape
> away and lets slip that the third-floor corridor is about something being kept
> safe. End with Harry connecting it to the vault.

**Pacing** — `slow` (introspective), `normal`, or `fast` (action-heavy). This
adjusts sentence length, description, and how much room a moment gets.

**Batch add** — paste or upload several outlines separated by a line of `---`.

**Reorder** — the arrows renumber the queue, because episode 4 is whatever is
fourth.

### Generating

Press **Generate Episode N**. You will see the pipeline work:

```
✅ Planned 4 scenes
✅ Simulated scene 1/4 — 9 turns
✅ Lore check scene 1/4 — passed
✅ Wrote scene 1/4 — 1,423 words
⚠️ Lore check scene 2/4 — 1 violation, re-running
✅ Re-simulated scene 2/4 — 9 turns
🔄 Working on scene 2/4…
⬜ Scene 3/4
⬜ Assembling final text
```

A ⚠️ line is the system working, not failing: the Lore Checker found something
that breaks your world's rules and is re-running the offending turns with a
correction injected. It gives up after two attempts and accepts the scene with a
warning rather than looping.

**Turns per scene** is a cap, not a target. Scenes usually end earlier, when the
supervisor judges the objective met.

Afterwards, **What this cost** shows the measured token breakdown per stage.

### If it fails

An episode that fails partway — an outage, a rate limit that outlasts the
retries — keeps the scenes it already finished. Generating that episode again
picks up from the first unwritten scene, and does not pay the Director twice.

Editing the storyline discards the checkpoint, because a different storyline
means different scenes. **⚙️ Settings → Backups & recovery** lists anything
part-written, and lets you discard it.

---

## 📖 Reading Room

The prose, formatted the way a reader would meet it: serif type, generous
leading, scene breaks as dividers, dialogue lifted a shade from narration.

**Side by side** shows your original outline and the scene breakdown next to the
prose — including each scene's interaction log, which is what the characters
actually did before the Writer got to it. This is the view for working out *why*
a chapter went the way it did.

**Edit mode** lets you rewrite the text by hand. Your edits are saved to the
project and are what gets exported.

**Export** — this episode as `.txt`, `.md` or `.docx`, or the whole story as one
document with a table of contents, every chapter, and appendices for the cast and
the world.

---

## 🧠 Memory Inspector

**Plot threads** — every 떡밥 the Summarizer has opened, with its status, its
timeline, and whether it is going cold. A thread untouched for five episodes is
flagged, and the Director is told about it so it can be woven back in.

You can **Force resolve** a thread the story quietly settled, or **Reactivate**
one you want to reopen.

**Character memory** — what each character currently feels, what they are
chasing, how their relationships have moved from their original sheet, and every
interaction they were part of.

**Episode summaries** — the 300–500 word record of each episode, searchable.

**Search** — the same retrieval the agents use. If a memory does not surface
here, it will not reach a prompt either. This is the first place to look when a
character fails to remember something they should.

---

## ⚙️ Settings

**Writing style** — perspective, POV character, prose density, dialogue ratio,
target length, output language (한국어 by default), and free-form style notes.
These reach the Writer and nothing else: they change how the story is told, never
what happens in it.

**Model & cost** — the live configuration, the pricing costs are computed with,
and the retry policy. Model settings are read from `.env` at startup so a long
generation cannot have the model changed underneath it; the page shows you the
exact block to edit.

**Project** — export everything (world, cast, episodes, style, memory) as a ZIP,
import one back, or start over.

**Backups & recovery** — snapshot the memory directory before a risky change, and
manage part-written episodes.

---

## Where things live on disk

```
data/
  project.json      world, cast, episodes, style
  state/            character memory, story memory, plot threads, checkpoints
  chromadb/         the vector store
  examples/         the bundled datasets
```

Everything but `examples/` is gitignored. State files are written atomically, so
a crash cannot truncate them.

---

## Running without the UI

```bash
python -m storyweaver.smoke_test               # is the model binding working?
python -m storyweaver.demo_scene --two         # one scene, printed
python -m storyweaver.demo_episode --memory    # one episode, with continuity
python scripts/run_wizarding_world.py --episodes 10 --out build/
```

The last one is the full ten-episode arc, with a cost report per episode and
exports at the end.
