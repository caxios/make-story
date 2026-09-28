/**
 * 회차 개요·기획서에서 새로 생긴 설정을 작품에 등록하고, 무엇이 들어갔는지 알린다.
 *
 * 개요를 저장하는 곳(추가·수정·가져오기·구조 적용)은 저장 직후 `registerFrom`을
 * 부르고, 기획서는 서버가 저장할 때 직접 읽어 `registered`로 돌려주므로
 * `announce`만 부른다. 등록은 저장과 별개다 — 읽기에 실패해도 저장한 것은 그대로다.
 */

import { useCallback } from 'react'

import * as api from '@/api/client'
import { useToast } from '@/components/ToastContext'
import { useProject } from '@/state/ProjectContext'

const SHOWN = 4

export function useSettingsRegistration() {
  const { info, warning } = useToast()
  const { refresh } = useProject()

  const announce = useCallback(
    async (registered: string[] | undefined, failure?: string) => {
      if (failure) warning(`새 설정을 읽지 못했습니다: ${failure}`)
      if (!registered || registered.length === 0) return
      const shown = registered.slice(0, SHOWN).join(' · ')
      const more = registered.length > SHOWN ? ` 외 ${registered.length - SHOWN}개` : ''
      info(`새 설정 ${registered.length}개를 작품에 등록했습니다: ${shown}${more}`)
      await refresh()
    },
    [info, warning, refresh],
  )

  const registerFrom = useCallback(
    async (episodeNumbers: number[]) => {
      if (episodeNumbers.length === 0) return
      try {
        const { registered } = await api.extractSettings(episodeNumbers)
        await announce(registered)
      } catch (cause) {
        await announce([], cause instanceof Error ? cause.message : String(cause))
      }
    },
    [announce],
  )

  return { registerFrom, announce }
}
