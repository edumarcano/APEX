import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import type { DesktopBackendState, DesktopLocationCheck, DesktopPlatform, DesktopServicesStatus } from './contracts'

const BACKEND_STATE_EVENT = 'desktop-backend-state'
const SERVICES_STATE_EVENT = 'desktop-services-state'
const DEVICE_STATE_EVENT = 'desktop-device-state'

export function createTauriPlatform(): DesktopPlatform {
  return {
    getBackendStatus: () => invoke<DesktopBackendState>('desktop_backend_status'),
    retryBackend: () => invoke<DesktopBackendState>('desktop_backend_retry'),
    quit: () => invoke<void>('desktop_quit'),
    subscribeBackendState: async (onWakeup) => listen(BACKEND_STATE_EVENT, onWakeup),
    getServicesStatus: () => invoke<DesktopServicesStatus>('desktop_services_status'),
    retryServices: () => invoke<DesktopServicesStatus>('desktop_services_retry'),
    subscribeServicesState: async (onWakeup) => listen(SERVICES_STATE_EVENT, onWakeup),
    openExternal: (url) => invoke<void>('desktop_open_external', { url }),
    writeClipboardText: (text) => invoke<void>('desktop_write_clipboard', { text }),
    checkLocationPermission: () => invoke<DesktopLocationCheck>('desktop_check_location_permission'),
    subscribeDeviceState: async (onWakeup) => listen(DEVICE_STATE_EVENT, onWakeup),
  }
}
