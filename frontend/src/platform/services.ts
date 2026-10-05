import { loadDesktopPlatform } from './index'
import type { DesktopLocationCheck, DesktopServicesStatus, DesktopVisibilityState } from './contracts'
import { safeExternalUrl } from '../lib/externalLinks'

export function isNativeDesktop(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export async function subscribeDesktopVisibilityState(
  onChange: (state: DesktopVisibilityState) => void,
): Promise<() => void> {
  if (!isNativeDesktop()) return () => undefined
  return (await loadDesktopPlatform()).subscribeVisibilityState(onChange)
}

export async function getDesktopVisibilityState(): Promise<DesktopVisibilityState | null> {
  if (!isNativeDesktop()) return null
  return (await loadDesktopPlatform()).getVisibilityState()
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

export async function checkDesktopLocationPermission(): Promise<DesktopLocationCheck | null> {
  if (!isNativeDesktop()) return null
  return (await loadDesktopPlatform()).checkLocationPermission()
}

export async function subscribeDesktopDeviceState(onWakeup: () => void): Promise<() => void> {
  if (!isNativeDesktop()) return () => undefined
  return (await loadDesktopPlatform()).subscribeDeviceState(onWakeup)
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
  const safeUrl = safeExternalUrl(url)
  if (!safeUrl) throw new Error('The link address is not a valid HTTP(S) URL.')
  if (isNativeDesktop()) {
    await (await loadDesktopPlatform()).openExternal(safeUrl)
    return
  }
  const opened = window.open(safeUrl, '_blank')
  if (!opened) {
    throw new Error('The browser could not open this link. Check its popup settings.')
  }
  opened.opener = null
}
