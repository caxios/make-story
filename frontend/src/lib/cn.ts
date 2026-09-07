import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Join class names, letting a later Tailwind utility win over an earlier one. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/** `1,423` — thousands separated, for word and token counts. */
export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}
