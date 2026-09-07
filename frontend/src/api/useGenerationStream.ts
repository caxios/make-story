/**
 * Watching one episode being written.
 *
 * The backend streams `start`, then a `progress` frame per pipeline node, then
 * exactly one `complete` or `error`. This keeps the latest of each and the
 * running checklist, and closes the connection the moment the run ends.
 *
 * It never lets EventSource reconnect on its own. A reconnect is a second GET,
 * and a second GET is a second generation — so any error closes the stream and
 * is reported, rather than retried behind the author's back.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { generationStreamUrl } from '@/api/client'
import type {
  GenerationCompleteEvent,
  GenerationErrorEvent,
  GenerationProgressEvent,
  GenerationStartEvent,
} from '@/types/storyweaver'

export type GenerationStatus = 'idle' | 'connecting' | 'generating' | 'complete' | 'error'

export interface GenerationState {
  status: GenerationStatus
  /** The episode being generated, while one is. */
  episodeNumber: number | null
  /** `Date.now()` when the stream opened, for an elapsed clock. */
  startedAt: number | null
  /** `Date.now()` when it finished, either way. */
  finishedAt: number | null
  start: GenerationStartEvent | null
  /** The most recent progress frame. */
  progress: GenerationProgressEvent | null
  /** Every stage line so far, as the backend phrased it. */
  checklist: string[]
  /** What each finished stage said, in order — a scrollable running log. */
  log: string[]
  result: GenerationCompleteEvent | null
  error: GenerationErrorEvent | null
  /** True from the moment a run starts until it finishes, either way. */
  isRunning: boolean
}

const IDLE: GenerationState = {
  status: 'idle',
  episodeNumber: null,
  startedAt: null,
  finishedAt: null,
  start: null,
  progress: null,
  checklist: [],
  log: [],
  result: null,
  error: null,
  isRunning: false,
}

export interface UseGenerationStream extends GenerationState {
  /** Open the stream for one episode. Refuses while another run is live. */
  begin: (episodeNumber: number, maxTurns?: number) => void
  /** Stop watching. The backend keeps going and checkpoints what it finishes. */
  stop: () => void
  /** Clear the last result, ready for the next run. */
  reset: () => void
}

function parse<T>(event: MessageEvent): T | null {
  try {
    return JSON.parse(event.data as string) as T
  } catch {
    return null
  }
}

export function useGenerationStream(): UseGenerationStream {
  const [state, setState] = useState<GenerationState>(IDLE)
  const sourceRef = useRef<EventSource | null>(null)

  const close = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
  }, [])

  const stop = useCallback(() => {
    close()
    setState((previous) =>
      previous.isRunning ? { ...previous, status: 'idle', isRunning: false } : previous,
    )
  }, [close])

  const reset = useCallback(() => {
    close()
    setState(IDLE)
  }, [close])

  const begin = useCallback(
    (episodeNumber: number, maxTurns = 12) => {
      if (sourceRef.current) return

      const source = new EventSource(generationStreamUrl(episodeNumber, maxTurns))
      sourceRef.current = source

      setState({
        ...IDLE,
        status: 'connecting',
        episodeNumber,
        startedAt: Date.now(),
        isRunning: true,
      })

      source.addEventListener('start', (event) => {
        const payload = parse<GenerationStartEvent>(event as MessageEvent)
        if (!payload) return
        setState((previous) => ({
          ...previous,
          status: 'generating',
          start: payload,
          log:
            payload.resuming_from_scene === null
              ? previous.log
              : [...previous.log, `Resuming from scene ${payload.resuming_from_scene}`],
        }))
      })

      source.addEventListener('progress', (event) => {
        const payload = parse<GenerationProgressEvent>(event as MessageEvent)
        if (!payload) return
        setState((previous) => ({
          ...previous,
          status: 'generating',
          progress: payload,
          checklist: payload.checklist,
          // `summary` repeats while a node produces nothing new to say.
          log:
            payload.summary && payload.summary !== previous.log.at(-1)
              ? [...previous.log, payload.summary]
              : previous.log,
        }))
      })

      source.addEventListener('complete', (event) => {
        const payload = parse<GenerationCompleteEvent>(event as MessageEvent)
        close()
        setState((previous) => ({
          ...previous,
          status: 'complete',
          isRunning: false,
          finishedAt: Date.now(),
          result: payload,
          checklist: payload?.checklist ?? previous.checklist,
        }))
      })

      // One listener, because EventSource delivers two different things under
      // this name: the backend's own "error" frame, which carries a payload,
      // and the built-in connection failure, which carries nothing. The
      // payload is what tells them apart.
      source.addEventListener('error', (event) => {
        const payload = parse<GenerationErrorEvent>(event as MessageEvent)
        close()
        setState((previous) => {
          if (previous.status === 'complete') return previous
          return {
            ...previous,
            status: 'error',
            isRunning: false,
            finishedAt: Date.now(),
            error: payload ?? {
              episode_number: episodeNumber,
              message:
                previous.status === 'connecting'
                  ? 'The backend would not start this generation. It may already be ' +
                    'running, or the story may still be missing its world or cast.'
                  : 'The connection to the backend dropped. Anything already written ' +
                    'is checkpointed — generating again picks up from there.',
              type: 'ConnectionError',
              resumable: previous.progress !== null,
              scenes_completed: previous.progress?.current_scene ?? 0,
              usage: null,
            },
          }
        })
      })
    },
    [close],
  )

  // Leaving the page should not leave a socket open.
  useEffect(() => close, [close])

  return { ...state, begin, stop, reset }
}
