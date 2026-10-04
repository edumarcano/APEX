import { useCallback, useEffect, useState, type ReactElement } from 'react'

import { SettingsCard, SettingsToggle, StatusRow } from '../SettingsControls'
import { getDesktopServicesStatus, isNativeDesktop, retryDesktopServices, subscribeDesktopServicesState } from '../../platform/services'
import type { DesktopServicesStatus } from '../../platform/contracts'
import type { RuntimeSettings } from '../../types/settings'

export default function DesktopView({
  titleId,
  draft,
  setDraft,
}: {
  titleId: string
  draft: RuntimeSettings
  setDraft: (updater: (previous: RuntimeSettings) => RuntimeSettings) => void
}): ReactElement {
  const native = isNativeDesktop()
  const [status, setStatus] = useState<DesktopServicesStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)

  const refresh = useCallback(async () => {
    if (!native) return
    try {
      setStatus(await getDesktopServicesStatus())
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Desktop service status is unavailable.')
    }
  }, [native])

  useEffect(() => {
    let active = true
    let unlisten: (() => void) | undefined
    void Promise.resolve().then(refresh)
    const onSaved = () => { if (active) void refresh() }
    window.addEventListener('desktop-preferences-saved', onSaved)
    void subscribeDesktopServicesState(() => { if (active) void refresh() })
      .then((stop) => { if (active) unlisten = stop; else stop() })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : 'Desktop service updates are unavailable.') })
    return () => { active = false; unlisten?.(); window.removeEventListener('desktop-preferences-saved', onSaved) }
  }, [refresh])

  const retry = async () => {
    setRetrying(true)
    try {
      setStatus(await retryDesktopServices())
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Desktop service retry failed.')
    } finally {
      setRetrying(false)
    }
  }

  const updatePreference = (key: 'launch_on_startup' | 'completion_notifications', value: boolean) => {
    setDraft((previous) => ({ ...previous, desktop: { ...previous.desktop, [key]: value } }))
  }
  const pending = Boolean(status && (
    status.requested.launch_on_startup !== draft.desktop.launch_on_startup ||
    status.requested.completion_notifications !== draft.desktop.completion_notifications
  ))

  return <div className="grid grid-cols-1 gap-4">
    <SettingsCard id={`${titleId}-desktop-services`} title="Desktop services" badgeText="Windows desktop">
      <div className="space-y-3">
        {!native ? <p className="text-xs text-zinc-400">These preferences are saved with Runtime Settings. Their operating system effects are available in the desktop app.</p> : null}
        <SettingsToggle id="settings-desktop-startup" label="Launch APEX at sign-in" checked={draft.desktop.launch_on_startup} onChange={(value) => updatePreference('launch_on_startup', value)} timing="Active" disabled={!native} />
        <p className="-mt-2 text-[11px] text-zinc-500">APEX starts hidden in the system tray. Save the preference before retrying desktop services.</p>
        <SettingsToggle id="settings-desktop-notifications" label="Completion notifications" checked={draft.desktop.completion_notifications} onChange={(value) => updatePreference('completion_notifications', value)} timing="Active" disabled={!native} />
        <p className="-mt-2 text-[11px] text-zinc-500">Notify only after a successful completion while APEX is hidden or minimized.</p>
        {native ? <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
          <StatusRow label="Saved preferences" value={status?.preferences_ready ? 'Loaded by desktop' : 'Pending or unavailable'} tone={status?.preferences_ready ? 'ok' : 'warn'} />
          <StatusRow label="Startup registration" value={status ? startupState(status.startup.actual_enabled, status.startup.error_code) : 'Checking…'} tone={status?.startup.error_code ? 'error' : 'neutral'} />
          <StatusRow label="System tray" value={status ? (status.tray_available ? 'Available' : 'Unavailable') : 'Checking…'} tone={status?.tray_available ? 'ok' : 'warn'} />
          <StatusRow label="Notifications" value={status ? `${status.notifications.os_setting}${status.notifications.error_code ? ` · ${status.notifications.error_code}` : ''}` : 'Checking…'} tone={status?.notifications.os_setting === 'enabled' ? 'ok' : 'warn'} />
          {pending ? <p className="py-2 text-xs text-amber-200" role="status">Unsaved desktop preferences. Save changes before retrying.</p> : null}
          {error ? <p className="py-2 text-xs text-red-200" role="alert">{error}</p> : null}
          <button type="button" onClick={() => void retry()} disabled={retrying || pending} className="my-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50">{retrying ? 'Retrying…' : 'Retry desktop services'}</button>
        </div> : null}
      </div>
    </SettingsCard>
  </div>
}

function startupState(enabled: boolean | null, errorCode: string | null): string {
  if (errorCode) return `Error: ${errorCode}`
  if (enabled === null) return 'Unavailable'
  return enabled ? 'Enabled' : 'Disabled'
}
