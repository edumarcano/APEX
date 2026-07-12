import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hasAttribute('disabled') && element.tabIndex !== -1,
  )
}

/**
 * Traps Tab focus inside `containerRef` while `active` is true and restores
 * focus to the previously focused element (or `restoreFocusRef`) on cleanup.
 */
export function useFocusTrap(
  active: boolean,
  containerRef: RefObject<HTMLElement | null>,
  restoreFocusRef?: RefObject<HTMLElement | null>,
): void {
  const previouslyFocusedRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!active) {
      return undefined
    }

    const container = containerRef.current
    if (!container) {
      return undefined
    }

    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null

    const restoreTargetAtOpen = restoreFocusRef?.current ?? null

    const focusable = getFocusableElements(container)
    const initial = focusable[0] ?? container
    initial.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') {
        return
      }

      const elements = getFocusableElements(container)
      if (elements.length === 0) {
        event.preventDefault()
        container.focus()
        return
      }

      const first = elements[0]
      const last = elements[elements.length - 1]
      const activeElement = document.activeElement

      if (event.shiftKey) {
        if (activeElement === first || !container.contains(activeElement)) {
          event.preventDefault()
          last.focus()
        }
        return
      }

      if (activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    container.addEventListener('keydown', handleKeyDown)

    return () => {
      container.removeEventListener('keydown', handleKeyDown)
      const restoreTarget = restoreTargetAtOpen ?? previouslyFocusedRef.current
      if (restoreTarget && document.contains(restoreTarget)) {
        restoreTarget.focus()
      }
    }
  }, [active, containerRef, restoreFocusRef])
}
