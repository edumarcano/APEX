import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import type { DesktopBackendState, DesktopLocationCheck, DesktopPlatform, DesktopServicesStatus, DesktopSetupState, DesktopVisibilityState } from './contracts'

const BACKEND_STATE_EVENT = 'desktop-backend-state'
const SERVICES_STATE_EVENT = 'desktop-services-state'
const DEVICE_STATE_EVENT = 'desktop-device-state'
const SETUP_STATE_EVENT = 'desktop-setup-state'
const VISIBILITY_STATE_EVENT = 'desktop-visibility-state'

function isDesktopVisibilityState(value: unknown): value is DesktopVisibilityState {
  return value !== null && typeof value === 'object' &&
    typeof (value as DesktopVisibilityState).revision === 'number' &&
    Number.isSafeInteger((value as DesktopVisibilityState).revision) &&
    (value as DesktopVisibilityState).revision >= 0 &&
    typeof (value as DesktopVisibilityState).visible === 'boolean'
}

export function createTauriPlatform(): DesktopPlatform {
  return {
    getVisibilityState: () => invoke<DesktopVisibilityState>('desktop_visibility_state'),
    subscribeVisibilityState: async (onChange) => listen<unknown>(VISIBILITY_STATE_EVENT, (event) => {
      if (isDesktopVisibilityState(event.payload)) onChange(event.payload)
    }),
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
