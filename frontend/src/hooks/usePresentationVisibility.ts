import { useSyncExternalStore } from 'react'

import type { DesktopVisibilityState } from '../platform/contracts'
import { getDesktopVisibilityState, isNativeDesktop, subscribeDesktopVisibilityState } from '../platform/services'

type Listener = () => void

let nativeHost = isNativeDesktop()
let nativeVisible = false
let visible = nativeHost ? false : (typeof document === 'undefined' || !document.hidden)
let revision = -1
let attached = false
let attachmentGeneration = 0
let detachNative: (() => void) | undefined
const listeners = new Set<Listener>()

function publish(nextVisible: boolean): void {
  if (visible === nextVisible) return
  visible = nextVisible
  for (const listener of listeners) listener()
}

function acceptNativeState(state: DesktopVisibilityState): void {
  if (!Number.isSafeInteger(state.revision) || state.revision < 0 || state.revision <= revision || typeof state.visible !== 'boolean') return
  revision = state.revision
  nativeVisible = state.visible
  publish(nativeVisible && !document.hidden)
}

function onDocumentVisibilityChange(): void {
  publish(nativeHost ? nativeVisible && !document.hidden : !document.hidden)
}

function attach(): void {
  if (attached || typeof document === 'undefined') return
  attached = true
  const generation = ++attachmentGeneration
  nativeHost = isNativeDesktop()
  document.addEventListener('visibilitychange', onDocumentVisibilityChange)
  if (!nativeHost) {
    publish(!document.hidden)
    return
  }
  nativeVisible = false
  publish(false)

  let cancelled = false
  let unsubscribe: (() => void) | undefined
  const isCurrentAttachment = (): boolean => (
    !cancelled && attached && attachmentGeneration === generation
  )
  detachNative = () => {
    cancelled = true
    const unlisten = unsubscribe
    unsubscribe = undefined
    unlisten?.()
  }
  void (async () => {
    try {
      unsubscribe = await subscribeDesktopVisibilityState((state) => {
        if (isCurrentAttachment()) acceptNativeState(state)
      })
      if (!isCurrentAttachment()) {
        unsubscribe()
        unsubscribe = undefined
        return
      }
      const snapshot = await getDesktopVisibilityState()
      if (!isCurrentAttachment()) return
      if (snapshot) acceptNativeState(snapshot)
    } catch {
      if (isCurrentAttachment()) {
        cancelled = true
        const unlisten = unsubscribe
        unsubscribe = undefined
        unlisten?.()
        nativeHost = false
        publish(!document.hidden)
      }
    }
  })()
}

function detach(): void {
  if (!attached) return
  attached = false
  attachmentGeneration += 1
  document.removeEventListener('visibilitychange', onDocumentVisibilityChange)
  detachNative?.()
  detachNative = undefined
  nativeHost = false
  nativeVisible = false
  revision = -1
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  attach()
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) detach()
  }
}

function getSnapshot(): boolean {
  return visible
}

/** Native windows use a revisioned visibility snapshot; browsers use document visibility. */
export function usePresentationVisibility(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}
