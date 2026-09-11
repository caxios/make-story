/**
 * ⚙️ Settings — how the prose is written, and what it has cost.
 *
 * Every control here reaches the Writer's prompt. Nothing on this page is
 * decorative: if a setting could not change the output, it would not be here.
 */

import { AlertTriangle, Coins, Gauge, KeyRound, Save, Type } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  PageHeader,
  Panel,
  SelectField,
  Slider,
  TextArea,
  TextField,
} from '@/components/ui'
import { formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type {
  Perspective,
  ProseDensity,
  Telemetry,
  Tense,
  WritingStyle,
} from '@/types/storyweaver'

const PERSPECTIVES: { value: Perspective; label: string }[] = [
  { value: 'third_person_limited', label: 'Third person limited — inside one head' },
  { value: 'third_person_omniscient', label: 'Third person omniscient — free to move' },
  { value: 'first_person', label: 'First person — they narrate themselves' },
]

const TENSES: { value: Tense; label: string }[] = [
  { value: 'past', label: 'Past — the standard for narrative fiction' },
  { value: 'present', label: 'Present — immediate and close' },
]

const DENSITIES: { value: ProseDensity; label: string }[] = [
  { value: 'sparse', label: 'Sparse — short sentences, whitespace between beats' },
  { value: 'moderate', label: 'Moderate — description where it earns its place' },
  { value: 'lush', label: 'Lush — layered imagery, longer rhythms' },
]

export function Settings() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="How the prose is written, and what writing it has cost."
      />
      <div className="space-y-5">
        <StylePanel />
        <TelemetryPanel />
      </div>
    </>
  )
}

// ==========================================================================
// Writing style
// ==========================================================================

function StylePanel() {
  const { project, refresh } = useProject()
  const { success, fromError } = useToast()

  const [draft, setDraft] = useState<WritingStyle | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (project) setDraft(project.style)
  }, [project])

  const dirty = useMemo(
    () =>
      draft !== null &&
      project !== null &&
      JSON.stringify(draft) !== JSON.stringify(project.style),
    [draft, project],
  )

  if (!draft || !project) return <div className="sw-panel h-96 animate-pulse-soft" />

  const patch = (changes: Partial<WritingStyle>) =>
    setDraft((previous) => (previous ? { ...previous, ...changes } : previous))

  const save = async () => {
    setSaving(true)
    try {
      await api.saveStyle(draft)
      await refresh()
      success('Writing style saved')
    } catch (cause) {
      fromError(cause, 'Could not save the style.')
    } finally {
      setSaving(false)
    }
  }

  // The unit this target is in follows the language: Korean is measured in
  // characters, English in words. `WritingStyle.describe_target_length` on the
  // backend makes the same decision, and this label has to agree with it.
  const korean = draft.language.toLowerCase().startsWith('ko')
  const perScene = draft.target_word_count_per_scene
  const episodeLow = perScene * 3
  const episodeHigh = perScene * 4

  return (
    <Panel
      title="Writing style"
      description="Set once for the whole story. Every one of these goes into the Writer's prompt."
      actions={
        <>
          {dirty && <Badge tone="warn">Unsaved</Badge>}
          <Button
            variant="primary"
            icon={Save}
            onClick={() => void save()}
            loading={saving}
            disabled={!dirty}
          >
            Save style
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label="Narrative perspective"
            value={draft.perspective}
            onChange={(event) => patch({ perspective: event.target.value as Perspective })}
            options={PERSPECTIVES}
          />
          <SelectField
            label="Tense"
            value={draft.tense}
            onChange={(event) => patch({ tense: event.target.value as Tense })}
            options={TENSES}
          />
          <SelectField
            label="Point-of-view character"
            value={draft.pov_character_id ?? ''}
            onChange={(event) => patch({ pov_character_id: event.target.value || null })}
            options={[
              { value: '', label: '— whoever opens the scene —' },
              ...project.characters.map((character) => ({
                value: character.id,
                label: character.name,
              })),
            ]}
            hint="Ignored for omniscient. If they are not in a scene, the Writer falls back to whoever opens it."
          />
          <SelectField
            label="Prose density"
            value={draft.prose_density}
            onChange={(event) => patch({ prose_density: event.target.value as ProseDensity })}
            options={DENSITIES}
            hint="Pacing is set per episode, in the queue — this is the story-wide texture."
          />
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <Slider
            label="Dialogue vs. narration"
            min={0.2}
            max={0.8}
            step={0.05}
            value={draft.dialogue_ratio}
            onChange={(dialogue_ratio) => patch({ dialogue_ratio })}
            format={(value) => `${Math.round(value * 100)}% dialogue`}
          />
          <div className="space-y-1.5">
            <TextField
              label={korean ? 'Target characters per scene (공백 포함)' : 'Target words per scene'}
              type="number"
              min={100}
              max={6000}
              step={100}
              value={perScene}
              onChange={(event) =>
                patch({
                  target_word_count_per_scene: Math.max(1, Number(event.target.value) || 1400),
                })
              }
            />
          </div>
        </div>

        {/* The one number an author most often wants and cannot see. */}
        <div className="flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3">
          <Gauge className="mt-0.5 size-4 shrink-0 text-ink-muted" aria-hidden />
          <div className="text-xs leading-relaxed text-ink-dim">
            <p>
              The Director plans 3–4 scenes, so one episode lands around{' '}
              <span className="font-medium text-ink">
                {formatCount(episodeLow)}–{formatCount(episodeHigh)}
              </span>{' '}
              {korean ? '자, 공백 포함' : 'words'}.
            </p>
            {korean && (
              <p className="mt-1.5 text-ink-muted">
                A Korean web-novel 회차 is 4,500–5,500자, which is what the default 1,400자
                per scene is set to hit. The Writer is instructed in characters rather than
                words, because a model told &ldquo;1,400 words&rdquo; of Korean reads that as
                어절 and overshoots three- to four-fold.
              </p>
            )}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Output language"
            value={draft.language}
            onChange={(event) => patch({ language: event.target.value })}
            hint="Written into the prompt verbatim: “ko”, “Korean” and “English” all work."
          />
        </div>

        <TextArea
          label="Author style notes"
          rows={4}
          value={draft.author_style_notes}
          onChange={(event) => patch({ author_style_notes: event.target.value })}
          placeholder="Short paragraphs. No adverbs in dialogue tags. Write like…"
          hint="Free text, appended to the Writer's guidelines."
        />
      </div>
    </Panel>
  )
}

// ==========================================================================
// Model and telemetry
// ==========================================================================

function TelemetryPanel() {
  const { fromError } = useToast()
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null)

  useEffect(() => {
    void api
      .getTelemetry()
      .then(setTelemetry)
      .catch((cause) => fromError(cause, 'Could not read the usage log.'))
  }, [fromError])

  if (!telemetry) return <div className="sw-panel h-56 animate-pulse-soft" />

  const stages = Object.entries(telemetry.by_stage)
  const busiest = Math.max(1, ...stages.map(([, tokens]) => tokens))

  return (
    <Panel
      title="Model and cost"
      description="Every model call is metered. These totals are cumulative across every generation this project has run."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">Model</p>
          <p className="mt-1.5 font-mono text-sm text-ink">{telemetry.model}</p>
          <p className="mt-2 text-xs text-ink-muted">
            temperature {telemetry.temperature} · max{' '}
            {formatCount(telemetry.max_output_tokens)} output tokens per call
          </p>
          {!telemetry.api_key_configured && (
            <p className="mt-2.5 flex items-start gap-1.5 text-xs leading-relaxed text-warn-bright">
              <KeyRound className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              GOOGLE_API_KEY is unset. Set it in <code>.env</code> and restart the backend, or
              generation will fail.
            </p>
          )}
        </div>

        <div className="rounded-xl border border-line bg-surface px-4 py-3">
          <p className="text-xs font-medium tracking-wide text-ink-muted uppercase">Spent</p>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="text-2xl font-semibold tracking-tight text-ink tabular-nums">
              ${telemetry.cost.toFixed(2)}
            </span>
            <span className="text-xs text-ink-muted">
              {formatCount(telemetry.total_tokens)} tokens
            </span>
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            {telemetry.runs} run{telemetry.runs === 1 ? '' : 's'} · {telemetry.calls} call
            {telemetry.calls === 1 ? '' : 's'} · {formatCount(telemetry.input_tokens)} in /{' '}
            {formatCount(telemetry.output_tokens)} out
          </p>
          <p className="mt-2 flex items-start gap-1.5 text-[0.68rem] leading-relaxed text-ink-muted">
            <Coins className="mt-0.5 size-3 shrink-0" aria-hidden />${
              telemetry.input_cost_per_mtok
            }/M in, ${telemetry.output_cost_per_mtok}/M out — the configured rates, not a bill.
          </p>
        </div>
      </div>

      {telemetry.estimated && (
        <p className="mt-4 flex items-start gap-2 rounded-lg border border-warn/25 bg-warn/8 px-3 py-2 text-xs leading-relaxed text-warn-bright">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Some calls returned no usage metadata, so their tokens were estimated from length.
          Treat these totals as a floor.
        </p>
      )}

      {stages.length > 0 && (
        <div className="mt-5">
          <p className="mb-2.5 flex items-center gap-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
            <Type className="size-3.5" aria-hidden />
            Where it went
          </p>
          <div className="space-y-2">
            {stages.map(([stage, tokens]) => (
              <div key={stage} className="flex items-center gap-3">
                <span className="w-24 shrink-0 truncate text-xs text-ink-dim">{stage}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                  <span
                    className="block h-full rounded-full bg-accent/70"
                    style={{ width: `${(tokens / busiest) * 100}%` }}
                  />
                </span>
                <span className="w-20 shrink-0 text-right font-mono text-xs text-ink-muted tabular-nums">
                  {formatCount(tokens)}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-muted">
            The character agent is usually the overwhelming majority of the spend — one call per
            turn, per scene.
          </p>
        </div>
      )}

      {telemetry.runs === 0 && (
        <p className="mt-4 text-xs leading-relaxed text-ink-muted">
          Nothing has been generated yet, so there is nothing to account for. A four-scene
          episode with three characters runs roughly 150k–250k tokens.
        </p>
      )}

      {telemetry.recent.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
            Recent runs
          </p>
          <div className="space-y-1">
            {telemetry.recent.map((run, index) => (
              <div
                key={`${run.at}-${index}`}
                className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-xs"
              >
                <span className="text-ink-dim">Episode {run.episode_number}</span>
                <span className="flex items-center gap-3 font-mono text-ink-muted tabular-nums">
                  <span>{formatCount(run.input_tokens + run.output_tokens)} tok</span>
                  <span>${run.cost.toFixed(3)}</span>
                  <span>{Math.round(run.seconds)}s</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}
