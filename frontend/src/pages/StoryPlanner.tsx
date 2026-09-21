/**
 * 📋 스토리 플래너 — 한 줄씩 적으면, 화별 기획서가 되어 돌아온다.
 *
 * 흐름은 네 단계다.
 *   1. 작가가 한 화에 한 줄씩 적는다
 *   2. "기획서 생성" — 각 줄이 모델을 한 번씩 거쳐 상세 기획서가 된다
 *   3. 작가가 읽고 고치고, 큐에 넣을 것만 승인한다
 *   4. 승인한 것만 에피소드 큐에 저장된다
 *
 * 여기서 만드는 건 줄거리(author_storyline)이지 본문이 아니다. 본문을 쓰기
 * 직전에 한 번 더 확인하는 장면 단위 기획서는 에피소드 큐 쪽에 따로 있다.
 */

import {
  CheckCircle2,
  Circle,
  ClipboardList,
  Plus,
  Sparkles,
  Trash2,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import type { ExpandedEpisodeSummary } from '@/api/client'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  PageHeader,
  Panel,
  TextArea,
  TextField,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'

/** 한 번에 보낼 수 있는 줄 수. 백엔드의 상한과 같은 값이다. */
const MAX_SUMMARIES = 20

export function StoryPlanner() {
  const { project, refresh } = useProject()
  const { success, error, fromError } = useToast()
  const navigate = useNavigate()

  // 1단계: 작가가 적은 한 줄들.
  const [summaries, setSummaries] = useState<string[]>(['', '', ''])

  // 2단계: 모델이 펼쳐 놓은 기획서. null이면 아직 생성 전이다.
  const [plans, setPlans] = useState<ExpandedEpisodeSummary[] | null>(null)

  // 편집본은 따로 들고 있는다. 원본(author_one_line)은 작가가 무엇을
  // 부탁했는지 보여주기 위해 손대지 않고 남겨 둔다.
  const [titles, setTitles] = useState<string[]>([])
  const [storylines, setStorylines] = useState<string[]>([])
  const [approved, setApproved] = useState<Set<number>>(new Set())

  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)

  const filled = summaries.filter((line) => line.trim())

  // ── 1단계 ────────────────────────────────────────────────────────────────

  function updateSummary(index: number, value: string) {
    setSummaries((current) => current.map((line, i) => (i === index ? value : line)))
  }

  function addRow() {
    setSummaries((current) => (current.length >= MAX_SUMMARIES ? current : [...current, '']))
  }

  function removeRow(index: number) {
    setSummaries((current) => current.filter((_, i) => i !== index))
  }

  async function generate() {
    if (filled.length === 0) return
    setGenerating(true)
    try {
      const result = await api.planAllEpisodes(filled.map((line) => line.trim()))
      setPlans(result.episodes)
      setTitles(result.episodes.map((episode) => episode.title))
      setStorylines(result.episodes.map((episode) => episode.author_storyline))
      setApproved(new Set())
    } catch (cause) {
      fromError(cause, '기획서를 만들지 못했습니다.')
    } finally {
      setGenerating(false)
    }
  }

  // ── 2단계 ────────────────────────────────────────────────────────────────

  function toggleApproval(index: number) {
    setApproved((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  function approveAll() {
    if (plans) setApproved(new Set(plans.map((_, index) => index)))
  }

  /**
   * 승인한 것만 큐에 넣는다.
   *
   * 하나가 실패해도 멈추지 않는다 — 다섯 중 셋째가 실패했다고 나머지 둘까지
   * 버리면 작가는 무엇이 저장됐는지 알 수 없게 된다. 저장된 것은 승인
   * 목록에서 빠지므로, 다시 누르면 실패한 것만 재시도된다.
   */
  async function saveApproved() {
    if (!plans) return
    const order = [...approved].sort((a, b) => a - b)
    if (order.length === 0) return

    setSaving(true)
    const saved: number[] = []
    const failures: string[] = []
    try {
      for (const index of order) {
        try {
          await api.addEpisode(storylines[index].trim(), titles[index].trim())
          saved.push(index)
        } catch (cause) {
          const reason = cause instanceof Error ? cause.message : String(cause)
          failures.push(plans[index].episode_number + '화: ' + reason)
        }
      }

      await refresh()

      if (saved.length > 0) {
        success(saved.length + '개 에피소드를 큐에 추가했습니다.')
      }
      if (failures.length > 0) {
        error('저장하지 못한 에피소드가 있습니다 — ' + failures.join(' / '))
        setApproved(new Set(order.filter((index) => !saved.includes(index))))
      } else {
        navigate('/episodes')
      }
    } finally {
      setSaving(false)
    }
  }

  // ── 아직 기획할 것이 없을 때 ─────────────────────────────────────────────

  if (project && !project.world.overview.trim()) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="세계관을 먼저 정해 주세요"
        description="기획서는 세계관과 인물 위에서 쓰입니다. 세계관 빌더에서 배경을 적고 오시면, 그때부터 한 줄이 한 화가 됩니다."
        action={
          <Button variant="primary" onClick={() => navigate('/world')}>
            세계관 빌더 열기
          </Button>
        }
      />
    )
  }

  if (project && project.characters.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title="인물이 아직 없습니다"
        description="누가 나오는지 모르면 기획서도 쓸 수 없습니다. 캐릭터 워크숍에서 인물을 한 명이라도 만들어 주세요."
        action={
          <Button variant="primary" onClick={() => navigate('/characters')}>
            캐릭터 워크숍 열기
          </Button>
        }
      />
    )
  }

  // ── 1단계: 한 줄 요약 ────────────────────────────────────────────────────

  if (!plans) {
    return (
      <div className="space-y-5">
        <PageHeader
          title="스토리 플래너"
          description="한 화에 한 줄씩 적어 주세요. 각 줄을 모델이 4~6문단짜리 기획서로 펼쳐 줍니다."
        />

        <Panel
          title="회차별 한 줄 요약"
          description={`한 줄이 모델 호출 한 번입니다. 지금 ${filled.length}줄, 최대 ${MAX_SUMMARIES}줄.`}
        >
          <div className="space-y-3">
            {summaries.map((summary, index) => (
              <div key={index} className="flex items-start gap-2">
                <span className="w-7 shrink-0 pt-3 text-right font-mono text-xs text-ink-muted">
                  {index + 1}.
                </span>
                <TextArea
                  className="flex-1"
                  rows={2}
                  placeholder={`${index + 1}번째 화 — 예: 지민이 오랜 친구 유나와 재회하고, 유나의 비밀을 눈치챈다`}
                  value={summary}
                  onChange={(event) => updateSummary(index, event.target.value)}
                />
                <IconButton
                  icon={Trash2}
                  title="이 줄 삭제"
                  variant="danger"
                  className="mt-1"
                  disabled={summaries.length <= 1}
                  onClick={() => removeRow(index)}
                />
              </div>
            ))}
          </div>

          <div className="mt-5 flex items-center justify-between gap-3">
            <Button
              variant="ghost"
              icon={Plus}
              onClick={addRow}
              disabled={summaries.length >= MAX_SUMMARIES}
            >
              회차 추가
            </Button>
            <Button
              variant="primary"
              icon={Sparkles}
              loading={generating}
              disabled={filled.length === 0 || generating}
              onClick={generate}
            >
              {generating ? '기획서 만드는 중…' : `기획서 생성 (${filled.length}화)`}
            </Button>
          </div>
        </Panel>
      </div>
    )
  }

  // ── 2단계: 기획서 검토 ───────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      <PageHeader
        title="기획서 검토"
        description={`${plans.length}화 분량의 기획서입니다. 큐에 넣을 것만 승인해 주세요. 저장하기 전에는 아무것도 기록되지 않습니다.`}
        actions={
          <>
            <Button variant="ghost" onClick={() => setPlans(null)} disabled={saving}>
              ← 요약으로 돌아가기
            </Button>
            <Button variant="secondary" onClick={approveAll} disabled={saving}>
              전체 승인
            </Button>
          </>
        }
      />

      <div className="space-y-4">
        {plans.map((plan, index) => {
          const isApproved = approved.has(index)
          return (
            <Panel
              key={plan.episode_number}
              className={cn('transition-colors', isApproved ? 'border-accent/40' : 'opacity-80')}
            >
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  onClick={() => toggleApproval(index)}
                  title={isApproved ? '승인 취소' : '이 기획서 승인'}
                  className={cn(
                    'mt-1 shrink-0 rounded-full transition-colors',
                    isApproved ? 'text-accent' : 'text-ink-muted hover:text-ink',
                  )}
                >
                  {isApproved ? (
                    <CheckCircle2 className="size-6" />
                  ) : (
                    <Circle className="size-6" />
                  )}
                </button>

                <div className="min-w-0 flex-1 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge mono>{plan.episode_number}화</Badge>
                    <span className="min-w-0 truncate text-xs text-ink-muted italic">
                      “{plan.author_one_line}”
                    </span>
                  </div>

                  <TextField
                    label="제목"
                    value={titles[index]}
                    onChange={(event) =>
                      setTitles((current) =>
                        current.map((title, i) => (i === index ? event.target.value : title)),
                      )
                    }
                  />

                  <TextArea
                    label="기획서 (자유롭게 고치세요)"
                    hint="여기 적힌 내용이 그대로 그 화의 줄거리가 되고, 본문은 이것을 바탕으로 쓰입니다."
                    rows={12}
                    value={storylines[index]}
                    onChange={(event) =>
                      setStorylines((current) =>
                        current.map((text, i) => (i === index ? event.target.value : text)),
                      )
                    }
                  />
                </div>
              </div>
            </Panel>
          )
        })}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
        <p className="text-xs text-ink-muted">
          {approved.size === 0
            ? '승인한 기획서가 없습니다.'
            : `${approved.size}화를 큐에 넣습니다.`}
        </p>
        <Button
          variant="primary"
          loading={saving}
          disabled={approved.size === 0 || saving}
          onClick={saveApproved}
        >
          {saving ? '저장 중…' : `${approved.size}화 큐에 저장 →`}
        </Button>
      </div>
    </div>
  )
}
