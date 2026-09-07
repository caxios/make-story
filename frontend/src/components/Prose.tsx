/**
 * Generated prose, shown the way a reader would meet it.
 *
 * The sanitizer is not decoration. A structured-output response occasionally
 * leaks its own envelope into the text — `additional_kwargs={...}`, a base64
 * `signature`, literal `\n` that was never unescaped — and a reader must never
 * see any of it. This mirrors `agents/writer.py::_clean` and
 * `ui/components.py::render_prose`, so both front ends sanitize identically.
 */

import { useMemo } from 'react'

import { cn } from '@/lib/cn'

export const SCENE_BREAK = '◇◇◇'

/** A paragraph that opens with a quote mark, in either language's convention. */
const DIALOGUE = /^\s*["“”'‘’「『]/

const JUNK = [
  // A metadata dict the model echoed back around its own output.
  /(?:extras|additional_kwargs|response_metadata|safety_ratings|usage_metadata)["']?\s*[:=]\s*\{[^}]{20,}\}/gs,
  // A signed-response blob.
  /["']?signature["']?\s*[:=]\s*["'][A-Za-z0-9+/=]{40,}["']/g,
  // A stray token count.
  /["']?\w+_token_count["']?\s*[:=]\s*\d+/g,
]

// A LangChain content-block list that reached the page stringified rather than
// unwrapped: `[{'type': 'text', 'text': '…the whole chapter…'}, …]`.
const CONTENT_BLOCK_MARKER = /\[\s*\{\s*["']type["']\s*:\s*["']text["']/
const CONTENT_BLOCK = /["']text["']\s*:\s*'((?:[^'\\]|\\.)*)'/g

/** Mirrors `agents/writer.py::_unwrap_content_blocks`. */
function unwrapContentBlocks(text: string): string {
  if (!CONTENT_BLOCK_MARKER.test(text)) return text
  const blocks = [...text.matchAll(CONTENT_BLOCK)].map((match) => match[1] ?? '')
  if (blocks.length === 0) return text
  return blocks
    .map((block) =>
      // Backslash-escapes last, or it re-reads the ones it just wrote.
      block
        .replace(/\\n/g, '\n')
        .replace(/\\t/g, '\t')
        .replace(/\\'/g, "'")
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\'),
    )
    .join('\n\n')
}

export function sanitize(text: string): string {
  // Unwrapping first: the junk patterns would otherwise chew through the
  // structure it needs to read.
  let cleaned = unwrapContentBlocks(text)
  for (const pattern of JUNK) cleaned = cleaned.replace(pattern, '')
  // Literal backslash-n, not a real newline that already survived.
  cleaned = cleaned.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
  cleaned = cleaned.replace(/\n{3,}/g, '\n\n')
  return cleaned.trim()
}

export interface ReaderSettings {
  serif: boolean
  fontSize: number
  lineHeight: number
  measure: number
}

export const DEFAULT_READER: ReaderSettings = {
  serif: true,
  fontSize: 18,
  lineHeight: 1.9,
  measure: 70,
}

export function Prose({
  text,
  settings,
  className,
}: {
  text: string
  settings: ReaderSettings
  className?: string
}) {
  const sections = useMemo(
    () =>
      sanitize(text)
        .split(SCENE_BREAK)
        .map((section) => section.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean))
        .filter((paragraphs) => paragraphs.length > 0),
    [text],
  )

  return (
    <div
      className={cn('mx-auto', className)}
      style={{
        fontFamily: settings.serif ? 'var(--font-serif)' : 'var(--font-sans)',
        fontSize: `${settings.fontSize}px`,
        lineHeight: settings.lineHeight,
        // `ch` on the reading font, so the measure is a real character count
        // rather than a pixel width that changes meaning when the font does.
        maxWidth: `${settings.measure}ch`,
      }}
    >
      {sections.map((paragraphs, sectionIndex) => (
        <section key={sectionIndex}>
          {sectionIndex > 0 && (
            <div
              aria-hidden
              className="my-10 text-center text-sm tracking-[0.55em] text-accent/70 select-none"
              style={{ textIndent: '0.55em' }}
            >
              {SCENE_BREAK}
            </div>
          )}
          {paragraphs.map((paragraph, index) => (
            <p
              key={index}
              className={cn(
                'mb-[1.3em] whitespace-pre-wrap',
                // Speech sits a shade apart from narration, so it separates at
                // a glance without the paragraph looking highlighted.
                DIALOGUE.test(paragraph) ? 'text-ink' : 'text-ink-dim',
              )}
            >
              {paragraph}
            </p>
          ))}
        </section>
      ))}
    </div>
  )
}
