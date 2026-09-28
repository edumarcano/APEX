import { useSyncExternalStore } from 'react'

function readBrowserOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine
}

function subscribeToBrowserOnline(onChange: () => void): () => void {
  window.addEventListener('online', onChange)
  window.addEventListener('offline', onChange)
  return () => {
    window.removeEventListener('online', onChange)
    window.removeEventListener('offline', onChange)
  }
}

/** Tracks the browser's own network signal without probing cloud providers. */
export function useBrowserOnline(): boolean {
  return useSyncExternalStore(
    subscribeToBrowserOnline,
    readBrowserOnline,
    () => true,
  )
}
