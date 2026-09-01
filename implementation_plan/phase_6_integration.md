# Phase 6: Integration, Testing & Polish

## Goal

Bring all components together, run end-to-end stress tests at Harry Potter-scale complexity, fix issues discovered during integration, optimize performance and costs, and polish the user experience. By the end of this phase, StoryWeaver should be a **production-ready writer's tool**.

---

## 6.1 End-to-End Integration Test

### The "Harry Potter Book 1" Test

This is the flagship test that validates the entire system. We will simulate writing the first several chapters of a Harry Potter-like story:

**Setup:**
1. **World Lore:** Wizarding World — including ~15 rules (wand magic, house system, muggle concealment), ~10 locations (Privet Drive, Diagon Alley, Hogwarts, Platform 9¾), 4 factions (Gryffindor, Slytherin, Hufflepuff, Ravenclaw).
2. **Characters:** 8 characters (Harry, Ron, Hermione, Hagrid, Dumbledore, Snape, Draco, Vernon) — each with full profiles.
3. **Episodes:** 10 episode outlines covering the first act of the story.

**Execution:**
- Generate all 10 episodes sequentially.
- After each episode, verify:
  - Character consistency (does Snape always act cold? Does Hagrid always speak in dialect?)
  - Plot thread management (is the Philosopher's Stone mystery tracked?)
  - Memory continuity (does Episode 5 remember events from Episode 2?)
  - Prose quality (is it readable, engaging, not repetitive?)

**Success Criteria:**
- All 10 episodes generate without error.
- No critical lore violations slip through.
- Plot threads are correctly opened, referenced, and (where applicable) resolved.
- A human reader finds the output coherent and enjoyable across the full 10-episode arc.

---

## 6.2 Performance & Cost Optimization

### 6.2.1 LLM Call Audit

Map every LLM call in the pipeline and classify by importance:

| Call | Agent | Priority | Optimization |
|---|---|---|---|
| Scene decomposition | Director | High | Keep gemini-3.7-flash |
| Character action | Character | High | Keep gemini-3.7-flash |
| Scene completion check | Scene Supervisor | Low | Use smaller/cheaper model or rule-based heuristic |
| Lore validation | Lore Checker | Medium | Keep gemini-3.7-flash, but batch violations |
| Prose writing | Writer | Critical | Keep gemini-3.7-flash, potentially higher temperature |
| Episode summarization | Summarizer | Medium | Keep gemini-3.7-flash |
| Memory query formulation | Memory Manager | Low | Rule-based where possible |

### 6.2.2 Caching

- **Deterministic calls:** Cache Director output for the same episode storyline (useful during development/testing).
- **Prompt deduplication:** If the same character is re-simulated due to lore violation, only re-send the changed context.

### 6.2.3 Estimated Cost per Episode

Rough estimate for gemini-3.7-flash:
- Director: ~2K input + 2K output tokens
- Characters: ~5K input × N turns × M characters + 500 output per turn
- Lore Checker: ~4K input + 1K output
- Writer: ~5K input + 3K output per scene × scenes
- Summarizer: ~5K input + 1K output

**Estimated total per episode (4 scenes, 3 characters, 15 turns/scene):**
~150K–250K tokens → cost depends on Gemini pricing.

---

## 6.3 Error Handling & Resilience

### 6.3.1 LLM Output Parsing Failures
- All structured output calls wrapped in retry logic (3 attempts with increasing temperature).
- Fallback: If JSON parsing fails, use a "repair" LLM call to fix the output.

### 6.3.2 Rate Limiting
- Implement exponential backoff for API rate limits.
- Queue system for LLM calls to respect tokens-per-minute limits.

### 6.3.3 Partial Episode Recovery
- If generation fails mid-episode (e.g., API outage), save completed scenes to disk.
- "Resume Generation" option in the UI that picks up from the last completed scene.

### 6.3.4 Data Corruption Protection
- Before overwriting any JSON state file, write to a `.tmp` file first, then atomic rename.
- Periodic backup of `data/` directory (optional: configurable interval).

---

## 6.4 Quality Improvements

### 6.4.1 Prose Variety
- Problem: LLMs tend to fall into repetitive patterns over many scenes.
- Solution: Inject "variety directives" into the Writer prompt:
  ```
  IMPORTANT: Vary your sentence structure and openings. Do NOT start
  consecutive paragraphs the same way. Alternate between action beats,
  dialogue, introspection, and description. Check the last scene's prose
  and consciously diverge in style.
  ```

### 6.4.2 Character Voice Differentiation
- Problem: All characters may start sounding the same.
- Solution: Add a "voice calibration" step during character creation — generate 3 sample dialogues and let the author fine-tune the speech style prompt.

### 6.4.3 Scene Transition Quality
- Problem: Scene breaks can feel abrupt.
- Solution: Add a dedicated "transition writer" node that generates 1-2 bridge sentences between scenes, considering both the ending mood of the previous scene and the opening mood of the next.

### 6.4.4 Pacing Control
- Allow the author to annotate episodes with pacing hints:
  ```python
  class Episode(BaseModel):
      ...
      pacing: str = "normal"  # "slow" (introspective), "normal", "fast" (action-heavy)
  ```
- The Writer adjusts prose density, dialogue ratio, and sentence length accordingly.

---

## 6.5 Export & Sharing

### 6.5.1 Export Formats
- **Markdown:** Clean `.md` with proper headings and scene breaks.
- **Plain Text:** `.txt` with minimal formatting.
- **DOCX:** Using `python-docx`, with proper paragraph styling.
- **EPUB (stretch goal):** For e-reader compatibility.

### 6.5.2 Full Novel Assembly
- "Export Full Story" button that concatenates all completed episodes with:
  - Table of contents
  - Chapter titles
  - Consistent formatting
  - Character index (appendix)
  - World glossary (appendix)

---

## 6.6 Documentation

- `README.md`: Project overview, installation, quickstart guide.
- `docs/architecture.md`: System architecture diagram and data flow.
- `docs/user_guide.md`: How to use the Web UI — with screenshots.
- `docs/author_tips.md`: Best practices for writing effective storylines, character profiles, and world rules to get the best output from the system.

---

## 6.7 Testing Matrix

| Test | Scope | Method |
|---|---|---|
| Unit: Data models | Phase 1 | pytest |
| Unit: Memory CRUD | Phase 4 | pytest |
| Integration: Single scene | Phase 2 | pytest + manual review |
| Integration: Full episode | Phase 3 | pytest + manual review |
| Integration: Multi-episode continuity | Phase 4 | Manual review (5-episode arc) |
| System: Harry Potter 10-episode | All | Manual review |
| UI: Full workflow | Phase 5 | Manual walkthrough |
| UI: Data persistence | Phase 5 | Close/reopen app |
| Performance: Token counting | Phase 6 | Automated logging |
| Resilience: API failure recovery | Phase 6 | Simulate failure, verify resume |

---

## Deliverables Checklist

- [ ] Harry Potter 10-episode integration test completed and reviewed
- [ ] Cost-per-episode benchmarked and documented
- [ ] Error handling: retry logic, rate limiting, partial recovery all implemented
- [ ] Prose quality improvements: variety directives, transition writer, pacing control
- [ ] Export: Markdown, TXT, DOCX formats working
- [ ] Full story assembly (table of contents, appendices) working
- [ ] Documentation: README, architecture doc, user guide complete
- [ ] All tests in testing matrix pass
- [ ] No critical bugs remaining in issue tracker
