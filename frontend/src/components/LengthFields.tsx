/**
 * 작품 분량 — 전체 몇 화짜리인지, 그중 처음 몇 화를 미리 구상할지.
 *
 * 둘은 다른 숫자다. 400화짜리 작품의 처음 12화는 작품 전체가 아니라 1부의
 * 도입부다. 이 구분이 없던 때는 12화 구상이 곧 작품 전체였고, 그래서 12화
 * 만에 결말에 닿았다.
 */

import { cn } from '@/lib/cn'

const PRESETS = [50, 100, 200, 300, 400, 500]

export function LengthFields({
  target,
  onTargetChange,
  opening,
  onOpeningChange,
  disabled = false,
}: {
  target: number
  onTargetChange: (value: number) => void
  /** 없으면 '처음 구상할 회차' 칸을 그리지 않는다. */
  opening?: number
  onOpeningChange?: (value: number) => void
  disabled?: boolean
}) {
  const clamp = (value: number, max: number) =>
    Number.isFinite(value) ? Math.max(1, Math.min(max, Math.round(value))) : 1

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-ink-dim">목표 총 회차</span>
          <span className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={2000}
              className="sw-field w-28 text-sm"
              value={target}
              disabled={disabled}
              onChange={(event) => onTargetChange(clamp(Number(event.target.value), 2000))}
            />
            <span className="text-sm text-ink-muted">화</span>
          </span>
        </label>
        {opening !== undefined && onOpeningChange && (
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-ink-dim">처음 구상할 회차</span>
            <span className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={Math.min(40, target)}
                className="sw-field w-24 text-sm"
                value={opening}
                disabled={disabled}
                onChange={(event) =>
                  onOpeningChange(clamp(Number(event.target.value), Math.min(40, target)))
                }
              />
              <span className="text-sm text-ink-muted">화</span>
            </span>
          </label>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            disabled={disabled}
            onClick={() => onTargetChange(preset)}
            className={cn(
              'rounded-full border px-2.5 py-1 text-xs transition-colors',
              preset === target
                ? 'border-accent/50 bg-accent/10 text-accent-bright'
                : 'border-line text-ink-dim hover:border-line-strong hover:text-ink',
            )}
          >
            {preset}화
          </button>
        ))}
      </div>
      {opening !== undefined && (
        <p className="text-xs leading-relaxed text-ink-muted">
          전체 {target}화 중 처음 {Math.min(opening, target)}화(약{' '}
          {Math.max(1, Math.round((100 * Math.min(opening, target)) / target))}
          %)만 미리 구상합니다. 그 뒤 회차는 에피소드 큐에서 AI가 이 구조에 맞춰 이어 씁니다.
        </p>
      )}
    </div>
  )
}
