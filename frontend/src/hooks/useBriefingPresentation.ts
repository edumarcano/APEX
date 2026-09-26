import { useCallback, useEffect, useRef, useState } from 'react'

import type { BriefingSessionDetail } from '../types/briefings'

type Options = {
  session: BriefingSessionDetail | null
  isLoadingSession: boolean
  onMarkPresented: (sessionId: string) => Promise<void>
}

/**
 * Marks a completed briefing as presented once its sentinel is at least half
 * visible while the document is visible. Each session is acknowledged at most
 * once per mount; a failed write clears the guard so a later sighting retries.
 * Attach the returned ref only where the artifact is actually rendered.
 */
export function useBriefingPresentation({
  session,
  isLoadingSession,
  onMarkPresented,
}: Options): (element: HTMLElement | null) => void {
  const [element, setElement] = useState<HTMLElement | null>(null)
  const visibleRef = useRef(false)
  const acknowledgedRef = useRef(new Set<string>())
  const acknowledgeIfVisible = useCallback((): void => {
    if (!session || !visibleRef.current || document.visibilityState !== 'visible' || session.presented_at || acknowledgedRef.current.has(session.id)) return
    acknowledgedRef.current.add(session.id)
    void onMarkPresented(session.id).catch(() => acknowledgedRef.current.delete(session.id))
  }, [onMarkPresented, session])
  useEffect(() => {
    visibleRef.current = false
    if (!element || isLoadingSession || session?.run_status !== 'completed' || !session.artifact || session.presented_at) return undefined
    if (typeof IntersectionObserver === 'undefined') {
      const rect = element.getBoundingClientRect()
      visibleRef.current = rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth
      acknowledgeIfVisible()
      return undefined
    }
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[0]
      visibleRef.current = Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.5)
      acknowledgeIfVisible()
    }, { threshold: [0.5] })
    const handleVisibility = (): void => acknowledgeIfVisible()
    document.addEventListener('visibilitychange', handleVisibility)
    observer.observe(element)
    return () => {
      observer.disconnect()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [acknowledgeIfVisible, element, isLoadingSession, session])
  return setElement
}
