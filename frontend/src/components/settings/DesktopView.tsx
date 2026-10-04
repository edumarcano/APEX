import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import { SettingsCard, SettingsToggle, StatusRow } from '../SettingsControls'
import { checkDesktopLocationPermission, getDesktopServicesStatus, isNativeDesktop, retryDesktopServices, subscribeDesktopDeviceState, subscribeDesktopServicesState } from '../../platform/services'
import type { DesktopLocationCheck, DesktopServicesStatus } from '../../platform/contracts'
import { fetchDeviceContextStatus, locationPermissionErrorMessage, type DeviceContextStatus } from '../../lib/deviceContext'
import type { RuntimeSettings } from '../../types/settings'

export default function DesktopView({
  titleId,
  baseline,
  draft,
  setDraft,
  demoMode = false,
}: {
  titleId: string
  baseline: RuntimeSettings | null
  draft: RuntimeSettings
  setDraft: (updater: (previous: RuntimeSettings) => RuntimeSettings) => void
  demoMode?: boolean
}): ReactElement {
  const native = isNativeDesktop()
  const savedLocationEnabled = baseline?.device_context.location_enabled ?? draft.device_context.location_enabled
  const [status, setStatus] = useState<DesktopServicesStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const requestSequence = useRef(0)
  const mounted = useRef(false)
  const statusRef = useRef<DesktopServicesStatus | null>(null)
  const [deviceStatus, setDeviceStatus] = useState<DeviceContextStatus | null>(null)
  const [deviceError, setDeviceError] = useState<string | null>(null)
  const [checkingLocation, setCheckingLocation] = useState(false)
  const [checkMessage, setCheckMessage] = useState<string | null>(null)
  const [checkResult, setCheckResult] = useState<DesktopLocationCheck | null>(null)
  const deviceRequestSequence = useRef(0)
  const deviceWakeupGeneration = useRef(0)
  const locationCheckRef = useRef(false)
  const actionGeneration = useRef(0)
  const timerSequence = useRef(0)
  const actionTimers = useRef(new Map<number, () => void>())
  const wakeupTimers = useRef(new Map<number, () => void>())
  const statusControllers = useRef(new Set<AbortController>())

  const waitFor = useCallback((delayMs: number, timers = actionTimers.current): Promise<void> => new Promise((resolve) => {
    const id = ++timerSequence.current
    const timer = window.setTimeout(() => {
      timers.delete(id)
      resolve()
    }, delayMs)
    timers.set(id, () => {
      window.clearTimeout(timer)
      timers.delete(id)
      resolve()
    })
  }), [])

  const cancelTimers = useCallback((timers: Map<number, () => void>) => {
    for (const cancel of timers.values()) cancel()
    timers.clear()
  }, [])

  const refreshDeviceStatus = useCallback(async () => {
    if (!native || demoMode) return null
    const requestId = ++deviceRequestSequence.current
    const controller = new AbortController()
    statusControllers.current.add(controller)
    try {
      const next = await fetchDeviceContextStatus(controller.signal)
      if (mounted.current && requestId === deviceRequestSequence.current) {
        setDeviceStatus(next)
        setDeviceError(null)
        return next
      }
      return null
    } catch {
      if (mounted.current && requestId === deviceRequestSequence.current) {
        setDeviceError('Device location status could not be loaded. Try again.')
      }
      return null
    } finally {
      statusControllers.current.delete(controller)
    }
  }, [native, demoMode])

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
    const actionTimersOnMount = actionTimers.current
    const wakeupTimersOnMount = wakeupTimers.current
    const statusControllersOnMount = statusControllers.current
    mounted.current = true
    void Promise.resolve().then(refresh)
    void Promise.resolve().then(() => {
      if (active) void refreshDeviceStatus()
    })
    const onSaved = () => {
      if (active) {
        void refresh()
        void refreshDeviceStatus()
      }
    }
    window.addEventListener('desktop-preferences-saved', onSaved)
    void subscribeDesktopServicesState(() => { if (active) void refresh() })
      .then((stop) => { if (active) unlisten = stop; else stop() })
      .catch(() => undefined)
    let stopDevice: (() => void) | undefined
    if (native && !demoMode) {
      void subscribeDesktopDeviceState(() => {
        if (!active) return
        const generation = ++deviceWakeupGeneration.current
        cancelTimers(wakeupTimers.current)
        void refreshDeviceStatus()
        void (async () => {
          for (const delay of [250, 750]) {
            await waitFor(delay, wakeupTimers.current)
            if (!active || generation !== deviceWakeupGeneration.current) return
            void refreshDeviceStatus()
          }
        })()
      }).then((stop) => { if (active) stopDevice = stop; else stop() }).catch(() => undefined)
    }
    return () => {
      active = false
      mounted.current = false
      actionGeneration.current += 1
      deviceWakeupGeneration.current += 1
      requestSequence.current += 1
      deviceRequestSequence.current += 1
      cancelTimers(actionTimersOnMount)
      cancelTimers(wakeupTimersOnMount)
      for (const controller of statusControllersOnMount) controller.abort()
      statusControllersOnMount.clear()
      unlisten?.()
      stopDevice?.()
      window.removeEventListener('desktop-preferences-saved', onSaved)
    }
  }, [cancelTimers, demoMode, native, refresh, refreshDeviceStatus, savedLocationEnabled, waitFor])

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
  const updateLocationPreference = (value: boolean) => {
    setDraft((previous) => ({ ...previous, device_context: { ...previous.device_context, location_enabled: value } }))
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
  const locationUnsaved = Boolean(baseline && baseline.device_context.location_enabled !== draft.device_context.location_enabled)
  const locationActionDisabled = !native || demoMode || !savedLocationEnabled || locationUnsaved || checkingLocation

  const checkLocation = async () => {
    if (locationActionDisabled || locationCheckRef.current) return
    locationCheckRef.current = true
    const generation = ++actionGeneration.current
    setCheckingLocation(true)
    setDeviceError(null)
    setCheckMessage(null)
    setCheckResult(null)
    try {
      const result = await checkDesktopLocationPermission()
      if (!mounted.current || generation !== actionGeneration.current) return
      if (!result) throw new Error('Location permission checks are available in the desktop app.')
      setCheckResult(result)
      const expected = result
      let latest: DeviceContextStatus | null = null
      for (let attempt = 0; attempt < 4; attempt += 1) {
        latest = await refreshDeviceStatus()
        if (!mounted.current || generation !== actionGeneration.current) return
        if (latest?.permission === expected.permission && latest.availability === expected.availability) break
        if (attempt < 3 && mounted.current) {
          await waitFor(250, actionTimers.current)
        }
        if (!mounted.current || generation !== actionGeneration.current) return
      }
      if (mounted.current) {
        setCheckMessage(latest?.permission === expected.permission && latest.availability === expected.availability
          ? 'Windows permission status updated.'
          : 'Windows returned a result; the device status is still updating.')
      }
    } catch (error) {
      if (mounted.current) setDeviceError(locationPermissionErrorMessage(error))
    } finally {
      locationCheckRef.current = false
      if (mounted.current) setCheckingLocation(false)
    }
  }

  return <div className="grid grid-cols-1 gap-4">
    <SettingsCard id={`${titleId}-desktop-services`} title="Desktop services" badgeText="Windows desktop">
      <div className="space-y-3">
        {!native ? <p className="text-xs text-zinc-400">These preferences are saved with Runtime Settings. Their operating system effects are available in the desktop app.</p> : null}
        <SettingsToggle id="settings-desktop-startup" label="Launch APEX at sign-in" checked={draft.desktop.launch_on_startup} onChange={(value) => updatePreference('launch_on_startup', value)} timing="Active" disabled={!native} />
        <p className="-mt-2 text-[11px] text-zinc-500">APEX starts hidden in the system tray. Save the preference before retrying desktop services.</p>
        <SettingsToggle id="settings-desktop-notifications" label="Completion notifications" checked={draft.desktop.completion_notifications} onChange={(value) => updatePreference('completion_notifications', value)} timing="Active" disabled={!native} />
        <p className="-mt-2 text-[11px] text-zinc-500">Notify only after a successful completion while APEX is hidden or minimized.</p>
        <SettingsToggle id="settings-device-location" label="Use device location for Weather" checked={draft.device_context.location_enabled} onChange={updateLocationPreference} timing="Active" />
        <p className="-mt-2 text-[11px] text-zinc-500">Saves an opt-in preference. APEX checks Windows permission only when you ask it to.</p>
        <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
          {demoMode ? <p className="text-xs text-zinc-400" role="status">Location checks are unavailable in demo mode.</p> : !native ? <p className="text-xs text-zinc-400" role="status">Permission checks are available in the Windows desktop app.</p> : <>
            <StatusRow label="Saved location preference" value={savedLocationEnabled ? 'Enabled' : 'Disabled'} />
            <StatusRow label="Windows permission" value={deviceStatus?.permission ?? 'Unknown'} />
            <StatusRow label="Location availability" value={deviceStatus?.availability ?? 'Unknown'} />
            <StatusRow label="Weather location source" value={deviceStatus?.source ?? 'Unknown'} />
            <StatusRow label="Location fix freshness" value={deviceStatus ? freshnessLabel(deviceStatus) : 'Unknown'} />
            {checkResult ? <StatusRow label="Latest Windows check result" value={`${checkResult.permission} · ${checkResult.availability}`} /> : null}
            {locationUnsaved ? <p className="py-2 text-xs text-amber-200" role="status">Save the location preference before checking permission.</p> : null}
            {deviceError ? <p className="py-2 text-xs text-red-200" role="alert">{deviceError}</p> : null}
            {checkMessage ? <p className="py-2 text-xs text-zinc-300" role="status">{checkMessage}</p> : null}
            <button type="button" onClick={() => void checkLocation()} disabled={locationActionDisabled} className="my-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50">{checkingLocation ? 'Checking permission…' : 'Check location permission'}</button>
          </>}
        </div>
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

function freshnessLabel(status: DeviceContextStatus): string {
  if (status.freshness === 'none') return 'No location fix'
  if (status.freshness === 'expired') return 'Expired'
  if (status.fix_age_seconds === null) return 'Fresh'
  return `Fresh (${Math.round(status.fix_age_seconds)} seconds old)`
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
