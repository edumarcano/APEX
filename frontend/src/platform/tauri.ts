import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

import type { DesktopBackendState, DesktopPlatform } from './contracts'

const BACKEND_STATE_EVENT = 'desktop-backend-state'

export function createTauriPlatform(): DesktopPlatform {
  return {
    getBackendStatus: () => invoke<DesktopBackendState>('desktop_backend_status'),
    retryBackend: () => invoke<DesktopBackendState>('desktop_backend_retry'),
    quit: () => invoke<void>('desktop_quit'),
    subscribeBackendState: async (onWakeup) => listen(BACKEND_STATE_EVENT, onWakeup),
  }
}
