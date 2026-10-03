import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import App from '../App'
import { API_RUNTIME_IDENTITY } from '../lib/api'
import { loadDesktopPlatform } from './index'
import type { DesktopBackendState, DesktopPlatform, RuntimeIdentity } from './contracts'

const RUNTIME_CHECK_TIMEOUT_MS = 5_000
const STATUS_REFRESH_MS = 2_500

type AdmissionState = {
  backend: DesktopBackendState | null
  errorCode: string | null
  message: string | null
  admittedKey: string | null
}

const EMPTY: AdmissionState = { backend: null, errorCode: null, message: null, admittedKey: null }

export default function DesktopAdmission(): ReactElement {
  const [admission, setAdmission] = useState(EMPTY)
  const [platform, setPlatform] = useState<DesktopPlatform | null>(null)
  const [confirmRetry, setConfirmRetry] = useState(false)
  const [busy, setBusy] = useState(false)
  const latestRef = useRef<{ generation: number; revision: number; statusRequest: number; admittedKey: string | null }>({
    generation: -1,
    revision: -1,
    statusRequest: 0,
    admittedKey: null,
  })
  const verificationRef = useRef<{ key: string; controller: AbortController } | null>(null)
  const activeRef = useRef(false)

  const refresh = useCallback(async (owner: DesktopPlatform, alive: () => boolean): Promise<void> => {
    const statusRequest = ++latestRef.current.statusRequest
    try {
      const snapshot = await owner.getBackendStatus()
      if (!alive() || statusRequest !== latestRef.current.statusRequest) return
      if (!isBackendState(snapshot)) {
        verificationRef.current?.controller.abort()
        verificationRef.current = null
        latestRef.current.admittedKey = null
        setAdmission({ backend: null, errorCode: 'protocol_error', message: null, admittedKey: null })
        return
      }
      const latest = latestRef.current
      if (snapshot.generation < latest.generation ||
        (snapshot.generation === latest.generation && snapshot.revision < latest.revision)) return
      latestRef.current = { ...latest, generation: snapshot.generation, revision: snapshot.revision }
      if (snapshot.phase !== 'ready') {
        verificationRef.current?.controller.abort()
        verificationRef.current = null
        latestRef.current.admittedKey = null
        setAdmission({ backend: snapshot, errorCode: null, message: null, admittedKey: null })
        return
      }
      const admittedKey = `${snapshot.generation}:${snapshot.revision}`
      if (latestRef.current.admittedKey === admittedKey) {
        setAdmission((current) => ({ ...current, backend: snapshot }))
        return
      }
      if (verificationRef.current?.key === admittedKey) return
      verificationRef.current?.controller.abort()
      const controller = new AbortController()
      const verification = { key: admittedKey, controller }
      verificationRef.current = verification
      setAdmission({ backend: snapshot, errorCode: 'verifying_runtime', message: null, admittedKey: null })
      if (!isRuntimeIdentity(snapshot.runtime)) {
        verificationRef.current = null
        latestRef.current.admittedKey = null
        setAdmission({ backend: snapshot, errorCode: 'identity_mismatch', message: null, admittedKey: null })
        return
      }

      const timeout = window.setTimeout(() => controller.abort(), RUNTIME_CHECK_TIMEOUT_MS)
      const isCurrentVerification = (): boolean => alive() && latestRef.current.generation === snapshot.generation &&
        latestRef.current.revision === snapshot.revision && verificationRef.current === verification
      try {
        const response = await fetch(API_RUNTIME_IDENTITY, { signal: controller.signal, cache: 'no-store' })
        if (!isCurrentVerification()) return
        if (!response.ok) {
          setAdmission({ backend: snapshot, errorCode: response.status === 403 ? 'cors_rejected' : 'startup_failed', message: null, admittedKey: null })
          return
        }
        const runtime: unknown = await response.json()
        if (!isCurrentVerification()) return
        if (!isRuntimeIdentity(runtime) || !sameRuntimeIdentity(snapshot.runtime, runtime)) {
          latestRef.current.admittedKey = null
          setAdmission({ backend: snapshot, errorCode: 'identity_mismatch', message: null, admittedKey: null })
          return
        }
        latestRef.current.admittedKey = admittedKey
        setAdmission({ backend: snapshot, errorCode: null, message: null, admittedKey })
      } catch (error) {
        if (!isCurrentVerification()) return
        setAdmission({
          backend: snapshot,
          errorCode: controller.signal.aborted ? 'startup_timeout' : 'cors_rejected',
          message: controller.signal.aborted ? 'The local runtime identity check timed out. Confirm the backend has completed startup, then retry.' : error instanceof TypeError ? 'APEX could not reach its local backend. Check the desktop origin and backend status.' : null,
          admittedKey: null,
        })
      } finally {
        window.clearTimeout(timeout)
        if (verificationRef.current === verification) verificationRef.current = null
      }
    } catch {
      if (alive() && statusRequest === latestRef.current.statusRequest) {
        verificationRef.current?.controller.abort()
        verificationRef.current = null
        latestRef.current.admittedKey = null
        setAdmission({ backend: null, errorCode: 'protocol_error', message: null, admittedKey: null })
      }
    }
  }, [])

  useEffect(() => {
    let active = true
    let unsubscribe: (() => void) | undefined
    let timer = 0
    let owner: DesktopPlatform | undefined
    const alive = (): boolean => active
    activeRef.current = true

    void (async () => {
      try {
        owner = await loadDesktopPlatform()
        if (!active) return
        setPlatform(owner)
        // The event is only a wakeup. Never trust its payload to admit App.
        try {
          unsubscribe = await owner.subscribeBackendState(() => { void refresh(owner!, alive) })
        } catch {
          // Snapshot polling remains authoritative if event subscription fails.
        }
        if (!active) {
          unsubscribe?.()
          return
        }
        void refresh(owner, alive)
        timer = window.setInterval(() => { void refresh(owner!, alive) }, STATUS_REFRESH_MS)
      } catch {
        if (active) setAdmission({ backend: null, errorCode: 'resource_missing', message: null, admittedKey: null })
      }
    })()

    return () => {
      active = false
      activeRef.current = false
      window.clearInterval(timer)
      verificationRef.current?.controller.abort()
      verificationRef.current = null
      unsubscribe?.()
    }
  }, [refresh])

  const retry = async (): Promise<void> => {
    if (!platform) return
    setBusy(true)
    setConfirmRetry(false)
    try {
      await platform.retryBackend()
      if (activeRef.current) await refresh(platform, () => activeRef.current)
    } catch {
      if (activeRef.current) await refresh(platform, () => activeRef.current)
      setAdmission((current) => current.backend?.phase === 'ready' && current.admittedKey === `${current.backend.generation}:${current.backend.revision}`
        ? current
        : { ...current, errorCode: 'startup_failed', admittedKey: null })
    } finally {
      setBusy(false)
    }
  }

  const quit = async (): Promise<void> => {
    if (!platform) return
    setBusy(true)
    try {
      await platform.quit()
    } catch {
      setAdmission((current) => ({ ...current, errorCode: 'shutdown_failed', admittedKey: null }))
      setBusy(false)
    }
  }

  const backend = admission.backend
  if (backend?.phase === 'ready' && !admission.errorCode && backend.runtime && admission.admittedKey === `${backend.generation}:${backend.revision}`) return <App />
  if (backend?.phase === 'stopping' || backend?.phase === 'stopped') {
    return <StatusPanel title="APEX is shutting down" description="Wait for the desktop window to close." busy />
  }
  if (!backend && !admission.errorCode || backend?.phase === 'starting') {
    return <StatusPanel title="Starting APEX" description="Waiting for the owned backend to become ready." busy />
  }

  const code = admission.errorCode === 'verifying_runtime' ? null : admission.errorCode ?? backend?.error_code ?? 'startup_failed'
  const details = code === null ? 'Checking that the local API belongs to the backend started for this window.' : messageFor(code, admission.message)
  return <StatusPanel
    title={titleFor(code, backend?.phase ?? 'failed')}
    description={details}
    busy={busy}
    actions={<>
      {platform ? <button type="button" disabled={busy} onClick={() => setConfirmRetry(true)} className={buttonClass}>Retry backend</button> : null}
      {platform ? <button type="button" disabled={busy} onClick={() => void quit()} className={buttonClass}>Quit APEX</button> : null}
      {!platform ? <button type="button" disabled={busy} onClick={() => window.location.reload()} className={buttonClass}>Reload APEX</button> : null}
    </>}
    confirmation={confirmRetry ? <div className="mt-5 rounded-lg border border-amber-400/30 bg-amber-400/5 p-4">
      <p className="text-sm text-amber-100">Restarting the backend will close the current workspace and discard unsent text. APEX does not save drafts.</p>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={() => setConfirmRetry(false)} className={buttonClass}>Cancel</button>
        <button type="button" disabled={busy} onClick={() => void retry()} className={buttonClass}>Restart backend</button>
      </div>
    </div> : null}
  />
}

const buttonClass = 'rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400 disabled:cursor-wait disabled:opacity-60'

function StatusPanel({ title, description, busy = false, actions, confirmation }: {
  title: string
  description: string
  busy?: boolean
  actions?: ReactElement
  confirmation?: ReactElement | null
}): ReactElement {
  return <main className="flex h-dvh w-full items-center justify-center overflow-auto bg-black px-5 py-8 text-slate-200">
    <section className="w-full max-w-xl rounded-2xl border border-white/10 bg-white/[0.04] p-6 shadow-2xl sm:p-8" aria-labelledby="desktop-status-title">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-300">APEX Desktop</p>
      <h1 id="desktop-status-title" className="mt-3 text-xl font-semibold text-white">{title}</h1>
      <p className="mt-3 text-sm leading-relaxed text-zinc-300" role={busy ? 'status' : 'alert'} aria-live={busy ? 'polite' : 'assertive'}>{description}</p>
      {busy ? <div className="mt-5 h-1 overflow-hidden rounded bg-white/10 motion-safe:animate-pulse" aria-hidden="true"><div className="h-full w-1/3 rounded bg-amber-300" /></div> : null}
      {actions ? <div className="mt-6 flex flex-wrap gap-2">{actions}</div> : null}
      {confirmation}
    </section>
  </main>
}

function titleFor(code: string | null, phase: DesktopBackendState['phase']): string {
  if (code === null) return 'Checking the APEX backend'
  if (code === 'port_in_use') return 'Another service is using the APEX port'
  if (code === 'profile_in_use') return 'APEX data is already in use'
  if (code === 'backend_crashed' || code === 'child_failed') return 'The APEX backend stopped unexpectedly'
  if (code === 'cors_rejected') return 'The desktop connection was rejected'
  if (code === 'identity_mismatch') return 'APEX could not verify its backend'
  if (code === 'resource_missing') return 'The desktop backend is unavailable'
  if (code === 'protocol_error') return 'The desktop backend status could not be read'
  if (phase === 'failed') return 'APEX could not start'
  return 'APEX needs attention'
}

function messageFor(code: string, message: string | null): string {
  if (message) return message
  const messages: Record<string, string> = {
    port_in_use: 'The local APEX port is occupied by another process. Close that service, then retry.',
    profile_in_use: 'Another APEX process owns this data profile. Close it before retrying.',
    startup_timeout: 'The local runtime identity check timed out. Confirm the backend has completed startup, then retry.',
    resource_missing: 'A required desktop resource could not be loaded. Retry or quit APEX.',
    identity_mismatch: 'The local API did not identify the backend started for this window. Check for another APEX process, then retry.',
    cors_rejected: 'The local API rejected this desktop origin. Check the desktop CORS configuration, then retry.',
    backend_crashed: 'The backend process ended. Retry starts a fresh backend generation.',
    child_failed: 'The backend process ended during startup. Retry starts it again.',
    shutdown_timeout: 'The backend did not finish shutting down in time. Retry or quit APEX.',
    shutdown_failed: 'APEX could not request a clean shutdown. Retry or quit the window.',
    protocol_error: 'The desktop and backend could not complete their private startup handshake.',
    startup_failed: 'The backend could not start or could not be reached. Retry to try again.',
    internal_error: 'The desktop backend reported an internal startup error. Retry or quit APEX.',
  }
  return messages[code] ?? 'The backend is unavailable. Retry to start it again or quit APEX.'
}

function isBackendState(value: unknown): value is DesktopBackendState {
  if (!value || typeof value !== 'object') return false
  const state = value as Partial<DesktopBackendState>
  return Number.isSafeInteger(state.revision) && Number.isSafeInteger(state.generation) &&
    ['starting', 'ready', 'failed', 'stopping', 'stopped'].includes(state.phase ?? '') &&
    (state.error_code === null || typeof state.error_code === 'string') &&
    (state.runtime === null || isRuntimeIdentity(state.runtime))
}

function isRuntimeIdentity(value: unknown): value is RuntimeIdentity {
  if (!value || typeof value !== 'object') return false
  const runtime = value as Partial<RuntimeIdentity>
  const expectedKeys = ['app_id', 'app_version', 'build_id', 'instance_id', 'pid', 'hosting_mode', 'launch_id', 'data_root_fingerprint', 'shutdown_timeout_seconds']
  return Object.keys(value).length === expectedKeys.length && expectedKeys.every((key) => key in value) &&
    runtime.app_id === 'apex' && typeof runtime.app_version === 'string' && typeof runtime.build_id === 'string' &&
    typeof runtime.instance_id === 'string' && Number.isSafeInteger(runtime.pid) && runtime.pid! > 0 &&
    (runtime.hosting_mode === 'managed' || runtime.hosting_mode === 'standalone') &&
    (runtime.launch_id === null || typeof runtime.launch_id === 'string') &&
    typeof runtime.data_root_fingerprint === 'string' && Number.isSafeInteger(runtime.shutdown_timeout_seconds)
}

function sameRuntimeIdentity(left: RuntimeIdentity, right: RuntimeIdentity): boolean {
  return left.app_id === right.app_id && left.app_version === right.app_version && left.build_id === right.build_id &&
    left.instance_id === right.instance_id && left.pid === right.pid && left.hosting_mode === right.hosting_mode &&
    left.launch_id === right.launch_id && left.data_root_fingerprint === right.data_root_fingerprint &&
    left.shutdown_timeout_seconds === right.shutdown_timeout_seconds
}
