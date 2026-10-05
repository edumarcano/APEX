import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DesktopView from './DesktopView'
import { BASE_SETTINGS } from '../../test/settingsFixtures'
import type { DesktopServicesStatus } from '../../platform/contracts'

const platform = vi.hoisted(() => ({
  isNativeDesktop: vi.fn(() => false),
  getDesktopServicesStatus: vi.fn<() => Promise<DesktopServicesStatus | null>>().mockResolvedValue(null),
  retryDesktopServices: vi.fn<() => Promise<DesktopServicesStatus | null>>().mockResolvedValue(null),
  subscribeDesktopServicesState: vi.fn<() => Promise<() => void>>().mockResolvedValue(() => undefined),
  checkDesktopLocationPermission: vi.fn<() => Promise<{ permission: 'unknown' | 'granted' | 'denied' | 'revoked' | 'unsupported'; availability: 'unknown' | 'available' | 'unavailable' | 'timed_out' | 'unsupported' } | null>>().mockResolvedValue(null),
  subscribeDesktopDeviceState: vi.fn<(onWakeup: () => void) => Promise<() => void>>().mockResolvedValue(() => undefined),
}))

vi.mock('../../platform/services', () => platform)

beforeEach(() => {
  platform.isNativeDesktop.mockReset().mockReturnValue(false)
  platform.getDesktopServicesStatus.mockReset().mockResolvedValue(null)
  platform.retryDesktopServices.mockReset().mockResolvedValue(null)
  platform.subscribeDesktopServicesState.mockReset().mockResolvedValue(() => undefined)
  platform.checkDesktopLocationPermission.mockReset().mockResolvedValue(null)
  platform.subscribeDesktopDeviceState.mockReset().mockResolvedValue(() => undefined)
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const status: DesktopServicesStatus = {
  revision: 4,
  generation: 2,
  preferences_ready: true,
  requested: { launch_on_startup: false, completion_notifications: false },
  tray_available: true,
  startup: { actual_enabled: false, error_code: null },
  notifications: { os_setting: 'enabled', error_code: null },
}

describe('DesktopView', () => {
  it('shows saved desktop controls as disabled in a browser', () => {
    platform.isNativeDesktop.mockReturnValue(false)
    const setDraft = vi.fn()
    render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={BASE_SETTINGS} setDraft={setDraft} />)
    expect(screen.getByRole('switch', { name: 'Launch APEX at sign-in' })).toBeDisabled()
    expect(screen.getByRole('switch', { name: 'Completion notifications' })).toBeDisabled()
    expect(screen.getByText(/operating system effects are available in the desktop app/i)).toBeVisible()
    expect(platform.getDesktopServicesStatus).not.toHaveBeenCalled()
    expect(screen.getByRole('switch', { name: 'Use device location for Weather' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Check location permission' })).not.toBeInTheDocument()
    expect(platform.checkDesktopLocationPermission).not.toHaveBeenCalled()
  })

  it('loads native status and retries desktop reconciliation', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.getDesktopServicesStatus.mockResolvedValue(status)
    platform.retryDesktopServices.mockResolvedValue({ ...status, revision: 5, startup: { actual_enabled: true, error_code: null } })
    render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={BASE_SETTINGS} setDraft={vi.fn()} />)
    expect(await screen.findByText('Loaded by desktop')).toBeVisible()
    expect(within(screen.getByText('Startup registration').parentElement as HTMLElement).getByText('Disabled')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Retry desktop services' }))
    await waitFor(() => expect(platform.retryDesktopServices).toHaveBeenCalledOnce())
    expect(await screen.findByText('Enabled; requested disabled')).toBeVisible()
  })

  it('separates unsaved draft changes from saved preferences waiting for native application', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.getDesktopServicesStatus.mockResolvedValue({ ...status, preferences_ready: true })
    const dirtyDraft = { ...BASE_SETTINGS, desktop: { ...BASE_SETTINGS.desktop, launch_on_startup: true } }
    const { rerender } = render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={dirtyDraft} setDraft={vi.fn()} />)
    expect(await screen.findByText('Unsaved desktop changes. Save changes before retrying.')).toBeVisible()
    expect(screen.queryByText('Saved preferences are waiting for desktop services to load.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry desktop services' })).toBeDisabled()

    const savedDraft = { ...BASE_SETTINGS, desktop: { ...BASE_SETTINGS.desktop, launch_on_startup: true } }
    rerender(<DesktopView titleId="title" baseline={savedDraft} draft={savedDraft} setDraft={vi.fn()} />)
    expect(await screen.findByText('Saved preferences are waiting for desktop services to load.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Retry desktop services' })).toBeEnabled()
  })

  it('ignores an older status request that resolves after a newer retry', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    let resolveOld!: (value: DesktopServicesStatus) => void
    platform.getDesktopServicesStatus.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve }))
    platform.retryDesktopServices.mockResolvedValue({
      ...status,
      revision: 8,
      startup: { actual_enabled: true, error_code: null },
    })
    render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={BASE_SETTINGS} setDraft={vi.fn()} />)
    await waitFor(() => expect(platform.getDesktopServicesStatus).toHaveBeenCalledOnce())
    fireEvent.click(screen.getByRole('button', { name: 'Retry desktop services' }))
    expect(await screen.findByText('Enabled; requested disabled')).toBeVisible()
    resolveOld({ ...status, revision: 7, startup: { actual_enabled: false, error_code: null } })
    await waitFor(() => expect(screen.getByText('Enabled; requested disabled')).toBeVisible())
  })

  it('keeps a newer retry error when an older status request later succeeds', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    const deviceStatus = { enabled: true, permission: 'unknown', availability: 'unknown', source: 'none', freshness: 'none', fix_age_seconds: null }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(deviceStatus), { status: 200 }))
    let resolveOld!: (value: DesktopServicesStatus) => void
    platform.getDesktopServicesStatus.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve }))
    platform.retryDesktopServices.mockRejectedValueOnce(new Error('native detail'))
    render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={BASE_SETTINGS} setDraft={vi.fn()} />)
    await waitFor(() => expect(platform.getDesktopServicesStatus).toHaveBeenCalledOnce())
    fireEvent.click(screen.getByRole('button', { name: 'Retry desktop services' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Desktop services could not be retried.')
    resolveOld({ ...status, revision: 12, startup: { actual_enabled: true, error_code: null } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Desktop services could not be retried.')
    expect(screen.queryByText('Enabled; requested disabled')).not.toBeInTheDocument()
  })

  it('does not apply a newer response carrying an older native revision', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.getDesktopServicesStatus
      .mockResolvedValueOnce({ ...status, revision: 8, startup: { actual_enabled: false, error_code: null } })
      .mockResolvedValueOnce({ ...status, revision: 7, startup: { actual_enabled: false, error_code: null } })
    platform.retryDesktopServices.mockResolvedValue({
      ...status,
      revision: 9,
      startup: { actual_enabled: true, error_code: null },
    })
    render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={BASE_SETTINGS} setDraft={vi.fn()} />)
    await waitFor(() => expect(within(screen.getByText('Startup registration').parentElement as HTMLElement).getByText('Disabled')).toBeVisible())
    fireEvent.click(screen.getByRole('button', { name: 'Retry desktop services' }))
    expect(await screen.findByText('Enabled; requested disabled')).toBeVisible()
    fireEvent(window, new Event('desktop-preferences-saved'))
    await waitFor(() => expect(platform.getDesktopServicesStatus).toHaveBeenCalledTimes(2))
    expect(screen.getByText('Enabled; requested disabled')).toBeVisible()
  })

  it('requires saving the location preference before enabling the explicit permission action', () => {
    platform.isNativeDesktop.mockReturnValue(true)
    const dirtyDraft = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    render(<DesktopView titleId="title" baseline={BASE_SETTINGS} draft={dirtyDraft} setDraft={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Check location permission' })).toBeDisabled()
    expect(screen.getByText('Save the location preference before checking permission.')).toBeVisible()
    expect(platform.checkDesktopLocationPermission).not.toHaveBeenCalled()
  })

  it('does not offer a permission check in demo mode', () => {
    platform.isNativeDesktop.mockReturnValue(true)
    const enabled = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    render(<DesktopView titleId="title" baseline={enabled} draft={enabled} setDraft={vi.fn()} demoMode />)
    expect(screen.getByText('Location checks are unavailable in demo mode.')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Check location permission' })).not.toBeInTheDocument()
    expect(platform.checkDesktopLocationPermission).not.toHaveBeenCalled()
    expect(platform.subscribeDesktopDeviceState).not.toHaveBeenCalled()
  })

  it('calls the native permission action once on click and waits for backend status', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.checkDesktopLocationPermission.mockResolvedValue({ permission: 'granted', availability: 'available' })
    const enabled = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    const unknown = { enabled: true, permission: 'unknown', availability: 'unknown', source: 'none', freshness: 'none', fix_age_seconds: null }
    const granted = { ...unknown, permission: 'granted', availability: 'available', source: 'device', freshness: 'fresh', fix_age_seconds: 2 }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(unknown), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(unknown), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(granted), { status: 200 }))
    render(<DesktopView titleId="title" baseline={enabled} draft={enabled} setDraft={vi.fn()} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    expect(platform.checkDesktopLocationPermission).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Check location permission' }))
    expect(platform.checkDesktopLocationPermission).toHaveBeenCalledOnce()
    expect(await screen.findByText('Windows permission status updated.')).toBeVisible()
    expect(screen.getByText('granted')).toBeVisible()
    expect(screen.getByText('device')).toBeVisible()
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('reports a denied permission and timeout from status without treating it as success', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.checkDesktopLocationPermission.mockResolvedValue({ permission: 'denied', availability: 'timed_out' })
    const enabled = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    const denied = { enabled: true, permission: 'denied', availability: 'timed_out', source: 'none', freshness: 'none', fix_age_seconds: null }
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(denied), { status: 200 }))
    render(<DesktopView titleId="title" baseline={enabled} draft={enabled} setDraft={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Check location permission' }))
    expect(await screen.findByText('denied')).toBeVisible()
    expect(screen.getByText('timed_out')).toBeVisible()
    expect(await screen.findByText('Windows permission status updated.')).toBeVisible()
    expect(platform.checkDesktopLocationPermission).toHaveBeenCalledOnce()
  })

  it('refreshes the coordinate-free status after passive device-state wakeups', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    const enabled = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    const granted = { enabled: true, permission: 'granted', availability: 'available', source: 'device', freshness: 'fresh', fix_age_seconds: 3 }
    const revoked = { ...granted, permission: 'revoked', availability: 'unavailable', source: 'configured', freshness: 'none', fix_age_seconds: null }
    let wakeup: (() => void) | null = null
    platform.subscribeDesktopDeviceState.mockImplementation(async (onWakeup) => {
      wakeup = onWakeup
      return () => undefined
    })
    let request = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(request++ === 0 ? granted : revoked), { status: 200 }))
    render(<DesktopView titleId="title" baseline={enabled} draft={enabled} setDraft={vi.fn()} />)
    expect(await screen.findByText('granted')).toBeVisible()
    act(() => wakeup?.())
    expect(await screen.findByText('revoked')).toBeVisible()
    expect(screen.getByText('configured')).toBeVisible()
  })

  it('refreshes status when a saved location preference is disabled', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    const enabled = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    const disabled = { ...BASE_SETTINGS, device_context: { location_enabled: false } }
    const granted = { enabled: true, permission: 'granted', availability: 'available', source: 'device', freshness: 'fresh', fix_age_seconds: 3 }
    const unknown = { enabled: false, permission: 'unknown', availability: 'unknown', source: 'none', freshness: 'none', fix_age_seconds: null }
    let request = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(request++ === 0 ? granted : unknown), { status: 200 }))
    const { rerender } = render(<DesktopView titleId="title" baseline={enabled} draft={enabled} setDraft={vi.fn()} />)
    expect(await screen.findByText('granted')).toBeVisible()
    rerender(<DesktopView titleId="title" baseline={disabled} draft={disabled} setDraft={vi.fn()} />)
    expect(await screen.findAllByText('unknown')).toHaveLength(2)
    expect(screen.getByText('none')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Check location permission' })).toBeDisabled()
  })

  it('cancels pending location retries when the view unmounts', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.checkDesktopLocationPermission.mockResolvedValue({ permission: 'granted', availability: 'available' })
    const enabled = { ...BASE_SETTINGS, device_context: { location_enabled: true } }
    const unknown = { enabled: true, permission: 'unknown', availability: 'unknown', source: 'none', freshness: 'none', fix_age_seconds: null }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(unknown), { status: 200 }))
    const { unmount } = render(<DesktopView titleId="title" baseline={enabled} draft={enabled} setDraft={vi.fn()} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    vi.useFakeTimers()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Check location permission' }))
      for (let index = 0; index < 12; index += 1) await Promise.resolve()
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    unmount()
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(fetchMock).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })
})
