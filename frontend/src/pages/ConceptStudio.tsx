/**
 * 💡 작품 기획 — 빈손에서 시작해, 함께 다듬어서, 작품으로.
 *
 * 이 앱에서 모델이 무언가를 *받아서* 바꾸지 않는 유일한 자리다. 나머지는 전부
 * 작가가 쓴 것에서 출발한다 — 줄거리를 받아 장면으로, 장면을 받아 본문으로.
 * 여기서는 아무것도 없는 데서 이야기를 내놓는다.
 *
 * 다듬기에 횟수 제한이 없다. 그래서 매 라운드가 *읽을 수 있을 만큼* 작아야
 * 하고, 무엇이 바뀌었는지가 매번 위에 뜬다.
 *
 * 세션은 디스크에 있다. 어떤 소설을 쓸지 정하는 일은 한 자리에서 끝나지
 * 않으니, 탭을 닫았다고 오후 한나절이 날아가서는 안 된다.
 */

import {
  ArrowRight,
  Lightbulb,
  ListOrdered,
  RotateCcw,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import { ConceptCard } from '@/components/ConceptCard'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  PageHeader,
  Panel,
  TextArea,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { ConceptCommitResult, ConceptSession } from '@/types/storyweaver'

/** How many chapters the opening outline covers. The author can redraw it. */
const DEFAULT_EPISODES = 12

export function ConceptStudio() {
  const { project, refresh } = useProject()
  const { success, fromError } = useToast()
  const navigate = useNavigate()

  const [session, setSession] = useState<ConceptSession | null>(null)
  const [changed, setChanged] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')

  const [seed, setSeed] = useState('')
  const [instruction, setInstruction] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [result, setResult] = useState<ConceptCommitResult | null>(null)

  const load = useCallback(async () => {
    try {
      const view = await api.getConceptSession()
      setSession(view.session)
      setSeed(view.session?.seed ?? '')
    } catch (cause) {
      fromError(cause, '기획 세션을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [fromError])

  useEffect(() => {
    void load()
  }, [load])

  const run = async (
    label: string,
    call: () => Promise<{ session: ConceptSession | null; changed: string[] }>,
    onDone?: () => void,
  ) => {
    setBusy(label)
    try {
      const view = await call()
      setSession(view.session)
      setChanged(view.changed)
      onDone?.()
    } catch (cause) {
      fromError(cause)
    } finally {
      setBusy('')
    }
  }

  const propose = () =>
    run('propose', () => api.proposeConcepts(seed.trim()), () => setChanged([]))

  const choose = (index: number) =>
    run('choose', () => api.chooseConcept(index, DEFAULT_EPISODES))

  const refine = () => {
    if (!instruction.trim()) return
    const asked = instruction.trim()
    return run('refine', () => api.refineConcept(asked), () => setInstruction(''))
  }

  const commit = async () => {
    setConfirming(false)
    setBusy('commit')
    try {
      const committed = await api.commitConcept()
      await refresh()
      setResult(committed)
      await load()
      success('기획을 작품에 반영했습니다.')
    } catch (cause) {
      fromError(cause, '반영하지 못했습니다.')
    } finally {
      setBusy('')
    }
  }

  const discard = async () => {
    setDiscarding(false)
    try {
      await api.discardConceptSession()
      setSession(null)
      setChanged([])
      setResult(null)
    } catch (cause) {
      fromError(cause, '세션을 지우지 못했습니다.')
    }
  }

  if (loading) return <div className="sw-panel h-72 animate-pulse-soft" />

  const chosen = session?.chosen ?? null
  const committed = session?.status === 'committed'
  // Committing replaces the world and adds a cast, so it is refused on a
  // project that already has a story. Better to say so before they ask.
  const occupied = Boolean(
    project && (project.characters.length > 0 || project.world.overview.trim()),
  )

  return (
    <div className="space-y-5">
      <PageHeader
        title="작품 기획"
        description="어떤 소설을 쓸지부터 AI와 함께 정합니다. 제안을 받고, 마음에 드는 하나를 골라, 만족할 때까지 다듬으세요."
        actions={
          session && (
            <Button
              variant="ghost"
              icon={Trash2}
              onClick={() => setDiscarding(true)}
              disabled={Boolean(busy)}
            >
              세션 버리기
            </Button>
          )
        }
      />

      {/* 반영 결과 */}
      {result && (
        <Panel title="작품에 반영했습니다" className="border-good/30">
          <p className="text-sm leading-relaxed text-ink-dim">
            세계관 1개, 인물 {result.characters.length}명, 규칙 {result.rules.length}개,
            장소 {result.locations.length}곳, 회차 {result.episodes}개를 만들었습니다.
            위키에는 기록 {result.chronicle_entries}건이 남았습니다.
          </p>
          {result.dropped.length > 0 && (
            <p className="mt-2 text-xs leading-relaxed text-warn-bright">
              옮기지 못한 것: {result.dropped.join(', ')}
            </p>
          )}
          <p className="mt-2 text-xs leading-relaxed text-ink-muted">
            전부 위키의 첫 기록으로 들어갔습니다. 인물도 설정도 회차도 앞으로 얼마든지
            고치거나 지우실 수 있습니다.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" icon={ListOrdered} onClick={() => navigate('/episodes')}>
              에피소드 큐로
            </Button>
            <Button icon={Lightbulb} onClick={() => navigate('/wiki/story/story')}>
              작품 위키 보기
            </Button>
          </div>
        </Panel>
      )}

      {/* 1단계: 빈손 */}
      {!session && (
        <Panel
          title="무엇을 쓸지부터"
          description="원하시는 방향이 있으면 한 줄 적어 주세요. 비워 두셔도 됩니다 — 그러면 장르를 넓게 흩어서 제안합니다."
        >
          <TextArea
            label="힌트 (선택)"
            rows={3}
            placeholder="예: 학원물인데 오컬트가 섞였으면 / 복수극인데 주인공이 악역 / (비워 두셔도 됩니다)"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
          <div className="mt-4 flex justify-end">
            <Button
              variant="primary"
              icon={Sparkles}
              loading={busy === 'propose'}
              disabled={Boolean(busy)}
              onClick={() => void propose()}
            >
              {seed.trim() ? '이 방향으로 제안받기' : '아무거나 제안받기'}
            </Button>
          </div>
        </Panel>
      )}

      {/* 2단계: 고르기 */}
      {session && !chosen && (
        <>
          <Panel>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-dim">
                {session.seed
                  ? `'${session.seed}' 방향으로 ${session.proposals.length}개를 제안했습니다.`
                  : `${session.proposals.length}개를 제안했습니다.`}
                <span className="ml-1 text-ink-muted">
                  하나를 고르시면 회차 구상까지 펼쳐 드립니다.
                </span>
              </p>
              <Button
                icon={RotateCcw}
                loading={busy === 'propose'}
                disabled={Boolean(busy)}
                onClick={() => void propose()}
              >
                다시 제안받기
              </Button>
            </div>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-3">
            {session.proposals.map((proposal, index) => (
              <ConceptCard
                key={`${proposal.title}-${index}`}
                concept={proposal}
                action={
                  <Button
                    variant="primary"
                    icon={ArrowRight}
                    loading={busy === 'choose'}
                    disabled={Boolean(busy)}
                    onClick={() => void choose(index)}
                  >
                    이걸로 시작
                  </Button>
                }
              />
            ))}
          </div>
        </>
      )}

      {/* 3단계: 다듬기 */}
      {chosen && (
        <>
          {changed.length > 0 && (
            <Panel title="이번에 바뀐 것" className="border-accent/30">
              <ul className="space-y-1 text-sm text-ink-dim">
                {changed.map((line) => (
                  <li key={line}>· {line}</li>
                ))}
              </ul>
            </Panel>
          )}

          {!committed && (
            <Panel
              title="더 다듬기"
              description="평소 말하듯 적어 주세요. 시키신 것과 거기서 따라올 것만 바뀌고, 무엇이 바뀌었는지 위에 표시됩니다. 만족하실 때까지 몇 번이든 괜찮습니다."
            >
              <TextArea
                rows={3}
                placeholder="예: 주인공을 더 어리게 해줘 / 결말을 비극으로 바꿔줘 / 세계관을 좀 더 차갑게"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
              />
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs text-ink-muted">
                  지금까지 {Math.max(session.turns.length - 1, 0)}번 손봤습니다
                </span>
                <div className="flex gap-2">
                  <Button
                    icon={Sparkles}
                    loading={busy === 'refine'}
                    disabled={!instruction.trim() || Boolean(busy)}
                    onClick={() => void refine()}
                  >
                    다듬기
                  </Button>
                  <Button
                    variant="primary"
                    loading={busy === 'commit'}
                    disabled={Boolean(busy)}
                    onClick={() => setConfirming(true)}
                  >
                    이대로 작품 시작하기
                  </Button>
                </div>
              </div>

              {occupied && (
                <p className="mt-3 rounded-lg border border-warn/30 bg-warn/10 p-3 text-xs leading-relaxed text-warn-bright">
                  이미 설정이 있는 작품입니다. 기획을 반영하면 세계관이 덮이고 인물과
                  회차가 섞이기 때문에 거부됩니다. 새 작품으로 시작하시려면 설정에서
                  먼저 초기화해 주세요.
                </p>
              )}
            </Panel>
          )}

          <ConceptCard concept={chosen} expanded />

          {session.turns.length > 1 && <TurnHistory session={session} />}
        </>
      )}

      {session && !chosen && session.proposals.length === 0 && (
        <Panel>
          <EmptyState
            icon={Lightbulb}
            title="쓸 만한 제안이 오지 않았습니다"
            description="다시 제안받아 보세요. 힌트를 한 줄 적어 주시면 더 잘 맞춥니다."
            action={
              <Button variant="primary" onClick={() => void propose()}>
                다시 제안받기
              </Button>
            }
          />
        </Panel>
      )}

      <ConfirmDialog
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={() => void commit()}
        title="이 기획으로 작품을 시작할까요?"
        confirmLabel="작품 시작하기"
        destructive={false}
        message={
          chosen ? (
            <>
              세계관 1개, 인물 {chosen.characters.length}명, 규칙 {chosen.rules.length}개,
              장소 {chosen.locations.length}곳, 회차 구상 {chosen.episodes.length}개가
              만들어집니다.
              <p className="mt-2 text-ink-muted">
                전부 위키의 첫 기록으로 들어갑니다 — 나중에 인물을 더하거나, 설정을
                고치거나, 지우실 수 있습니다.
              </p>
            </>
          ) : (
            <></>
          )
        }
      />

      <ConfirmDialog
        open={discarding}
        onClose={() => setDiscarding(false)}
        onConfirm={() => void discard()}
        title="기획 세션을 버릴까요?"
        confirmLabel="버리기"
        message={
          <>
            제안과 다듬은 내용이 사라집니다.
            <p className="mt-2 text-ink-muted">
              이미 작품에 반영하신 것은 그대로 남습니다.
            </p>
          </>
        }
      />
    </div>
  )
}

// ==========================================================================
// What was asked for, and what it did
// ==========================================================================

function TurnHistory({ session }: { session: ConceptSession }) {
  const [open, setOpen] = useState(false)
  const turns = session.turns.filter((turn) => turn.instruction.trim())

  if (turns.length === 0) return null

  return (
    <Panel
      title="기획 기록"
      description="무엇을 부탁했고 무엇이 바뀌었는지. 작품을 시작하면 이 기록도 위키에 남습니다."
      actions={
        <Button size="sm" variant="ghost" onClick={() => setOpen((current) => !current)}>
          {open ? '접기' : `${turns.length}번 보기`}
        </Button>
      }
    >
      {open && (
        <ol className="space-y-3 border-l border-line pl-4">
          {turns.map((turn) => (
            <li key={turn.turn} className="relative text-sm">
              <span
                className={cn(
                  'absolute -left-[1.3rem] top-1.5 size-2 rounded-full bg-accent',
                )}
                aria-hidden
              />
              <p className="flex items-center gap-2">
                <Badge mono>{turn.turn}</Badge>
                <span className="text-ink">{turn.instruction}</span>
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-ink-muted">
                {turn.changed.map((line) => (
                  <li key={line}>· {line}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}
