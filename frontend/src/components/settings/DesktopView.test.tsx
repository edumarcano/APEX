import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DesktopView from './DesktopView'
import { BASE_SETTINGS } from '../../test/settingsFixtures'
import type { DesktopServicesStatus } from '../../platform/contracts'

const platform = vi.hoisted(() => ({
  isNativeDesktop: vi.fn(() => false),
  getDesktopServicesStatus: vi.fn<() => Promise<DesktopServicesStatus | null>>().mockResolvedValue(null),
  retryDesktopServices: vi.fn<() => Promise<DesktopServicesStatus | null>>().mockResolvedValue(null),
  subscribeDesktopServicesState: vi.fn<() => Promise<() => void>>().mockResolvedValue(() => undefined),
}))

vi.mock('../../platform/services', () => platform)

beforeEach(() => {
  platform.isNativeDesktop.mockReset().mockReturnValue(false)
  platform.getDesktopServicesStatus.mockReset().mockResolvedValue(null)
  platform.retryDesktopServices.mockReset().mockResolvedValue(null)
  platform.subscribeDesktopServicesState.mockReset().mockResolvedValue(() => undefined)
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
})
