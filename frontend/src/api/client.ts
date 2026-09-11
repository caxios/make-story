/**
 * The typed REST client.
 *
 * One `request` does the work: it serializes, parses, and turns a failure into
 * an `ApiError` carrying the backend's own `detail` string — the messages there
 * are already written for an author ("This story has no world yet"), so they
 * are worth surfacing verbatim rather than replacing with "Request failed".
 */

import type {
  CharacterGraph,
  CharacterMemoryState,
  CharacterProfile,
  Episode,
  Health,
  Location,
  LocationTreeRow,
  MemorySearchResult,
  MemoryStatus,
  Pacing,
  PendingGeneration,
  PlotThreads,
  Project,
  ProjectStats,
  Rule,
  Telemetry,
  WorldLore,
  WritingStyle,
} from '@/types/storyweaver'

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal } = options

  let response: Response
  try {
    response = await fetch(path, {
      method,
      signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (cause) {
    // An aborted request is the caller changing its mind, not a failure.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError(0, 'Could not reach the StoryWeaver backend. Is it running?')
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response))
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** FastAPI reports errors as `{detail}`, but validation errors nest a list there. */
async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const { detail } = body
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item as { msg?: string }).msg)
        .filter((msg): msg is string => Boolean(msg))
      if (messages.length > 0) return messages.join('; ')
    }
  } catch {
    // Not JSON — fall through to the status line.
  }
  return `${response.status} ${response.statusText}`.trim()
}

/** A download the browser saves, rather than a payload we parse. */
async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(path)
  if (!response.ok) throw new ApiError(response.status, await readError(response))
  return {
    blob: await response.blob(),
    filename: filenameFrom(response.headers.get('content-disposition')),
  }
}

function filenameFrom(disposition: string | null): string {
  if (!disposition) return 'download'
  // `filename*=UTF-8''…` is the one that survives a Korean chapter title.
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (encoded?.[1]) return decodeURIComponent(encoded[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain?.[1] ?? 'download'
}

// ==========================================================================
// Meta
// ==========================================================================

export const getHealth = () => request<Health>('/api/health')

// ==========================================================================
// Project
// ==========================================================================

export const getProject = () => request<Project>('/api/project')

export const saveProject = (project: Project) =>
  request<Project>('/api/project', { method: 'PUT', body: project })

export const getStats = () => request<ProjectStats>('/api/project/stats')

/**
 * The writing style is part of the project, and the project is saved whole —
 * so a style change is a read-modify-write rather than its own endpoint.
 */
export async function saveStyle(style: WritingStyle): Promise<Project> {
  const project = await getProject()
  return saveProject({ ...project, style })
}

export async function renameProject(name: string): Promise<Project> {
  const project = await getProject()
  return saveProject({ ...project, name })
}

export const getTelemetry = () => request<Telemetry>('/api/telemetry')

// ==========================================================================
// World
// ==========================================================================

export interface WorldUpdate {
  title?: string
  genre?: string
  tone?: string
  era?: string | null
  overview?: string
  factions?: string[]
}

export const getWorld = () => request<WorldLore>('/api/world')

export const updateWorld = (update: WorldUpdate) =>
  request<WorldLore>('/api/world', { method: 'PUT', body: update })

export const upsertRule = (rule: Rule) =>
  request<WorldLore>('/api/world/rules', { method: 'POST', body: rule })

export const deleteRule = (ruleId: string) =>
  request<WorldLore>(`/api/world/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })

export const upsertLocation = (location: Location) =>
  request<WorldLore>('/api/world/locations', { method: 'POST', body: location })

export const deleteLocation = (locationId: string) =>
  request<WorldLore>(`/api/world/locations/${encodeURIComponent(locationId)}`, {
    method: 'DELETE',
  })

export const getLocationTree = () => request<LocationTreeRow[]>('/api/world/locations/tree')

// ==========================================================================
// Characters
// ==========================================================================

export const getCharacters = () => request<CharacterProfile[]>('/api/characters')

export const upsertCharacter = (character: CharacterProfile) =>
  request<CharacterProfile>('/api/characters', { method: 'POST', body: character })

export const deleteCharacter = (characterId: string) =>
  request<CharacterProfile[]>(`/api/characters/${encodeURIComponent(characterId)}`, {
    method: 'DELETE',
  })

export const cloneCharacter = (characterId: string, newId: string, newName: string) =>
  request<CharacterProfile>(`/api/characters/${encodeURIComponent(characterId)}/clone`, {
    method: 'POST',
    body: { new_id: newId, new_name: newName },
  })

export const getCharacterGraph = () => request<CharacterGraph>('/api/characters/graph')

// ==========================================================================
// Episodes
// ==========================================================================

export interface EpisodeUpdate {
  title?: string
  author_storyline?: string
  pacing?: Pacing
  status?: Episode['status']
  final_text?: string
  summary?: string
}

export const getEpisodes = () => request<Episode[]>('/api/episodes')

export const getEpisode = (episodeNumber: number) =>
  request<Episode>(`/api/episodes/${episodeNumber}`)

export const addEpisode = (authorStoryline: string, title = '', pacing: Pacing = 'normal') =>
  request<Episode>('/api/episodes', {
    method: 'POST',
    body: { author_storyline: authorStoryline, title, pacing },
  })

export const updateEpisode = (episodeNumber: number, update: EpisodeUpdate) =>
  request<Episode>(`/api/episodes/${episodeNumber}`, { method: 'PUT', body: update })

export const deleteEpisode = (episodeNumber: number) =>
  request<Episode[]>(`/api/episodes/${episodeNumber}`, { method: 'DELETE' })

/** `-1` moves the episode up the queue, `+1` moves it down. */
export const moveEpisode = (episodeNumber: number, offset: number) =>
  request<Episode[]>(`/api/episodes/${episodeNumber}/move`, {
    method: 'POST',
    body: { offset },
  })

export const addEpisodesBatch = (text: string, separator = '---') =>
  request<Episode[]>('/api/episodes/batch', { method: 'POST', body: { text, separator } })

/**
 * Re-read a finished chapter and rewrite its summary.
 *
 * This is a model call, so it is slow and it costs something — worth it after
 * editing prose by hand, because the summary is what the next episode is told
 * about this one.
 */
export const summarizeEpisode = (episodeNumber: number) =>
  request<Episode>(`/api/episodes/${episodeNumber}/summarize`, { method: 'POST' })

// ==========================================================================
// Generation
// ==========================================================================

export const getPendingGenerations = () =>
  request<PendingGeneration[]>('/api/generation/pending')

export const getRunningGenerations = () => request<number[]>('/api/generation/running')

/** The SSE endpoint. Opened by `useGenerationStream`, not by `fetch`. */
export const generationStreamUrl = (episodeNumber: number, maxTurns: number) =>
  `/api/generation/stream/${episodeNumber}?max_turns=${maxTurns}`

// ==========================================================================
// Memory
// ==========================================================================

export const getMemoryStatus = () => request<MemoryStatus>('/api/memory/status')

export const getPlotThreads = (currentEpisode?: number) =>
  request<PlotThreads>(
    currentEpisode === undefined
      ? '/api/memory/threads'
      : `/api/memory/threads?current_episode=${currentEpisode}`,
  )

export const searchMemory = (
  query: string,
  options: { topK?: number; characterId?: string | null } = {},
) =>
  request<MemorySearchResult>('/api/memory/query', {
    method: 'POST',
    body: {
      query,
      top_k: options.topK ?? 10,
      character_id: options.characterId ?? null,
    },
  })

export const getCharacterMemory = (characterId: string) =>
  request<CharacterMemoryState>(`/api/memory/characters/${encodeURIComponent(characterId)}`)

// ==========================================================================
// Export
// ==========================================================================

export type EpisodeFormat = 'markdown' | 'text' | 'docx'

export const downloadEpisode = (episodeNumber: number, format: EpisodeFormat) =>
  download(`/api/export/episode/${episodeNumber}/${format}`)

export const downloadStory = (format: 'markdown' | 'docx', appendices = true) =>
  download(`/api/export/story/${format}?appendices=${appendices}`)

export const downloadProjectArchive = (includeMemory = true) =>
  download(`/api/export/project/zip?include_memory=${includeMemory}`)

/** Hand a downloaded blob to the browser under the filename the API chose. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
