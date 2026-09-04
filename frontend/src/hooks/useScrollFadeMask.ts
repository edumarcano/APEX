import { useEffect, useRef, useState, type RefObject } from 'react'

export interface UseScrollFadeMaskResult<T extends HTMLElement> {
  elementRef: RefObject<T | null>
  canScrollDown: boolean
}

/**
 * Detects whether a scrollable container currently has overflow content below the fold.
 * Returns `canScrollDown = true` only when there is scrollable content remaining to be scrolled,
 * and `false` when the content fits without scrolling or the user has reached the bottom.
 */
export function useScrollFadeMask<T extends HTMLElement = HTMLElement>(): UseScrollFadeMaskResult<T> {
  const elementRef = useRef<T | null>(null)
  const [canScrollDown, setCanScrollDown] = useState(false)

  useEffect(() => {
    const element = elementRef.current
    if (!element) return

    const updateScrollFade = () => {
      // Content has vertical overflow exceeding client height by at least 1px
      const hasOverflow = element.scrollHeight > element.clientHeight + 1
      // Scrolled to within 2px of the bottom (tolerates fractional scaling / subpixel rounding)
      const isAtBottom = Math.ceil(element.scrollTop + element.clientHeight) >= element.scrollHeight - 2
      const nextCanScrollDown = hasOverflow && !isAtBottom

      setCanScrollDown((prev) => (prev !== nextCanScrollDown ? nextCanScrollDown : prev))
    }

    updateScrollFade()

    element.addEventListener('scroll', updateScrollFade, { passive: true })

    let resizeObserver: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(updateScrollFade)
      resizeObserver.observe(element)
    }

    let mutationObserver: MutationObserver | null = null
    if (typeof MutationObserver !== 'undefined') {
      mutationObserver = new MutationObserver(updateScrollFade)
      mutationObserver.observe(element, { childList: true, subtree: true, characterData: true })
    }

    return () => {
      element.removeEventListener('scroll', updateScrollFade)
      resizeObserver?.disconnect()
      mutationObserver?.disconnect()
    }
  }, [])

  return { elementRef, canScrollDown }
}
