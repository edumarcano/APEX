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

export type DesktopPlatform = {
  getBackendStatus(): Promise<DesktopBackendState>
  retryBackend(): Promise<DesktopBackendState>
  quit(): Promise<void>
  subscribeBackendState(onWakeup: () => void): Promise<() => void>
}

