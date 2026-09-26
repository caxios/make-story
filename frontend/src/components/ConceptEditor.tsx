/**
 * 기획 직접 수정 — AI에게 부탁하지 않고, 작가가 원하는 대로 바로 고친다.
 *
 * 다듬기는 "주인공을 더 어리게 해줘"처럼 방향을 말하는 것이고, 이건 이름
 * 하나, 결말 한 줄, 3화 구상 한 문장을 정확히 원하는 대로 적는 것이다. 모델을
 * 부르지 않는다. 확정한 뒤에도 쓸 수 있고, 그때는 '작품에 반영'을 눌러야
 * 작품에 들어간다.
 */

import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button, IconButton, Modal, TextArea, TextField } from '@/components/ui'
import type { ConceptCharacter, StoryConcept } from '@/types/storyweaver'

const lines = (values: string[]) => values.join('\n')
const unlines = (text: string) =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

const blankCharacter = (): ConceptCharacter => ({
  name: '',
  role: '조연',
  age: null,
  gender: null,
  appearance: '',
  personality: '',
  speech: '',
  goal: '',
  secret: '',
  relationships: [],
})

export function ConceptEditor({
  open,
  concept,
  saving,
  onClose,
  onSave,
}: {
  open: boolean
  concept: StoryConcept
  saving: boolean
  onClose: () => void
  onSave: (edited: StoryConcept) => void
}) {
  const [draft, setDraft] = useState<StoryConcept>(concept)
  // 목록 칸은 편집하는 동안 줄바꿈을 그대로 두고, 저장할 때만 정리한다.
  const [rules, setRules] = useState('')
  const [places, setPlaces] = useState('')
  const [factions, setFactions] = useState('')

  useEffect(() => {
    if (!open) return
    setDraft(concept)
    setRules(lines(concept.rules))
    setPlaces(lines(concept.locations))
    setFactions(lines(concept.factions))
  }, [open, concept])

  const set = <K extends keyof StoryConcept>(key: K, value: StoryConcept[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const setCharacter = (index: number, patch: Partial<ConceptCharacter>) =>
    set(
      'characters',
      draft.characters.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    )

  const save = () =>
    onSave({
      ...draft,
      rules: unlines(rules),
      locations: unlines(places),
      factions: unlines(factions),
      characters: draft.characters
        .filter((c) => c.name.trim())
        .map((c) => ({
          ...c,
          relationships: unlines(c.relationships.join('\n')),
        })),
    })

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="기획 직접 수정"
      description="고친 그대로 저장됩니다. AI를 부르지 않습니다."
      footer={
        <>
          <Button onClick={onClose} disabled={saving}>
            취소
          </Button>
          <Button variant="primary" loading={saving} onClick={save}>
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        <section className="space-y-3">
          <p className="text-sm font-medium text-ink">작품</p>
          <TextField
            label="제목"
            value={draft.title}
            onChange={(e) => set('title', e.target.value)}
          />
          <TextField
            label="한 줄 요약"
            value={draft.logline}
            onChange={(e) => set('logline', e.target.value)}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <TextField
              label="장르"
              value={draft.genre}
              onChange={(e) => set('genre', e.target.value)}
            />
            <TextField
              label="톤"
              value={draft.tone}
              onChange={(e) => set('tone', e.target.value)}
            />
            <TextField
              label="시대"
              value={draft.era ?? ''}
              onChange={(e) => set('era', e.target.value || null)}
            />
          </div>
          <TextArea
            label="기획 의도 (세계관과 훅)"
            rows={5}
            value={draft.premise}
            onChange={(e) => set('premise', e.target.value)}
          />
          <TextArea
            label="전체 아크"
            rows={6}
            value={draft.arc}
            onChange={(e) => set('arc', e.target.value)}
          />
          <TextArea
            label="계획된 결말"
            rows={3}
            value={draft.ending}
            onChange={(e) => set('ending', e.target.value)}
          />
        </section>

        <section className="grid gap-3 sm:grid-cols-3">
          <TextArea
            label="세계의 규칙 (한 줄에 하나)"
            rows={5}
            value={rules}
            onChange={(e) => setRules(e.target.value)}
          />
          <TextArea
            label="장소 (한 줄에 하나)"
            rows={5}
            value={places}
            onChange={(e) => setPlaces(e.target.value)}
          />
          <TextArea
            label="세력 (한 줄에 하나)"
            rows={5}
            value={factions}
            onChange={(e) => setFactions(e.target.value)}
          />
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-ink">인물 {draft.characters.length}명</p>
            <Button
              size="sm"
              icon={Plus}
              onClick={() => set('characters', [...draft.characters, blankCharacter()])}
            >
              인물 추가
            </Button>
          </div>
          <ul className="space-y-3">
            {draft.characters.map((character, index) => (
              <li key={index} className="space-y-2 rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-end gap-2">
                  <TextField
                    className="min-w-32 flex-1"
                    label="이름"
                    value={character.name}
                    onChange={(e) => setCharacter(index, { name: e.target.value })}
                  />
                  <TextField
                    className="min-w-32 flex-1"
                    label="역할"
                    value={character.role}
                    onChange={(e) => setCharacter(index, { role: e.target.value })}
                  />
                  <TextField
                    className="w-20"
                    label="나이"
                    type="number"
                    value={character.age ?? ''}
                    onChange={(e) =>
                      setCharacter(index, {
                        age: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  />
                  <TextField
                    className="w-24"
                    label="성별"
                    value={character.gender ?? ''}
                    onChange={(e) => setCharacter(index, { gender: e.target.value || null })}
                  />
                  <IconButton
                    icon={Trash2}
                    title="이 인물 빼기"
                    variant="danger"
                    className="mb-0.5"
                    onClick={() =>
                      set(
                        'characters',
                        draft.characters.filter((_, i) => i !== index),
                      )
                    }
                  />
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <TextArea
                    label="외모"
                    rows={2}
                    value={character.appearance}
                    onChange={(e) => setCharacter(index, { appearance: e.target.value })}
                  />
                  <TextArea
                    label="성격"
                    rows={2}
                    value={character.personality}
                    onChange={(e) => setCharacter(index, { personality: e.target.value })}
                  />
                  <TextArea
                    label="말투"
                    rows={2}
                    value={character.speech}
                    onChange={(e) => setCharacter(index, { speech: e.target.value })}
                  />
                  <TextArea
                    label="관계 (한 줄에 하나, '이름 — 관계')"
                    rows={2}
                    value={lines(character.relationships)}
                    onChange={(e) =>
                      setCharacter(index, {
                        relationships: e.target.value.split('\n'),
                      })
                    }
                  />
                  <TextField
                    label="목표"
                    value={character.goal}
                    onChange={(e) => setCharacter(index, { goal: e.target.value })}
                  />
                  <TextField
                    label="비밀"
                    value={character.secret}
                    onChange={(e) => setCharacter(index, { secret: e.target.value })}
                  />
                </div>
              </li>
            ))}
          </ul>
        </section>

        {draft.episodes.length > 0 && (
          <section>
            <p className="mb-2 text-sm font-medium text-ink">회차 구상</p>
            <ul className="space-y-2">
              {draft.episodes.map((episode, index) => (
                <li key={episode.number} className="flex items-start gap-2">
                  <span className="mt-2 w-10 shrink-0 text-right font-mono text-xs text-ink-muted">
                    {episode.number}화
                  </span>
                  <textarea
                    className="sw-field w-full text-sm"
                    rows={2}
                    value={episode.line}
                    onChange={(e) =>
                      set(
                        'episodes',
                        draft.episodes.map((ep, i) =>
                          i === index ? { ...ep, line: e.target.value } : ep,
                        ),
                      )
                    }
                  />
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Modal>
  )
}
