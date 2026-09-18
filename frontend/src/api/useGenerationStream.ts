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

import { ApiError, checkGeneration, generationStreamUrl, getRunningGenerations } from '@/api/client'
import type {
  GenerationCompleteEvent,
  GenerationErrorEvent,
  GenerationProgressEvent,
  GenerationStartEvent,
} from '@/types/storyweaver'

/**
 * `detached` means the stream dropped but the job is still running on the
 * backend: it saves its own result, so this is not a failure — the page just
 * stopped being able to watch.
 */
export type GenerationStatus =
  | 'idle'
  | 'connecting'
  | 'generating'
  | 'detached'
  | 'complete'
  | 'error'

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
  /** Why nothing has started yet, while waiting on a backend that is booting. */
  waiting: string | null
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
  waiting: null,
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

/** How long to keep asking a backend that is still booting (ChromaDB is slow). */
const BOOT_WAIT_MS = 45_000
const BOOT_RETRY_MS = 2_000

/** The backend is not answering yet — booting, restarting, or not started. */
function isBooting(cause: unknown): boolean {
  return cause instanceof ApiError && [0, 502, 503, 504].includes(cause.status)
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** The backend's refusal, in words the author can act on. */
function refusal(episodeNumber: number, cause: unknown): GenerationErrorEvent {
  let message: string
  let type = 'Refused'
  if (cause instanceof ApiError && cause.status === 0) {
    type = 'Unreachable'
    message =
      '백엔드에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요 ' +
      '(python scripts/dev.py).'
  } else if (isBooting(cause)) {
    type = 'Starting'
    message =
      '백엔드가 아직 준비되지 않았습니다. 서버를 막 켰다면 메모리(ChromaDB)를 ' +
      '불러오는 중일 수 있습니다 — 잠시 후 다시 시도하세요.'
  } else if (cause instanceof ApiError) {
    type = `HTTP ${cause.status}`
    message = cause.detail
  } else {
    message = cause instanceof Error ? cause.message : String(cause)
  }
  return {
    episode_number: episodeNumber,
    message,
    type,
    resumable: false,
    scenes_completed: 0,
    usage: null,
  }
}

export function useGenerationStream(): UseGenerationStream {
  const [state, setState] = useState<GenerationState>(IDLE)
  const sourceRef = useRef<EventSource | null>(null)
  // Set while `begin` is asking the backend first, and cleared by `stop` /
  // `reset`, so an author who closes the overlay during that wait is not then
  // surprised by a generation starting anyway.
  const pendingRef = useRef<{ cancelled: boolean } | null>(null)

  const close = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
  }, [])

  const cancelPending = useCallback(() => {
    if (pendingRef.current) pendingRef.current.cancelled = true
    pendingRef.current = null
  }, [])

  const stop = useCallback(() => {
    cancelPending()
    close()
    setState((previous) =>
      previous.isRunning ? { ...previous, status: 'idle', isRunning: false } : previous,
    )
  }, [close, cancelPending])

  const reset = useCallback(() => {
    cancelPending()
    close()
    setState(IDLE)
  }, [close, cancelPending])

  const open = useCallback(
    (episodeNumber: number, maxTurns: number) => {
      const source = new EventSource(generationStreamUrl(episodeNumber, maxTurns))
      sourceRef.current = source

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

        if (payload) {
          setState((previous) =>
            previous.status === 'complete'
              ? previous
              : {
                  ...previous,
                  status: 'error',
                  isRunning: false,
                  finishedAt: Date.now(),
                  error: payload,
                },
          )
          return
        }

        // A bare connection failure. The backend already agreed to start this
        // episode, and a generation no longer depends on its stream — so before
        // calling it a failure, ask whether the job is still running.
        void getRunningGenerations()
          .then((running) => running.includes(episodeNumber))
          .catch(() => false)
          .then((alive) =>
            setState((previous) => {
              if (previous.status === 'complete') return previous
              if (alive) {
                return { ...previous, status: 'detached', isRunning: false }
              }
              return {
                ...previous,
                status: 'error',
                isRunning: false,
                finishedAt: Date.now(),
                error: {
                  episode_number: episodeNumber,
                  message:
                    '백엔드와의 연결이 끊겼습니다. 이미 쓴 장면은 체크포인트에 저장되어 ' +
                    '있으니, 다시 생성하면 거기서부터 이어서 씁니다.',
                  type: 'ConnectionError',
                  resumable: previous.progress !== null,
                  scenes_completed: previous.progress?.current_scene ?? 0,
                  usage: null,
                },
              }
            }),
          )
      })
    },
    [close],
  )

  const begin = useCallback(
    (episodeNumber: number, maxTurns = 12) => {
      if (sourceRef.current || pendingRef.current) return

      const pending = { cancelled: false }
      pendingRef.current = pending

      setState({
        ...IDLE,
        status: 'connecting',
        episodeNumber,
        startedAt: Date.now(),
        isRunning: true,
      })

      void (async () => {
        // Ask first, with an ordinary request that can read the backend's
        // answer. An EventSource that is refused learns only that it failed.
        const deadline = Date.now() + BOOT_WAIT_MS
        for (;;) {
          try {
            await checkGeneration(episodeNumber, maxTurns)
            break
          } catch (cause) {
            if (pending.cancelled) return
            if (isBooting(cause) && Date.now() < deadline) {
              setState((previous) => ({
                ...previous,
                waiting: '백엔드가 준비되는 중입니다 — 준비되면 바로 시작합니다…',
              }))
              await sleep(BOOT_RETRY_MS)
              if (pending.cancelled) return
              continue
            }
            pendingRef.current = null
            setState((previous) => ({
              ...previous,
              status: 'error',
              isRunning: false,
              waiting: null,
              finishedAt: Date.now(),
              error: refusal(episodeNumber, cause),
            }))
            return
          }
        }

        if (pending.cancelled) return
        pendingRef.current = null
        setState((previous) => ({ ...previous, waiting: null }))
        open(episodeNumber, maxTurns)
      })()
    },
    [open],
  )

  // Leaving the page should not leave a socket open, or a start pending.
  useEffect(
    () => () => {
      cancelPending()
      close()
    },
    [close, cancelPending],
  )

  return { ...state, begin, stop, reset }
}
