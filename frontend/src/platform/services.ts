import { loadDesktopPlatform } from './index'
import type { DesktopServicesStatus } from './contracts'

export function isNativeDesktop(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export async function getDesktopServicesStatus(): Promise<DesktopServicesStatus | null> {
  if (!isNativeDesktop()) return null
  return (await loadDesktopPlatform()).getServicesStatus()
}

export async function retryDesktopServices(): Promise<DesktopServicesStatus | null> {
  if (!isNativeDesktop()) return null
  return (await loadDesktopPlatform()).retryServices()
}

export async function subscribeDesktopServicesState(onWakeup: () => void): Promise<() => void> {
  if (!isNativeDesktop()) return () => undefined
  return (await loadDesktopPlatform()).subscribeServicesState(onWakeup)
}

export async function writeClipboardText(text: string): Promise<void> {
  if (isNativeDesktop()) {
    await (await loadDesktopPlatform()).writeClipboardText(text)
    return
  }
  if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable in this browser.')
  await navigator.clipboard.writeText(text)
}

export async function openExternal(url: string): Promise<void> {
  if (!isNativeDesktop()) throw new Error('External link service is unavailable.')
  await (await loadDesktopPlatform()).openExternal(url)
}
