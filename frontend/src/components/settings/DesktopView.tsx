import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import { SettingsCard, SettingsToggle, StatusRow } from '../SettingsControls'
import { getDesktopServicesStatus, isNativeDesktop, retryDesktopServices, subscribeDesktopServicesState } from '../../platform/services'
import type { DesktopServicesStatus } from '../../platform/contracts'
import type { RuntimeSettings } from '../../types/settings'

export default function DesktopView({
  titleId,
  baseline,
  draft,
  setDraft,
}: {
  titleId: string
  baseline: RuntimeSettings | null
  draft: RuntimeSettings
  setDraft: (updater: (previous: RuntimeSettings) => RuntimeSettings) => void
}): ReactElement {
  const native = isNativeDesktop()
  const [status, setStatus] = useState<DesktopServicesStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const requestSequence = useRef(0)
  const mounted = useRef(false)
  const statusRef = useRef<DesktopServicesStatus | null>(null)

  const applyStatus = (next: DesktopServicesStatus | null) => {
    if (!next || !mounted.current) return
    const current = statusRef.current
    if (current && (next.generation < current.generation || (next.generation === current.generation && next.revision < current.revision))) return
    statusRef.current = next
    setStatus(next)
    setError(null)
  }

  const refresh = useCallback(async () => {
    if (!native) return
    const requestId = ++requestSequence.current
    try {
      const next = await getDesktopServicesStatus()
      if (mounted.current && requestId === requestSequence.current) applyStatus(next)
    } catch {
      if (mounted.current && requestId === requestSequence.current) setError('Desktop service status could not be loaded. Try again.')
    }
  }, [native])

  useEffect(() => {
    let active = true
    let unlisten: (() => void) | undefined
    mounted.current = true
    void Promise.resolve().then(refresh)
    const onSaved = () => { if (active) void refresh() }
    window.addEventListener('desktop-preferences-saved', onSaved)
    void subscribeDesktopServicesState(() => { if (active) void refresh() })
      .then((stop) => { if (active) unlisten = stop; else stop() })
      .catch(() => undefined)
    return () => { active = false; mounted.current = false; requestSequence.current += 1; unlisten?.(); window.removeEventListener('desktop-preferences-saved', onSaved) }
  }, [refresh])

  const retry = async () => {
    const requestId = ++requestSequence.current
    setRetrying(true)
    try {
      const next = await retryDesktopServices()
      if (mounted.current && requestId === requestSequence.current) applyStatus(next)
    } catch {
      if (mounted.current && requestId === requestSequence.current) setError('Desktop services could not be retried. Try again.')
    } finally {
      if (mounted.current) setRetrying(false)
    }
  }

  const updatePreference = (key: 'launch_on_startup' | 'completion_notifications', value: boolean) => {
    setDraft((previous) => ({ ...previous, desktop: { ...previous.desktop, [key]: value } }))
  }
  const saved = baseline?.desktop ?? draft.desktop
  const unsaved = Boolean(baseline && (
    baseline.desktop.launch_on_startup !== draft.desktop.launch_on_startup ||
    baseline.desktop.completion_notifications !== draft.desktop.completion_notifications
  ))
  const savedPreferencesPending = Boolean(status && (
    !status.preferences_ready ||
    status.requested.launch_on_startup !== saved.launch_on_startup ||
    status.requested.completion_notifications !== saved.completion_notifications
  ))
  const startupMatches = status?.startup.actual_enabled === saved.launch_on_startup

  return <div className="grid grid-cols-1 gap-4">
    <SettingsCard id={`${titleId}-desktop-services`} title="Desktop services" badgeText="Windows desktop">
      <div className="space-y-3">
        {!native ? <p className="text-xs text-zinc-400">These preferences are saved with Runtime Settings. Their operating system effects are available in the desktop app.</p> : null}
        <SettingsToggle id="settings-desktop-startup" label="Launch APEX at sign-in" checked={draft.desktop.launch_on_startup} onChange={(value) => updatePreference('launch_on_startup', value)} timing="Active" disabled={!native} />
        <p className="-mt-2 text-[11px] text-zinc-500">APEX starts hidden in the system tray. Save the preference before retrying desktop services.</p>
        <SettingsToggle id="settings-desktop-notifications" label="Completion notifications" checked={draft.desktop.completion_notifications} onChange={(value) => updatePreference('completion_notifications', value)} timing="Active" disabled={!native} />
        <p className="-mt-2 text-[11px] text-zinc-500">Notify only after a successful completion while APEX is hidden or minimized.</p>
        {native ? <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
          <StatusRow label="Desktop preference delivery" value={status ? (status.preferences_ready ? 'Loaded by desktop' : 'Waiting for desktop') : 'Checking…'} tone={status?.preferences_ready ? 'ok' : 'warn'} />
          <StatusRow label="Saved startup preference" value={saved.launch_on_startup ? 'Enabled' : 'Disabled'} />
          <StatusRow label="Startup registration" value={status ? startupState(status.startup.actual_enabled, saved.launch_on_startup, status.startup.error_code) : 'Checking…'} tone={status?.startup.error_code || (status && !startupMatches) ? 'error' : 'neutral'} />
          <StatusRow label="Saved notification preference" value={saved.completion_notifications ? 'Enabled' : 'Disabled'} />
          <StatusRow label="System tray" value={status ? (status.tray_available ? 'Available' : 'Unavailable') : 'Checking…'} tone={status?.tray_available ? 'ok' : 'warn'} />
          <StatusRow label="Windows notifications" value={status ? notificationState(status.notifications.os_setting) : 'Checking…'} tone={status?.notifications.os_setting === 'enabled' ? 'ok' : 'warn'} />
          {status?.startup.error_code || status?.notifications.error_code ? <p className="py-2 text-xs text-amber-200" role="status">A desktop service needs attention. Retry desktop services to apply the saved preferences.</p> : null}
          {unsaved ? <p className="py-2 text-xs text-amber-200" role="status">Unsaved desktop changes. Save changes before retrying.</p> : null}
          {!unsaved && savedPreferencesPending ? <p className="py-2 text-xs text-amber-200" role="status">Saved preferences are waiting for desktop services to load.</p> : null}
          {error ? <p className="py-2 text-xs text-red-200" role="alert">{error}</p> : null}
          <button type="button" onClick={() => void retry()} disabled={retrying || unsaved} className="my-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50">{retrying ? 'Retrying…' : 'Retry desktop services'}</button>
        </div> : null}
      </div>
    </SettingsCard>
  </div>
}

function startupState(actual: boolean | null, requested: boolean, errorCode: string | null): string {
  const actualLabel = actual === null ? 'Unavailable' : actual ? 'Enabled' : 'Disabled'
  const requestedLabel = requested ? 'enabled' : 'disabled'
  if (errorCode || actual !== requested) return `${actualLabel}; requested ${requestedLabel}`
  return actualLabel
}

function notificationState(value: DesktopServicesStatus['notifications']['os_setting']): string {
  switch (value) {
    case 'enabled': return 'Allowed'
    case 'disabled_app': return 'Disabled for APEX'
    case 'disabled_user': return 'Disabled in Windows settings'
    case 'disabled_policy': return 'Blocked by system policy'
    case 'disabled_manifest': return 'Unavailable for this app'
    case 'unavailable': return 'Unavailable'
    default: return 'Unknown'
  }
}
