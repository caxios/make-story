/**
 * The domain, mirrored from the Python Pydantic models.
 *
 * These are the wire format, so they follow `src/storyweaver/models/` field for
 * field — snake_case included. Where the backend has `X | None`, the type here
 * is `X | null`, because that is what JSON delivers; where it has a
 * `default_factory=list`, the field is required and possibly empty, never
 * optional. Anything that drifts from this file is a bug on one side or the
 * other, not a difference of opinion.
 */

// ==========================================================================
// World  —  models/world.py
// ==========================================================================

export interface Rule {
  id: string
  category: string
  statement: string
  exceptions: string[]
}

export interface Location {
  id: string
  name: string
  description: string
  parent_location_id: string | null
  notable_features: string[]
}

export interface WorldLore {
  title: string
  genre: string
  tone: string
  era: string | null
  overview: string
  rules: Rule[]
  locations: Location[]
  /** Faction names. The backend stores plain strings, not objects. */
  factions: string[]
  additional_lore: Record<string, string>
}

/** One row of `GET /api/world/locations/tree`: the hierarchy, flattened. */
export interface LocationTreeRow {
  depth: number
  location: Location
}

// ==========================================================================
// Characters  —  models/character.py
// ==========================================================================

export interface Trait {
  name: string
  /** 0.0 – 1.0 */
  intensity: number
  description: string | null
}

export interface Relationship {
  target_character_id: string
  /** "friend", "rival", "mentor", … */
  type: string
  /** -1.0 (hatred) – 1.0 (love) */
  sentiment: number
  description: string | null
}

export interface CharacterProfile {
  id: string
  name: string
  /** Where they stand in the story: "protagonist", "antagonist", … Free text. */
  role: string
  aliases: string[]
  age: number | null
  gender: string | null
  appearance: string
  personality_summary: string
  traits: Trait[]
  /** Free text: dialect, formality, verbal habits. */
  speech_style: string
  values: string[]
  goals: string[]
  backstory: string
  relationships: Relationship[]
  secrets: string[]
  /** Meta-notes, never shown to the model as character knowledge. */
  author_notes: string
}

/** `GET /api/characters/graph`, shaped for a force-directed view. */
export interface CharacterGraphNode {
  id: string
  label: string
  /** Derived from the strongest trait — not an authored field. */
  role: string
  degree: number
}

export interface CharacterGraphEdge {
  source: string
  target: string
  type: string
  sentiment: number
  description: string
}

export interface CharacterGraph {
  nodes: CharacterGraphNode[]
  edges: CharacterGraphEdge[]
}

// ==========================================================================
// Episodes  —  models/episode.py
// ==========================================================================

export type InteractionType = 'dialogue' | 'action' | 'thought' | 'reaction'

export interface InteractionEntry {
  turn: number
  character_id: string
  type: InteractionType
  content: string
  directed_at: string | null
}

export interface StoryBeat {
  description: string
  involved_character_ids: string[]
  location_id: string | null
  mood: string | null
}

export interface Scene {
  scene_number: number
  title: string
  location_id: string | null
  participating_character_ids: string[]
  objective: string
  beats: StoryBeat[]
  /** Rendered one-line turns, filled in by the character simulation. */
  interaction_log: string[]
  /** Filled in by the Writer. */
  prose: string
}

export type EpisodeStatus = 'queued' | 'in_progress' | 'completed'
export type Pacing = 'slow' | 'normal' | 'fast'

export interface Episode {
  episode_number: number
  title: string
  author_storyline: string
  scenes: Scene[]
  final_text: string
  summary: string
  status: EpisodeStatus
  pacing: Pacing
}

// ==========================================================================
// Style  —  models/style.py
// ==========================================================================

export type Perspective =
  | 'third_person_limited'
  | 'third_person_omniscient'
  | 'first_person'

export type ProseDensity = 'sparse' | 'moderate' | 'lush'
export type Tense = 'past' | 'present'

export interface WritingStyle {
  perspective: Perspective
  pov_character_id: string | null
  tense: Tense
  prose_density: ProseDensity
  /** 0.0 – 1.0 */
  dialogue_ratio: number
  target_word_count_per_scene: number
  /** ISO-ish language code the prose is written in. */
  language: string
  author_style_notes: string
}

// ==========================================================================
// Project  —  ui/project.py
// ==========================================================================

export interface Project {
  name: string
  world: WorldLore
  characters: CharacterProfile[]
  episodes: Episode[]
  style: WritingStyle
}

export interface ProjectStats {
  episodes_total: number
  episodes_completed: number
  episodes_queued: number
  total_words: number
  character_count: number
  open_thread_count: number
  /** False when ChromaDB did not start; the thread count is then 0, not wrong. */
  memory_available: boolean
  memory_error: string
}

// ==========================================================================
// Memory  —  memory/plot_tracker.py, memory/vector_store.py
// ==========================================================================

export type ThreadStatus = 'open' | 'progressing' | 'resolved'

/** A 떡밥: a question the story has raised and not yet paid off. */
export interface PlotThread {
  id: string
  name: string
  description: string
  status: ThreadStatus
  opened_in_episode: number
  last_referenced_episode: number
  resolved_in_episode: number | null
  linked_characters: string[]
  events: string[]
  resolution: string | null
}

export interface PlotThreads {
  active: PlotThread[]
  resolved: PlotThread[]
  /** A subset of `active`: quiet long enough to read as dropped. */
  stale: PlotThread[]
  stale_after_episodes: number
}

export interface MemoryHit {
  id: string
  document: string
  /** The document with its episode number prefixed, as a prompt would quote it. */
  rendered: string
  collection: string
  episode_number: number
  metadata: Record<string, unknown>
  /** Chroma's distance — smaller is closer. Null when the store did not report one. */
  distance: number | null
  /** The same thing the way round a reader expects: 1.0 is a perfect match. */
  relevance: number | null
}

export interface MemorySearchResult {
  query: string
  results: MemoryHit[]
}

export interface MemoryStatus {
  available: boolean
  error: string
  collections: Record<string, number>
  is_empty?: boolean
}

export interface CharacterMemoryState {
  character_id: string
  interaction_history: unknown[]
  relationship_updates: Relationship[]
  internal_state: string
  current_goals: string[]
  last_updated_episode: number
}

// ==========================================================================
// Generation  —  api/generation.py (Server-Sent Events)
// ==========================================================================

export interface UsageReport {
  calls: number
  total_tokens: number
  /** The per-stage breakdown, already formatted for display. */
  report: string
}

export interface GenerationStartEvent {
  episode_number: number
  title: string
  /** Set when a checkpoint survived an earlier run and is being picked up. */
  resuming_from_scene: number | null
  memory_available: boolean
}

/** The pipeline stages, in the order they happen. */
export type GenerationStage =
  | 'planning'
  | 'simulating'
  | 'checking'
  | 'writing'
  | 'assembling'
  | 'recording'

/** What the scene in flight is about. Null before the Director has planned. */
export interface GenerationSceneDetail {
  number: number
  title: string
  objective: string
  /** Character names, not ids. */
  characters: string[]
}

export interface GenerationProgressEvent {
  /** The pipeline node that just finished, e.g. "write_scene". */
  node: string
  /** That node's stage, for the stepper. Empty for bookkeeping nodes. */
  stage: GenerationStage | ''
  current_scene: number
  total_scenes: number
  /** What is happening now, phrased for a human. */
  label: string
  /** What just finished. */
  summary: string
  /** 0.0 – 1.0, rough. */
  fraction: number
  checklist: string[]
  scene: GenerationSceneDetail | null
  /** Turns simulated in this scene so far, against the cap. */
  turns: number
  max_turns: number
  /** How many times the Lore Checker has sent this scene back. */
  retry_count: number
  /** Spent so far on this episode. */
  tokens: number
  calls: number
}

export interface GenerationCompleteEvent {
  episode: Episode
  words: number
  scenes: number
  checklist: string[]
  recorded_to_memory: boolean
  usage: UsageReport | null
}

export interface GenerationErrorEvent {
  episode_number: number
  message: string
  type: string
  /** True when the finished scenes were checkpointed and can be resumed. */
  resumable: boolean
  scenes_completed: number
  usage: UsageReport | null
}

export interface PendingGeneration {
  episode_number: number
  current_scene_index: number
  scenes_completed: number
}

// ==========================================================================
// Telemetry  —  api/telemetry.py
// ==========================================================================

export interface TelemetryRun {
  at: string
  episode_number: number
  calls: number
  input_tokens: number
  output_tokens: number
  seconds: number
  cost: number
  estimated: boolean
  by_stage: Record<string, number>
}

export interface Telemetry {
  model: string
  api_key_configured: boolean
  temperature: number
  max_output_tokens: number
  input_cost_per_mtok: number
  output_cost_per_mtok: number
  runs: number
  calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  seconds: number
  cost: number
  /** True when any run had to estimate: the totals are then a floor. */
  estimated: boolean
  by_stage: Record<string, number>
  recent: TelemetryRun[]
}

export interface Health {
  status: string
  version: string
  api_version: string
  model: string
  api_key_configured: boolean
  memory_available: boolean
  memory_error: string
  data_dir: string
}
