export type RuntimeIdentity = {
  app_id: 'apex'
  app_version: string
  build_id: string
  instance_id: string
  pid: number
  hosting_mode: 'standalone' | 'managed'
  launch_id: string | null
  data_root_fingerprint: string
  shutdown_timeout_seconds: number
}

export type DesktopBackendPhase = 'starting' | 'ready' | 'failed' | 'stopping' | 'stopped'

export type DesktopBackendState = {
  revision: number
  generation: number
  phase: DesktopBackendPhase
  error_code: string | null
  runtime: RuntimeIdentity | null
}

export type DesktopServicesStatus = {
  revision: number
  generation: number
  preferences_ready: boolean
  requested: { launch_on_startup: boolean; completion_notifications: boolean }
  tray_available: boolean
  startup: { actual_enabled: boolean | null; error_code: string | null }
  notifications: {
    os_setting:
      | 'enabled'
      | 'disabled_app'
      | 'disabled_user'
      | 'disabled_policy'
      | 'disabled_manifest'
      | 'unavailable'
      | 'unknown'
    error_code: string | null
  }
}

export type DesktopVisibilityState = {
  revision: number
  visible: boolean
}

export type DesktopLocationCheck = {
  permission: 'unknown' | 'granted' | 'denied' | 'revoked' | 'unsupported'
  availability: 'unknown' | 'available' | 'unavailable' | 'timed_out' | 'unsupported'
}

export type ImportDisposition = 'copy' | 'missing' | 'retain_external' | 'reuse'

export type ImportItem = {
  path: string
  category: string
  disposition: ImportDisposition
  file_count: number
  total_bytes: number
}

export type ImportPreview = {
  preview_id: string
  can_import: boolean
  items: ImportItem[]
  warnings: string[]
  blockers: string[]
}

export type DesktopSetupPhase = 'checking' | 'choice_required' | 'preview_ready' | 'importing' | 'ready' | 'recovery_required' | 'failed'

export type DesktopSetupState = {
  revision: number
  phase: DesktopSetupPhase
  preview: ImportPreview | null
  progress: { stage: string; completed_bytes: number; total_bytes: number } | null
  error_code: string | null
}

export type DesktopPlatform = {
  getVisibilityState(): Promise<DesktopVisibilityState>
  subscribeVisibilityState(onChange: (state: DesktopVisibilityState) => void): Promise<() => void>
  getBackendStatus(): Promise<DesktopBackendState>
  retryBackend(): Promise<DesktopBackendState>
  quit(): Promise<void>
  subscribeBackendState(onWakeup: () => void): Promise<() => void>
  getServicesStatus(): Promise<DesktopServicesStatus>
  retryServices(): Promise<DesktopServicesStatus>
  subscribeServicesState(onWakeup: () => void): Promise<() => void>
  openExternal(url: string): Promise<void>
  writeClipboardText(text: string): Promise<void>
  checkLocationPermission(): Promise<DesktopLocationCheck>
  subscribeDeviceState(onWakeup: () => void): Promise<() => void>
  getSetupStatus(): Promise<DesktopSetupState>
  pickImportSource(): Promise<string | null>
  previewImport(sourceDir: string): Promise<DesktopSetupState>
  importData(previewId: string): Promise<DesktopSetupState>
  freshStart(): Promise<DesktopSetupState>
  recoverImport(): Promise<DesktopSetupState>
  subscribeSetupState(onWakeup: () => void): Promise<() => void>
}
