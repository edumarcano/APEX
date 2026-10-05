import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import type { DesktopBackendState, DesktopLocationCheck, DesktopPlatform, DesktopServicesStatus, DesktopSetupState } from './contracts'

const BACKEND_STATE_EVENT = 'desktop-backend-state'
const SERVICES_STATE_EVENT = 'desktop-services-state'
const DEVICE_STATE_EVENT = 'desktop-device-state'
const SETUP_STATE_EVENT = 'desktop-setup-state'

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
    getSetupStatus: () => invoke<DesktopSetupState>('desktop_setup_status'),
    pickImportSource: () => invoke<string | null>('desktop_import_pick_source'),
    previewImport: (sourceDir) => invoke<DesktopSetupState>('desktop_import_preview', { sourceDir }),
    importData: (previewId) => invoke<DesktopSetupState>('desktop_import_commit', { previewId }),
    freshStart: () => invoke<DesktopSetupState>('desktop_fresh_start'),
    recoverImport: () => invoke<DesktopSetupState>('desktop_import_recover'),
    subscribeSetupState: async (onWakeup) => listen(SETUP_STATE_EVENT, onWakeup),
  }
}
