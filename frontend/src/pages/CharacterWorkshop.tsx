/**
 * 👤 Character Workshop — the cast, and how they feel about each other.
 *
 * The drawer edits a working copy and saves it in one call, rather than firing
 * a request per keystroke: a character sheet is a document, not a settings
 * panel, and half-written prose has no business reaching the model.
 */

import {
  Copy,
  Eye,
  EyeOff,
  Heart,
  Network,
  Pencil,
  Plus,
  Trash2,
  UserRound,
  Users,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import * as api from '@/api/client'
import { CharacterGraph } from '@/components/CharacterGraph'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  EmptyState,
  IconButton,
  Modal,
  PageHeader,
  Panel,
  SelectField,
  Slider,
  Tabs,
  TagInput,
  TextArea,
  TextField,
} from '@/components/ui'
import { useProject } from '@/state/ProjectContext'
import type {
  CharacterGraph as GraphData,
  CharacterProfile,
  Relationship,
  Trait,
} from '@/types/storyweaver'

const ROLES = [
  'protagonist',
  'antagonist',
  'deuteragonist',
  'supporting',
  'mentor',
  'foil',
  'love interest',
  'minor',
] as const

const RELATIONSHIP_TYPES = [
  'friend',
  'rival',
  'mentor',
  'student',
  'family',
  'ally',
  'enemy',
  'lover',
  'colleague',
  'stranger',
] as const

/** Traits a new character starts with — a spread, not a template to keep. */
const STARTER_TRAITS = ['courage', 'warmth', 'pragmatism', 'pride'] as const

function blankCharacter(): CharacterProfile {
  return {
    id: '',
    name: '',
    role: 'supporting',
    aliases: [],
    age: null,
    gender: null,
    appearance: '',
    personality_summary: '',
    traits: STARTER_TRAITS.map((name) => ({ name, intensity: 0.5, description: null })),
    speech_style: '',
    values: [],
    goals: [],
    backstory: '',
    relationships: [],
    secrets: [],
    author_notes: '',
  }
}

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/[^\p{L}\p{N}-]/gu, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
}

/** The card blurb: the first sentence of the personality summary. */
function oneLine(character: CharacterProfile): string {
  const summary = character.personality_summary.trim()
  if (!summary) return 'No summary yet.'
  const stop = summary.search(/[.!?。](\s|$)/)
  return stop === -1 ? summary : summary.slice(0, stop + 1)
}

function roleTone(role: string) {
  if (role === 'protagonist' || role === 'deuteragonist') return 'accent' as const
  if (role === 'antagonist') return 'bad' as const
  if (role === 'mentor' || role === 'love interest') return 'violet' as const
  return 'neutral' as const
}

type TabId = 'cast' | 'graph'

export function CharacterWorkshop() {
  const { project, loading, refresh } = useProject()
  const { success, fromError } = useToast()

  const [tab, setTab] = useState<TabId>('cast')
  const [editing, setEditing] = useState<CharacterProfile | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [deleting, setDeleting] = useState<CharacterProfile | null>(null)
  const [cloning, setCloning] = useState<CharacterProfile | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)

  const characters = useMemo(() => project?.characters ?? [], [project])

  // The graph is derived server-side, so it is fetched rather than computed —
  // and refetched whenever the cast changes underneath it.
  useEffect(() => {
    if (tab !== 'graph') return
    let cancelled = false
    void api
      .getCharacterGraph()
      .then((data) => !cancelled && setGraph(data))
      .catch((cause) => fromError(cause, 'Could not load the relationship graph.'))
    return () => {
      cancelled = true
    }
  }, [tab, characters, fromError])

  const remove = async (character: CharacterProfile) => {
    try {
      await api.deleteCharacter(character.id)
      await refresh()
      const referrers = characters.filter((other) =>
        other.relationships.some((r) => r.target_character_id === character.id),
      ).length
      success(
        referrers > 0
          ? `${character.name} deleted, along with ${referrers} relationship${referrers === 1 ? '' : 's'} pointing at them`
          : `${character.name} deleted`,
      )
    } catch (cause) {
      fromError(cause, 'Could not delete the character.')
    }
  }

  if (loading) return <div className="sw-panel h-72 animate-pulse-soft" />
  if (!project) return null

  return (
    <>
      <PageHeader
        title="Character Workshop"
        description="Who they are, how they talk, and what they want — the whole of what a character agent knows."
        actions={
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => {
              setEditing(blankCharacter())
              setIsNew(true)
            }}
          >
            New character
          </Button>
        }
      />

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'cast', label: 'Cast', icon: Users, count: characters.length },
          { id: 'graph', label: 'Relationships', icon: Network },
        ]}
      />

      {tab === 'cast' &&
        (characters.length === 0 ? (
          <Panel>
            <EmptyState
              icon={UserRound}
              title="No characters yet"
              description="An episode needs at least one. Everything on a character sheet becomes part of how that character speaks and decides."
              action={
                <Button
                  variant="primary"
                  icon={Plus}
                  onClick={() => {
                    setEditing(blankCharacter())
                    setIsNew(true)
                  }}
                >
                  Add the first one
                </Button>
              }
            />
          </Panel>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {characters.map((character) => (
              <CharacterCard
                key={character.id}
                character={character}
                onEdit={() => {
                  setEditing(character)
                  setIsNew(false)
                }}
                onClone={() => setCloning(character)}
                onDelete={() => setDeleting(character)}
              />
            ))}
          </div>
        ))}

      {tab === 'graph' && (
        <Panel
          title="How the cast is wired"
          description="Click a character to open their sheet. Hover to isolate everything they are part of."
        >
          {characters.length === 0 ? (
            <EmptyState
              icon={Network}
              title="Nothing to draw yet"
              description="Add characters and give them relationships, and they will appear here."
            />
          ) : graph === null ? (
            <div className="h-96 animate-pulse-soft rounded-xl bg-white/2" />
          ) : graph.edges.length === 0 ? (
            <>
              <CharacterGraph
                graph={graph}
                onSelect={(id) => {
                  const found = characters.find((character) => character.id === id)
                  if (found) {
                    setEditing(found)
                    setIsNew(false)
                  }
                }}
              />
              <p className="mt-4 text-center text-xs text-ink-muted">
                No relationships defined yet — open a character and add one.
              </p>
            </>
          ) : (
            <CharacterGraph
              graph={graph}
              onSelect={(id) => {
                const found = characters.find((character) => character.id === id)
                if (found) {
                  setEditing(found)
                  setIsNew(false)
                }
              }}
            />
          )}
        </Panel>
      )}

      <CharacterDrawer
        character={editing}
        isNew={isNew}
        cast={characters}
        onClose={() => setEditing(null)}
        onSaved={refresh}
      />

      <CloneDialog
        character={cloning}
        existingIds={characters.map((character) => character.id)}
        onClose={() => setCloning(null)}
        onCloned={refresh}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && void remove(deleting)}
        title={`Delete ${deleting?.name}?`}
        message={
          <>
            Every relationship pointing at them is deleted too — leaving those behind would put
            ids into prompts that no longer resolve to anyone.
            <p className="mt-2 text-ink-muted">
              Episodes already written are untouched; they keep whatever they said.
            </p>
          </>
        }
      />
    </>
  )
}

// ==========================================================================
// Card
// ==========================================================================

function CharacterCard({
  character,
  onEdit,
  onClone,
  onDelete,
}: {
  character: CharacterProfile
  onEdit: () => void
  onClone: () => void
  onDelete: () => void
}) {
  const strongest = [...character.traits].sort((a, b) => b.intensity - a.intensity).slice(0, 3)

  return (
    <div className="sw-panel group flex flex-col p-4 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold tracking-tight text-ink">
              {character.name || '(unnamed)'}
            </h3>
            {character.role && <Badge tone={roleTone(character.role)}>{character.role}</Badge>}
          </div>
          <p className="mt-1 font-mono text-xs text-ink-muted">#{character.id}</p>
        </div>
        <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <IconButton icon={Pencil} title={`Edit ${character.name}`} onClick={onEdit} />
          <IconButton icon={Copy} title={`Clone ${character.name}`} onClick={onClone} />
          <IconButton icon={Trash2} title={`Delete ${character.name}`} onClick={onDelete} />
        </div>
      </div>

      <p className="mt-3 line-clamp-3 flex-1 text-xs leading-relaxed text-ink-dim">
        {oneLine(character)}
      </p>

      {strongest.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {strongest.map((trait) => (
            <div key={trait.name} className="flex items-center gap-2">
              <span className="w-20 shrink-0 truncate text-[0.68rem] text-ink-muted">
                {trait.name}
              </span>
              <span className="h-1 flex-1 overflow-hidden rounded-full bg-line">
                <span
                  className="block h-full rounded-full bg-accent/70"
                  style={{ width: `${trait.intensity * 100}%` }}
                />
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3.5 flex items-center gap-3 border-t border-line pt-3 text-[0.68rem] text-ink-muted">
        <span className="flex items-center gap-1">
          <Heart className="size-3" />
          {character.relationships.length} relationship
          {character.relationships.length === 1 ? '' : 's'}
        </span>
        {character.secrets.length > 0 && (
          <span className="flex items-center gap-1">
            <EyeOff className="size-3" />
            {character.secrets.length} secret{character.secrets.length === 1 ? '' : 's'}
          </span>
        )}
      </div>
    </div>
  )
}

// ==========================================================================
// Drawer
// ==========================================================================

function CharacterDrawer({
  character,
  isNew,
  cast,
  onClose,
  onSaved,
}: {
  character: CharacterProfile | null
  isNew: boolean
  cast: CharacterProfile[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [draft, setDraft] = useState<CharacterProfile>(character ?? blankCharacter())
  const [saving, setSaving] = useState(false)
  const [showSecrets, setShowSecrets] = useState(false)

  useEffect(() => {
    if (character) {
      setDraft(character)
      setShowSecrets(false)
    }
  }, [character])

  const idTaken = isNew && cast.some((existing) => existing.id === draft.id.trim())
  const valid = draft.id.trim() !== '' && draft.name.trim() !== '' && !idTaken

  const patch = (changes: Partial<CharacterProfile>) =>
    setDraft((previous) => ({ ...previous, ...changes }))

  const save = async () => {
    setSaving(true)
    try {
      await api.upsertCharacter({ ...draft, id: draft.id.trim(), name: draft.name.trim() })
      await onSaved()
      success(isNew ? `${draft.name} added to the cast` : `${draft.name} saved`)
      onClose()
    } catch (cause) {
      fromError(cause, 'Could not save the character.')
    } finally {
      setSaving(false)
    }
  }

  const others = cast.filter((other) => other.id !== draft.id)

  return (
    <Drawer
      open={character !== null}
      onClose={onClose}
      title={isNew ? 'New character' : draft.name || '(unnamed)'}
      description={isNew ? undefined : `#${draft.id}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!valid}>
            {isNew ? 'Add to cast' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="space-y-7">
        {/* --- Basics --- */}
        <Section title="Basics">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Name"
              value={draft.name}
              onChange={(event) => {
                const name = event.target.value
                setDraft((previous) => ({
                  ...previous,
                  name,
                  // A new character's id follows the name until it is typed by
                  // hand; an existing id never moves.
                  id:
                    isNew && previous.id === slugify(previous.name)
                      ? slugify(name)
                      : previous.id,
                }))
              }}
              placeholder="Harry Potter"
            />
            <TextField
              label="Id"
              value={draft.id}
              disabled={!isNew}
              onChange={(event) => patch({ id: event.target.value })}
              placeholder="harry-potter"
              hint={
                idTaken
                  ? 'A character with this id already exists.'
                  : isNew
                    ? 'How scenes and relationships refer to them.'
                    : 'Ids are fixed once set — relationships point at them.'
              }
            />
            <SelectField
              label="Role"
              value={draft.role}
              onChange={(event) => patch({ role: event.target.value })}
              options={[
                { value: '', label: '— none —' },
                ...(draft.role && !ROLES.includes(draft.role as (typeof ROLES)[number])
                  ? [{ value: draft.role, label: draft.role }]
                  : []),
                ...ROLES.map((role) => ({ value: role, label: role })),
              ]}
            />
            <TextField
              label="Age"
              type="number"
              value={draft.age ?? ''}
              onChange={(event) =>
                patch({ age: event.target.value === '' ? null : Number(event.target.value) })
              }
              placeholder="—"
            />
            <TextField
              label="Gender"
              value={draft.gender ?? ''}
              onChange={(event) => patch({ gender: event.target.value || null })}
              placeholder="—"
              className="sm:col-span-2"
            />
          </div>

          <TagInput
            label="Aliases"
            values={draft.aliases}
            onChange={(aliases) => patch({ aliases })}
            hint="Other names the story calls them by — titles, nicknames, epithets."
            placeholder="Add an alias and press Enter"
          />

          <TextArea
            label="Personality summary"
            rows={4}
            value={draft.personality_summary}
            onChange={(event) => patch({ personality_summary: event.target.value })}
            placeholder="A short paragraph. Who are they when nothing is happening?"
            hint="The first sentence is what shows on their card."
          />

          <TextArea
            label="Appearance"
            rows={3}
            value={draft.appearance}
            onChange={(event) => patch({ appearance: event.target.value })}
            placeholder="What another character notices first."
          />
        </Section>

        {/* --- Traits --- */}
        <Section
          title="Personality traits"
          description="Intensity is passed to the character agent as a dial, not a label — 0.9 courage argues back, 0.2 courage looks for the door."
        >
          <TraitEditor traits={draft.traits} onChange={(traits) => patch({ traits })} />
        </Section>

        {/* --- Voice --- */}
        <Section title="Voice">
          <TextArea
            label="Speech style"
            rows={4}
            value={draft.speech_style}
            onChange={(event) => patch({ speech_style: event.target.value })}
            placeholder="Formality, dialect, verbal habits, and a line they might actually say."
            hint="Free text, quoted directly into the character agent's prompt. Example lines belong here."
          />
        </Section>

        {/* --- Motivation --- */}
        <Section title="What drives them">
          <TagInput
            label="Goals"
            values={draft.goals}
            onChange={(goals) => patch({ goals })}
            hint="What they are chasing right now."
            placeholder="Add a goal and press Enter"
          />
          <TagInput
            label="Values"
            values={draft.values}
            onChange={(values) => patch({ values })}
            hint="What they will not trade away."
            placeholder="Add a value and press Enter"
          />
          <TextArea
            label="Backstory"
            rows={4}
            value={draft.backstory}
            onChange={(event) => patch({ backstory: event.target.value })}
            placeholder="What happened before page one."
          />
        </Section>

        {/* --- Secrets --- */}
        <Section
          title="Secrets"
          description="Known to this character and to no one else. Other characters' agents never see them."
          action={
            <Button
              size="sm"
              icon={showSecrets ? EyeOff : Eye}
              onClick={() => setShowSecrets((value) => !value)}
            >
              {showSecrets ? 'Hide' : `Show${draft.secrets.length ? ` (${draft.secrets.length})` : ''}`}
            </Button>
          }
        >
          {showSecrets ? (
            <>
              <TagInput
                values={draft.secrets}
                onChange={(secrets) => patch({ secrets })}
                placeholder="Add a secret and press Enter"
              />
              <TextArea
                label="Author notes"
                rows={3}
                value={draft.author_notes}
                onChange={(event) => patch({ author_notes: event.target.value })}
                placeholder="Notes to yourself. Never shown to any agent as character knowledge."
              />
            </>
          ) : (
            <p className="text-xs text-ink-muted">
              {draft.secrets.length === 0
                ? 'Nothing hidden yet.'
                : `${draft.secrets.length} secret${draft.secrets.length === 1 ? '' : 's'}, hidden.`}
            </p>
          )}
        </Section>

        {/* --- Relationships --- */}
        <Section
          title="Relationships"
          description="Directed: this is how they feel, not how it is returned."
        >
          <RelationshipEditor
            relationships={draft.relationships}
            others={others}
            onChange={(relationships) => patch({ relationships })}
          />
        </Section>
      </div>
    </Drawer>
  )
}

function Section({
  title,
  description,
  action,
  children,
}: {
  title: string
  description?: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-line pb-2">
        <div>
          <h3 className="text-xs font-semibold tracking-wide text-ink uppercase">{title}</h3>
          {description && (
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">{description}</p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

// --------------------------------------------------------------------------
// Traits
// --------------------------------------------------------------------------

function TraitEditor({
  traits,
  onChange,
}: {
  traits: Trait[]
  onChange: (traits: Trait[]) => void
}) {
  const [name, setName] = useState('')

  const add = () => {
    const trimmed = name.trim()
    if (!trimmed || traits.some((trait) => trait.name === trimmed)) return
    onChange([...traits, { name: trimmed, intensity: 0.5, description: null }])
    setName('')
  }

  return (
    <div className="space-y-3">
      {traits.length > 0 && (
        <div className="space-y-3 rounded-xl border border-line bg-surface px-4 py-3.5">
          {traits.map((trait, index) => (
            <div key={`${trait.name}-${index}`} className="flex items-end gap-3">
              <div className="min-w-0 flex-1">
                <Slider
                  label={trait.name}
                  value={trait.intensity}
                  onChange={(intensity) =>
                    onChange(
                      traits.map((existing, i) =>
                        i === index ? { ...existing, intensity } : existing,
                      ),
                    )
                  }
                />
              </div>
              <IconButton
                icon={Trash2}
                title={`Remove ${trait.name}`}
                className="mb-0.5"
                onClick={() => onChange(traits.filter((_, i) => i !== index))}
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              add()
            }
          }}
          placeholder="Add a trait — courage, cynicism, patience…"
          className="sw-field flex-1 text-sm"
        />
        <Button icon={Plus} onClick={add} disabled={!name.trim()}>
          Add
        </Button>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// Relationships
// --------------------------------------------------------------------------

function RelationshipEditor({
  relationships,
  others,
  onChange,
}: {
  relationships: Relationship[]
  others: CharacterProfile[]
  onChange: (relationships: Relationship[]) => void
}) {
  const nameOf = (id: string) => others.find((other) => other.id === id)?.name ?? id

  const update = (index: number, changes: Partial<Relationship>) =>
    onChange(
      relationships.map((existing, i) => (i === index ? { ...existing, ...changes } : existing)),
    )

  const unrelated = others.filter(
    (other) => !relationships.some((r) => r.target_character_id === other.id),
  )

  if (others.length === 0) {
    return (
      <p className="text-xs text-ink-muted">
        Relationships need someone to point at. Add another character first.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {relationships.map((relationship, index) => (
        <div
          key={`${relationship.target_character_id}-${index}`}
          className="space-y-3 rounded-xl border border-line bg-surface px-4 py-3.5"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm font-medium text-ink">
              {nameOf(relationship.target_character_id)}
            </span>
            <IconButton
              icon={Trash2}
              title={`Remove the relationship with ${nameOf(relationship.target_character_id)}`}
              onClick={() => onChange(relationships.filter((_, i) => i !== index))}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label="Who"
              value={relationship.target_character_id}
              onChange={(event) => update(index, { target_character_id: event.target.value })}
              options={others.map((other) => ({ value: other.id, label: other.name }))}
            />
            <SelectField
              label="Type"
              value={relationship.type}
              onChange={(event) => update(index, { type: event.target.value })}
              options={[
                ...(RELATIONSHIP_TYPES.includes(
                  relationship.type as (typeof RELATIONSHIP_TYPES)[number],
                )
                  ? []
                  : [{ value: relationship.type, label: relationship.type }]),
                ...RELATIONSHIP_TYPES.map((type) => ({ value: type, label: type })),
              ]}
            />
          </div>

          <Slider
            label="Sentiment"
            tone="sentiment"
            min={-1}
            max={1}
            step={0.05}
            value={relationship.sentiment}
            onChange={(sentiment) => update(index, { sentiment })}
            format={(value) =>
              `${value > 0 ? '+' : ''}${value.toFixed(2)} · ${
                value > 0.3 ? 'allied' : value < -0.3 ? 'hostile' : 'neutral'
              }`
            }
          />

          <TextField
            label="Notes"
            value={relationship.description ?? ''}
            onChange={(event) => update(index, { description: event.target.value || null })}
            placeholder="The nuance a type and a number cannot carry."
          />
        </div>
      ))}

      <Button
        icon={Plus}
        disabled={unrelated.length === 0}
        onClick={() =>
          unrelated[0] &&
          onChange([
            ...relationships,
            {
              target_character_id: unrelated[0].id,
              type: 'friend',
              sentiment: 0,
              description: null,
            },
          ])
        }
      >
        {unrelated.length === 0 ? 'Everyone is already covered' : 'Add a relationship'}
      </Button>
    </div>
  )
}

// --------------------------------------------------------------------------
// Clone
// --------------------------------------------------------------------------

function CloneDialog({
  character,
  existingIds,
  onClose,
  onCloned,
}: {
  character: CharacterProfile | null
  existingIds: string[]
  onClose: () => void
  onCloned: () => Promise<void>
}) {
  const { success, fromError } = useToast()
  const [name, setName] = useState('')
  const [id, setId] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (character) {
      setName(`${character.name} (copy)`)
      setId(`${character.id}-copy`)
    }
  }, [character])

  const taken = existingIds.includes(id.trim())
  const valid = id.trim() !== '' && name.trim() !== '' && !taken

  const clone = async () => {
    if (!character) return
    setSaving(true)
    try {
      await api.cloneCharacter(character.id, id.trim(), name.trim())
      await onCloned()
      success(`${name.trim()} cloned from ${character.name}`)
      onClose()
    } catch (cause) {
      fromError(cause, 'Could not clone the character.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={character !== null}
      onClose={onClose}
      title={`Clone ${character?.name}`}
      description="Everything is copied — traits, voice, goals, secrets and relationships."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void clone()} loading={saving} disabled={!valid}>
            Clone
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => {
            setName(event.target.value)
            setId(slugify(event.target.value))
          }}
        />
        <TextField
          label="Id"
          value={id}
          onChange={(event) => setId(event.target.value)}
          hint={taken ? 'A character with this id already exists.' : undefined}
        />
      </div>
    </Modal>
  )
}
