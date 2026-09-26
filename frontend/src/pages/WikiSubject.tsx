/**
 * 📖 위키 문서 한 편 — 지금의 설정과, 거기까지 온 내력.
 *
 * 섹션마다 두 가지가 같이 보인다. 지금 값(= AI가 다음 회차를 쓸 때 보는 값)과,
 * 작가가 처음 쓴 것부터 회차별 변화까지의 전체 내력. 가장 유용한 한 가지는
 * 앞의 것이다 — 지금 AI가 이 인물을 어떻게 알고 있는지를 볼 방법이 여기 말고는
 * 없기 때문이다.
 *
 * 고치는 것은 덮어쓰는 것이 아니라 내력에 한 줄을 더하는 것이다.
 */

import { ArrowLeft, ChevronDown, Eraser, Pencil, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import * as api from '@/api/client'
import { Chronicle } from '@/components/Chronicle'
import { useToast } from '@/components/ToastContext'
import { deletable, deletePageMessage } from '@/components/wikiDelete'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Modal,
  Panel,
  SelectField,
  TextArea,
  TextField,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { useProject } from '@/state/ProjectContext'
import type {
  ChronicleEntry,
  SectionKind,
  SubjectType,
  WikiPage,
  WikiSection,
} from '@/types/storyweaver'

const TYPE_LABELS: Record<SubjectType, string> = {
  story: '작품',
  character: '인물',
  world: '세계관',
  location: '장소',
  rule: '규칙',
  faction: '세력',
}

export function WikiSubject() {
  const params = useParams<{ subjectType: string; subjectId: string }>()
  const subjectType = (params.subjectType ?? 'character') as SubjectType
  const subjectId = params.subjectId ?? ''

  const { success, fromError } = useToast()
  const { refresh } = useProject()
  const navigate = useNavigate()

  const [page, setPage] = useState<WikiPage | null>(null)
  const [missing, setMissing] = useState(false)
  const [busy, setBusy] = useState(false)

  const [editing, setEditing] = useState<WikiSection | null>(null)
  const [draft, setDraft] = useState('')
  const [reason, setReason] = useState('')

  const [addingSection, setAddingSection] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newKind, setNewKind] = useState<SectionKind>('stateful')

  const [deletingSection, setDeletingSection] = useState<WikiSection | null>(null)
  const [purgeSection, setPurgeSection] = useState(false)
  const [deletingEntry, setDeletingEntry] = useState<ChronicleEntry | null>(null)
  const [clearingSection, setClearingSection] = useState<WikiSection | null>(null)
  const [deletingPage, setDeletingPage] = useState(false)
  const [summaryDraft, setSummaryDraft] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setPage(await api.getWikiPage(subjectType, subjectId))
    } catch (cause) {
      setMissing(true)
      fromError(cause, '문서를 불러오지 못했습니다.')
    }
  }, [subjectType, subjectId, fromError])

  useEffect(() => {
    void load()
  }, [load])

  /** Every write comes back with the whole page, so the view never guesses. */
  const apply = (next: WikiPage) => setPage(next)

  const openEditor = (section: WikiSection) => {
    setEditing(section)
    setDraft(section.kind === 'log' ? '' : section.current)
    setReason('')
  }

  const saveEntry = async () => {
    if (!editing || !draft.trim()) return
    setBusy(true)
    try {
      apply(
        await api.addChronicleEntry(subjectType, subjectId, editing.key, {
          value: draft.trim(),
          reason: reason.trim(),
        }),
      )
      success(`'${editing.title}'에 기록을 남겼습니다.`)
      setEditing(null)
    } catch (cause) {
      fromError(cause, '기록하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const addSection = async () => {
    if (!newTitle.trim()) return
    setBusy(true)
    try {
      apply(
        await api.addWikiSection(subjectType, subjectId, {
          title: newTitle.trim(),
          kind: newKind,
        }),
      )
      success(`'${newTitle.trim()}' 섹션을 추가했습니다.`)
      setAddingSection(false)
      setNewTitle('')
      setNewKind('stateful')
    } catch (cause) {
      fromError(cause, '섹션을 추가하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const removeSection = async (section: WikiSection, purge: boolean) => {
    setBusy(true)
    try {
      apply(await api.deleteWikiSection(subjectType, subjectId, section.key, purge))
      success(
        purge
          ? `'${section.title}' 섹션과 그 기록을 모두 지웠습니다.`
          : `'${section.title}' 섹션을 지웠습니다. 기록은 그대로 남아 있습니다.`,
      )
    } catch (cause) {
      fromError(cause, '섹션을 지우지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const saveSummary = async () => {
    if (summaryDraft === null) return
    setBusy(true)
    try {
      apply(await api.setWikiSummary(subjectType, subjectId, summaryDraft))
      setSummaryDraft(null)
    } catch (cause) {
      fromError(cause, '개요를 저장하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const retract = async (entryId: string) => {
    setBusy(true)
    try {
      await api.retractChronicleEntry(entryId)
      await load()
      success('기록을 취소했습니다. 이전 값으로 돌아갑니다.')
    } catch (cause) {
      fromError(cause, '취소하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const removeEntry = async (entryId: string) => {
    setBusy(true)
    try {
      await api.deleteChronicleEntry(entryId)
      await load()
      success('기록을 삭제했습니다.')
    } catch (cause) {
      fromError(cause, '삭제하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const clearSection = async (section: WikiSection) => {
    setBusy(true)
    try {
      apply(await api.clearWikiSection(subjectType, subjectId, section.key))
      await refresh()
      success(`'${section.title}' 내용을 지웠습니다.`)
    } catch (cause) {
      fromError(cause, '내용을 지우지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const removePage = async () => {
    setBusy(true)
    try {
      await api.deleteWikiPage(subjectType, subjectId)
      await refresh()
      success(`'${page?.title}' 문서를 삭제했습니다.`)
      navigate('/wiki')
    } catch (cause) {
      fromError(cause, '문서를 삭제하지 못했습니다.')
      setBusy(false)
    }
  }

  const restore = async (entryId: string) => {
    setBusy(true)
    try {
      await api.restoreChronicleEntry(entryId)
      await load()
    } catch (cause) {
      fromError(cause, '되살리지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  if (missing) {
    return (
      <EmptyState
        icon={ArrowLeft}
        title="문서를 열 수 없습니다"
        description="메모리 계층이 꺼져 있거나 문서가 없습니다."
        action={
          <Button variant="primary" onClick={() => navigate('/wiki')}>
            위키 목록으로
          </Button>
        }
      />
    )
  }
  if (page === null) return <div className="sw-panel h-72 animate-pulse-soft" />

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={() => navigate('/wiki')}>
            위키
          </Button>
          <h1 className="mt-2 truncate text-2xl font-semibold tracking-tight text-ink">
            {page.title}
          </h1>
          <p className="mt-1 flex items-center gap-2 text-xs text-ink-muted">
            <Badge>{TYPE_LABELS[page.subject_type]}</Badge>
            {page.retired && <Badge tone="warn">삭제된 인물</Badge>}
            <span className="font-mono">{page.subject_id}</span>
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button icon={Plus} onClick={() => setAddingSection(true)} disabled={busy}>
            섹션 추가
          </Button>
          {deletable(page.subject_type) && (
            <Button
              variant="danger"
              icon={Trash2}
              onClick={() => setDeletingPage(true)}
              disabled={busy}
            >
              문서 삭제
            </Button>
          )}
        </div>
      </div>

      {page.retired && (
        <p className="rounded-lg border border-line bg-white/3 p-3 text-sm text-ink-dim">
          {page.retired_note || '등장인물 목록에서 삭제되었습니다.'} 이미 회차에 기록이
          남아 있어 문서는 그대로 두었습니다. 앞으로 쓰는 회차에는 등장하지 않습니다.
        </p>
      )}

      {/* 개요 */}
      <Panel
        title="개요"
        actions={
          summaryDraft === null ? (
            <IconButton
              icon={Pencil}
              title="개요 편집"
              onClick={() => setSummaryDraft(page.summary)}
            />
          ) : (
            <>
              <Button size="sm" variant="ghost" onClick={() => setSummaryDraft(null)}>
                취소
              </Button>
              <Button size="sm" variant="primary" loading={busy} onClick={() => void saveSummary()}>
                저장
              </Button>
            </>
          )
        }
      >
        {summaryDraft === null ? (
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-ink-dim">
            {page.summary || (
              <span className="text-ink-muted">
                이 문서를 한 문단으로 소개해 주세요. (선택)
              </span>
            )}
          </p>
        ) : (
          <TextArea
            rows={4}
            value={summaryDraft}
            onChange={(event) => setSummaryDraft(event.target.value)}
            placeholder="예: 지극히 평범한 고등학생. 눈에 띄는 걸 싫어하지만 정의감은 있다."
          />
        )}
      </Panel>

      {/* 목차 */}
      <nav className="flex flex-wrap gap-1.5">
        {page.sections.map((section, index) => (
          <a
            key={section.key}
            href={`#${encodeURIComponent(section.key)}`}
            className="rounded-md border border-line px-2 py-1 text-xs text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            {index + 1}. {section.title}
          </a>
        ))}
      </nav>

      {page.sections.map((section) => (
        <SectionPanel
          key={section.key}
          section={section}
          subjectType={page.subject_type}
          busy={busy}
          onEdit={() => openEditor(section)}
          onDelete={() => {
            setPurgeSection(false)
            setDeletingSection(section)
          }}
          onRetract={(entry) => void retract(entry.entry_id)}
          onRestore={(entry) => void restore(entry.entry_id)}
          onDeleteEntry={setDeletingEntry}
          onClear={() => setClearingSection(section)}
        />
      ))}

      {/* 섹션 값 고치기 = 내력에 한 줄 더하기 */}
      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing ? `${editing.title} 기록하기` : ''}
        description={
          editing?.kind === 'log'
            ? '이 섹션에는 회차별 기록이 쌓입니다. 새 기록을 추가합니다.'
            : '덮어쓰지 않습니다. 지금 값은 내력에 남고, 적으신 것이 새 값이 됩니다.'
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)} disabled={busy}>
              취소
            </Button>
            <Button
              variant="primary"
              loading={busy}
              disabled={!draft.trim() || busy}
              onClick={() => void saveEntry()}
            >
              기록하기
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {editing?.kind !== 'log' && editing?.current && (
            <div className="rounded-lg border border-line bg-white/2 p-3">
              <p className="text-xs text-ink-muted">지금 값</p>
              <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-ink-dim">
                {editing.current}
              </p>
            </div>
          )}
          <TextArea
            label={editing?.kind === 'log' ? '새 기록' : '새 값'}
            rows={6}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <TextField
            label="이유 (선택)"
            hint="왜 이렇게 바뀌었는지 적어 두면, 나중에 작품 전체를 검수할 때 근거가 됩니다."
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      </Modal>

      {/* 섹션 추가 */}
      <Modal
        open={addingSection}
        onClose={() => setAddingSection(false)}
        title="섹션 추가"
        description="능력, 과거사, 명대사처럼 원하는 항목을 만드실 수 있습니다. AI도 여기에 기록합니다."
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddingSection(false)} disabled={busy}>
              취소
            </Button>
            <Button
              variant="primary"
              loading={busy}
              disabled={!newTitle.trim() || busy}
              onClick={() => void addSection()}
            >
              추가
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextField
            label="섹션 이름"
            placeholder="예: 능력"
            value={newTitle}
            onChange={(event) => setNewTitle(event.target.value)}
          />
          <SelectField
            label="종류"
            hint="상태형은 '지금 값'이 있고 그 변천사가 쌓입니다. 기록형은 회차별 기록만 쌓입니다."
            value={newKind}
            onChange={(event) => setNewKind(event.target.value as SectionKind)}
            options={[
              { value: 'stateful', label: '상태형 — 지금 값 + 변천사 (외모, 성격처럼)' },
              { value: 'log', label: '기록형 — 회차별 기록만 (작중 행적처럼)' },
            ]}
          />
        </div>
      </Modal>

      <ConfirmDialog
        open={deletingSection !== null}
        onClose={() => setDeletingSection(null)}
        onConfirm={() => deletingSection && void removeSection(deletingSection, purgeSection)}
        title={`'${deletingSection?.title}' 섹션을 지울까요?`}
        confirmLabel="섹션 지우기"
        message={
          <>
            문서에서 이 섹션이 사라집니다.
            <label className="mt-3 flex cursor-pointer items-center gap-2 text-ink">
              <input
                type="checkbox"
                className="size-4 accent-bad"
                checked={purgeSection}
                onChange={(event) => setPurgeSection(event.target.checked)}
              />
              이 섹션의 기록도 함께 삭제
            </label>
            <p className="mt-2 text-ink-muted">
              {purgeSection
                ? '기록까지 모두 지워지며 되돌릴 수 없습니다.'
                : '지금까지의 기록은 지워지지 않습니다. 같은 이름으로 다시 만들면 그대로 돌아옵니다.'}
            </p>
          </>
        }
      />

      <ConfirmDialog
        open={clearingSection !== null}
        onClose={() => setClearingSection(null)}
        onConfirm={() => clearingSection && void clearSection(clearingSection)}
        title={`'${clearingSection?.title}' 내용을 지울까요?`}
        confirmLabel="내용 지우기"
        message={
          <>
            <p>
              이 섹션의 지금 값과 내력이 모두 지워져 빈칸이 됩니다
              {clearingSection?.bound_field ? ' (인물·세계관 설정에 적힌 값도 함께 비워집니다)' : ''}.
              다음 회차부터 AI도 이 내용을 보지 않습니다.
            </p>
            <p className="mt-2 text-ink-muted">
              되돌릴 수 없습니다. 기록 한 줄만 지우시려면 내력에서 그 줄의 삭제 버튼을 쓰세요.
            </p>
          </>
        }
      />

      <ConfirmDialog
        open={deletingPage}
        onClose={() => setDeletingPage(false)}
        onConfirm={() => void removePage()}
        title={`'${page.title}' 문서를 삭제할까요?`}
        confirmLabel="문서 삭제"
        message={deletePageMessage(page.subject_type)}
      />

      <ConfirmDialog
        open={deletingEntry !== null}
        onClose={() => setDeletingEntry(null)}
        onConfirm={() => deletingEntry && void removeEntry(deletingEntry.entry_id)}
        title="이 기록을 삭제할까요?"
        confirmLabel="삭제"
        message={
          <>
            <p className="rounded-lg border border-line bg-white/2 p-3 whitespace-pre-wrap text-ink">
              {deletingEntry?.value}
            </p>
            <p className="mt-2 text-ink-muted">
              취소와 달리 흔적이 남지 않고 되돌릴 수 없습니다. 이 섹션은 바로 앞의 기록(없으면
              처음 설정)으로 돌아갑니다. 흔적을 남기고 싶으시면 '이 기록 취소'를 쓰세요.
            </p>
          </>
        }
      />
    </div>
  )
}

// ==========================================================================
// One section
// ==========================================================================

/**
 * What "지금 값" means depends on the page.
 *
 * On a character or a place it is what the model is told when the next chapter
 * is written. On the work's own page it deliberately is not: the arc and the
 * planned ending reach the stages that plan an episode and stop there, because
 * a character who has read the ending stops being surprised by it. Saying the
 * same sentence on both pages would be a lie on one of them — and the lie
 * would discourage an author from writing the ending down at all.
 */
function currentValueHint(subjectType: SubjectType): string {
  return subjectType === 'story'
    ? '지금 값 — 회차를 기획할 때 참고하며, 인물과 본문 작성에는 전달되지 않습니다.'
    : '지금 값 — 다음 회차를 쓸 때 AI가 보는 값입니다.'
}

function SectionPanel({
  section,
  subjectType,
  busy,
  onEdit,
  onDelete,
  onRetract,
  onRestore,
  onDeleteEntry,
  onClear,
}: {
  section: WikiSection
  subjectType: SubjectType
  busy: boolean
  onEdit: () => void
  onDelete: () => void
  onRetract: (entry: WikiSection['entries'][number]) => void
  onRestore: (entry: WikiSection['entries'][number]) => void
  onDeleteEntry: (entry: WikiSection['entries'][number]) => void
  onClear: () => void
}) {
  const isLog = section.kind === 'log'
  // A section that has never moved opens closed: the interesting ones are the
  // ones with a history, and a page of empty timelines hides them.
  const [open, setOpen] = useState(section.entries.length > 0)

  return (
    <section id={encodeURIComponent(section.key)} className="sw-panel p-5">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold tracking-tight text-ink">
            {section.title}
            {section.author_made && <Badge>직접 만든 섹션</Badge>}
            {isLog && <Badge tone="violet">기록형</Badge>}
          </h3>
          {!isLog && (
            <p className="mt-2 text-sm leading-relaxed whitespace-pre-wrap text-ink">
              {section.current || <span className="text-ink-muted">아직 비어 있습니다.</span>}
            </p>
          )}
          {!isLog && section.current && (
            <p className="mt-1 text-[0.7rem] text-ink-muted">
              {currentValueHint(subjectType)}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            icon={Pencil}
            title={isLog ? '기록 추가' : '값 바꾸기'}
            onClick={onEdit}
            disabled={busy}
          />
          {(section.current.trim() !== '' || section.entries.length > 0) && (
            <IconButton
              icon={Eraser}
              title="내용 지우기"
              variant="danger"
              onClick={onClear}
              disabled={busy}
            />
          )}
          {section.author_made && (
            <IconButton icon={Trash2} title="섹션 지우기" variant="danger" onClick={onDelete} disabled={busy} />
          )}
        </div>
      </header>

      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="mt-3 flex items-center gap-1 text-xs text-ink-muted transition-colors hover:text-ink"
      >
        <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
        내력 {section.entries.length > 0 && `(${section.entries.length})`}
      </button>

      {open && (
        <div className="mt-3">
          <Chronicle
            entries={section.entries}
            isLog={isLog}
            busy={busy}
            onRetract={onRetract}
            onRestore={onRestore}
            onDelete={onDeleteEntry}
          />
        </div>
      )}
    </section>
  )
}
