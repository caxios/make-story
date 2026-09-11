/**
 * 📖 Reading Room — the one page that is not a tool.
 *
 * Everything here serves reading: a single column at a comfortable measure,
 * typography the author controls, and the chapter list out of the way until it
 * is wanted. The reader's settings persist per browser, because a reading
 * preference is not something to set twice.
 */

import {
  BookOpen,
  Check,
  Download,
  FileText,
  Pencil,
  RotateCcw,
  Trash2,
  Type,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import * as api from '@/api/client'
import { EpisodeSummary } from '@/components/EpisodeSummary'
import { DEFAULT_READER, Prose, type ReaderSettings } from '@/components/Prose'
import { useToast } from '@/components/ToastContext'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Modal,
  Panel,
  Slider,
} from '@/components/ui'
import { cn, formatCount } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type { Episode } from '@/types/storyweaver'

const READER_KEY = 'storyweaver.reader'

const words = (text: string) => text.split(/\s+/).filter(Boolean).length
/** Characters including spaces — the unit Korean web novels are measured in. */
const characters = (text: string) => text.replace(/\r/g, '').length

function loadReader(): ReaderSettings {
  try {
    const stored = localStorage.getItem(READER_KEY)
    return stored ? { ...DEFAULT_READER, ...JSON.parse(stored) } : DEFAULT_READER
  } catch {
    return DEFAULT_READER
  }
}

export function ReadingRoom() {
  const { project, loading, refresh } = useProject()
  const { success, fromError } = useToast()
  const navigate = useNavigate()

  const [selected, setSelected] = useState<number | null>(null)
  const [reader, setReader] = useState<ReaderSettings>(loadReader)
  const [showTypography, setShowTypography] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [regenerating, setRegenerating] = useState(false)

  const completed = useMemo(
    () =>
      (project?.episodes ?? [])
        .filter((episode) => episode.status === 'completed' && episode.final_text.trim())
        .sort((a, b) => a.episode_number - b.episode_number),
    [project],
  )

  useEffect(() => {
    try {
      localStorage.setItem(READER_KEY, JSON.stringify(reader))
    } catch {
      // A browser that refuses storage still gets a working reader.
    }
  }, [reader])

  // Default to the last chapter written, and never point at one that is gone.
  const episode: Episode | null =
    completed.find((item) => item.episode_number === selected) ?? completed.at(-1) ?? null

  const startEditing = () => {
    if (!episode) return
    setDraft(episode.final_text)
    setEditing(true)
  }

  const save = async () => {
    if (!episode) return
    setSaving(true)
    try {
      await api.updateEpisode(episode.episode_number, { final_text: draft })
      await refresh()
      success('수정사항이 저장되었습니다')
      setEditing(false)
    } catch (cause) {
      fromError(cause, '회차 본문을 저장하지 못했습니다.')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!episode) return
    try {
      await api.deleteEpisode(episode.episode_number)
      await refresh()
      setSelected(null)
      success(`제${episode.episode_number}화가 삭제되었습니다`)
    } catch (cause) {
      fromError(cause, '회차를 삭제하지 못했습니다.')
    }
  }

  const requeue = async () => {
    if (!episode) return
    try {
      await api.updateEpisode(episode.episode_number, { status: 'queued' })
      await refresh()
      navigate('/episodes')
    } catch (cause) {
      fromError(cause, '회차를 대기열로 되돌리지 못했습니다.')
    }
  }

  const download = async (kind: 'markdown' | 'docx' | 'zip') => {
    if (!episode && kind !== 'zip') return
    try {
      const file =
        kind === 'zip'
          ? await api.downloadProjectArchive()
          : await api.downloadEpisode(episode!.episode_number, kind)
      api.saveBlob(file.blob, file.filename)
      success(`${file.filename} 다운로드 완료`)
    } catch (cause) {
      fromError(cause, '다운로드 파일을 생성하지 못했습니다.')
    }
  }

  if (loading) return <div className="sw-panel h-96 animate-pulse-soft" />
  if (!project) return null

  if (completed.length === 0 || !episode) {
    return (
      <Panel>
        <EmptyState
          icon={BookOpen}
          title="아직 작성된 회차가 없습니다"
          description="집필이 완료된 회차가 이곳에 표시됩니다. 에피소드 큐에서 개요를 등록하고 집필을 시작하세요."
          action={
            <Button variant="primary" onClick={() => navigate('/episodes')}>
              에피소드 큐로 이동
            </Button>
          }
        />
      </Panel>
    )
  }

  const count = words(episode.final_text)

  return (
    <div className="flex gap-6">
      {/* --- Chapters --- */}
      <nav className="hidden w-52 shrink-0 lg:block">
        <p className="mb-2 px-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
          회차 목록
        </p>
        <ol className="space-y-0.5">
          {completed.map((item) => {
            const active = item.episode_number === episode.episode_number
            return (
              <li key={item.episode_number}>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(item.episode_number)
                    setEditing(false)
                  }}
                  className={cn(
                    'w-full rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
                    active ? 'bg-accent/12 text-ink' : 'text-ink-dim hover:bg-white/4 hover:text-ink',
                  )}
                >
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-mono text-xs text-ink-muted tabular-nums">
                      {item.episode_number}
                    </span>
                    <span className="truncate">{item.title || '(제목 없음)'}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>

      <div className="min-w-0 flex-1">
        {/* --- Chapter header --- */}
        <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent">제{episode.episode_number}화</Badge>
              <Badge>{formatCount(count)} 단어</Badge>
              <Badge>{formatCount(characters(episode.final_text))} 자</Badge>
              {episode.scenes.length > 0 && (
                <Badge>
                  {episode.scenes.length}개 장면
                </Badge>
              )}
            </div>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink">
              {episode.title || '(제목 없음)'}
            </h2>
          </div>

          <div className="flex items-center gap-1">
            <IconButton
              icon={Type}
              title="서체 및 뷰어 설정"
              onClick={() => setShowTypography(true)}
            />
            <IconButton
              icon={editing ? X : Pencil}
              title={editing ? '편집 모드 종료' : '이 회차 편집'}
              onClick={() => (editing ? setEditing(false) : startEditing())}
            />
            <IconButton
              icon={RotateCcw}
              title="이 회차 다시 생성"
              onClick={() => setRegenerating(true)}
            />
            <IconButton icon={Trash2} title="이 회차 삭제" onClick={() => setDeleting(true)} />
          </div>
        </header>

        {/* --- What the next episode will be told about this one --- */}
        <EpisodeSummary episode={episode} onChanged={refresh} />

        {/* --- The chapter --- */}
        {editing ? (
          <div className="space-y-3">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={28}
              spellCheck={false}
              className="sw-field w-full resize-y leading-relaxed"
              style={{
                fontFamily: reader.serif ? 'var(--font-serif)' : 'var(--font-sans)',
                fontSize: `${reader.fontSize}px`,
                lineHeight: reader.lineHeight,
              }}
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-ink-muted">
                {formatCount(words(draft))} 단어
                {words(draft) !== count &&
                  ` · ${words(draft) > count ? '+' : ''}${formatCount(words(draft) - count)}`}
              </p>
              <div className="flex gap-2">
                <Button onClick={() => setEditing(false)}>취소</Button>
                <Button
                  variant="primary"
                  icon={Check}
                  onClick={() => void save()}
                  loading={saving}
                  disabled={draft === episode.final_text}
                >
                  변경사항 저장
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <article className="sw-panel px-6 py-10 sm:px-10">
            <Prose text={episode.final_text} settings={reader} />
          </article>
        )}

        {/* --- Export --- */}
        <Panel
          title="내보내기 (Export)"
          description="백엔드에서 직접 생성하므로 현재 디스크에 저장된 본문 및 프로젝트 상태와 완전히 일치합니다."
          className="mt-6"
        >
          <div className="flex flex-wrap gap-2">
            <Button icon={FileText} onClick={() => void download('markdown')}>
              회차 마크다운 (.md)
            </Button>
            <Button icon={FileText} onClick={() => void download('docx')}>
              회차 워드 문서 (.docx)
            </Button>
            <Button icon={Download} onClick={() => void download('zip')}>
              프로젝트 전체 백업 (.zip)
            </Button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-muted">
            전체 백업 파일(.zip)에는 본문 텍스트뿐만 아니라 인물 설정, 세계관, 벡터 메모리와 복선 장부까지
            모두 포함되어 있어 다른 환경에서도 완벽히 복원할 수 있습니다.
          </p>
        </Panel>
      </div>

      {/* --- Typography --- */}
      <Modal
        open={showTypography}
        onClose={() => setShowTypography(false)}
        title="서체 및 뷰어 설정"
        description="이 브라우저에 개인 설정이 안전하게 기억됩니다."
        footer={
          <>
            <Button onClick={() => setReader(DEFAULT_READER)}>기본값 복원</Button>
            <Button variant="primary" onClick={() => setShowTypography(false)}>
              완료
            </Button>
          </>
        }
      >
        <div className="space-y-5">
          <div>
            <p className="mb-2 text-xs font-medium text-ink-dim">서체 스타일</p>
            <div className="grid grid-cols-2 gap-2">
              {[
                { serif: true, label: '명조체 (Serif)', sample: 'Lora' },
                { serif: false, label: '고딕체 (Sans)', sample: 'Inter' },
              ].map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setReader({ ...reader, serif: option.serif })}
                  className={cn(
                    'rounded-xl border px-4 py-3 text-left transition-colors',
                    reader.serif === option.serif
                      ? 'border-accent/40 bg-accent/10'
                      : 'border-line bg-surface hover:border-line-strong',
                  )}
                >
                  <span
                    className="block text-lg text-ink"
                    style={{
                      fontFamily: option.serif ? 'var(--font-serif)' : 'var(--font-sans)',
                    }}
                  >
                    별이 지는 밤
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-muted">{option.label}</span>
                </button>
              ))}
            </div>
          </div>

          <Slider
            label="글자 크기"
            min={16}
            max={24}
            step={1}
            value={reader.fontSize}
            onChange={(fontSize) => setReader({ ...reader, fontSize })}
            format={(value) => `${value}px`}
          />
          <Slider
            label="줄 간격"
            min={1.6}
            max={2.2}
            step={0.05}
            value={reader.lineHeight}
            onChange={(lineHeight) => setReader({ ...reader, lineHeight })}
            format={(value) => value.toFixed(2)}
          />
          <Slider
            label="본문 너비"
            min={55}
            max={80}
            step={1}
            value={reader.measure}
            onChange={(measure) => setReader({ ...reader, measure })}
            format={(value) => `${value}자 너비`}
          />

          <div className="rounded-xl border border-line bg-surface px-4 py-3">
            <Prose
              text={'"이건 아무것도 아니야." 그는 말했다.\n\n차가운 돌벽 사이로 오래된 빗물 냄새가 번져왔다.'}
              settings={reader}
              className="!max-w-none"
            />
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={deleting}
        onClose={() => setDeleting(false)}
        onConfirm={() => void remove()}
        title={`제${episode.episode_number}화를 삭제하시겠습니까?`}
        message={
          <>
            작성 완료된 {formatCount(count)} 단어 분량의 본문이 완전히 삭제되며, 이후 회차 번호가
            하나씩 앞당겨집니다.
          </>
        }
      />

      <ConfirmDialog
        open={regenerating}
        onClose={() => setRegenerating(false)}
        onConfirm={() => void requeue()}
        title={`제${episode.episode_number}화를 다시 생성하시겠습니까?`}
        confirmLabel="대기열로 되돌리기"
        destructive={false}
        message={
          <>
            이 회차를 다시 에피소드 큐로 되돌리고 큐 화면으로 이동합니다. 기존에 작성된{' '}
            {formatCount(count)} 단어의 본문은 실제로 재생성을 시작하기 전까지 디스크에 보존됩니다.
          </>
        }
      />
    </div>
  )
}
