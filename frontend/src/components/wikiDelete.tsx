/**
 * 위키 문서 삭제 — 목록과 문서 화면이 같은 규칙과 같은 경고를 쓴다.
 *
 * 인물·장소·규칙은 프로젝트에 있기 때문에 문서가 있다. 그래서 문서만 지우면
 * 바로 다시 생긴다 — 위키에서 지우면 그 대상 자체가 지워진다. 작품과 세계관
 * 문서는 나머지가 매달린 틀이라 통째로는 지우지 않고, 섹션별로 비운다.
 */

import type { ReactNode } from 'react'

import type { SubjectType } from '@/types/storyweaver'

export const deletable = (subjectType: SubjectType): boolean =>
  subjectType !== 'story' && subjectType !== 'world'

const WHAT_GOES: Partial<Record<SubjectType, string>> = {
  character: '이 인물이 등장인물 목록에서도 삭제되고, 다른 인물과의 관계도 함께 지워집니다.',
  location: '이 장소가 세계관에서도 삭제됩니다. 안에 속한 장소들은 한 단계 위로 올라갑니다.',
  rule: '이 규칙이 세계관에서도 삭제됩니다.',
}

export function deletePageMessage(subjectType: SubjectType): ReactNode {
  return (
    <>
      <p>문서와 그 안의 기록이 모두 지워지며 되돌릴 수 없습니다.</p>
      {WHAT_GOES[subjectType] && <p className="mt-2">{WHAT_GOES[subjectType]}</p>}
      <p className="mt-2 text-ink-muted">이미 써 둔 회차 본문은 바뀌지 않습니다.</p>
    </>
  )
}
