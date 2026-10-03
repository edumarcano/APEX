import type { DesktopPlatform } from './contracts'

/** Load Tauri APIs only after the host has been identified as a native WebView. */
export async function loadDesktopPlatform(): Promise<DesktopPlatform> {
  const { createTauriPlatform } = await import('./tauri')
  return createTauriPlatform()
}
