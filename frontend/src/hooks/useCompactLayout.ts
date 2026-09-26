import { useEffect, useState } from 'react'

const COMPACT_LAYOUT_QUERY = '(max-width: 1279px), (max-height: 820px)'

/** Matches the design-system breakpoint where fullscreen HUD layouts collapse. */
export function useCompactLayout(): boolean {
  const [compact, setCompact] = useState(() => (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(COMPACT_LAYOUT_QUERY).matches
      : false
  ))
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(COMPACT_LAYOUT_QUERY)
    const update = (): void => setCompact(query.matches)
    update()
    query.addEventListener?.('change', update)
    return () => query.removeEventListener?.('change', update)
  }, [])
  return compact
}
