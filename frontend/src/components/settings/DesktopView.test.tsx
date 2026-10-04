import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

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
    render(<DesktopView titleId="title" draft={BASE_SETTINGS} setDraft={setDraft} />)
    expect(screen.getByRole('switch', { name: 'Launch APEX at sign-in' })).toBeDisabled()
    expect(screen.getByRole('switch', { name: 'Completion notifications' })).toBeDisabled()
    expect(screen.getByText(/operating system effects are available in the desktop app/i)).toBeVisible()
    expect(platform.getDesktopServicesStatus).not.toHaveBeenCalled()
  })

  it('loads native status and retries desktop reconciliation', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.getDesktopServicesStatus.mockResolvedValue(status)
    platform.retryDesktopServices.mockResolvedValue({ ...status, revision: 5, startup: { actual_enabled: true, error_code: null } })
    render(<DesktopView titleId="title" draft={BASE_SETTINGS} setDraft={vi.fn()} />)
    expect(await screen.findByText('Loaded by desktop')).toBeVisible()
    expect(screen.getByText('Disabled')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Retry desktop services' }))
    await waitFor(() => expect(platform.retryDesktopServices).toHaveBeenCalledOnce())
    expect(await screen.findByText('Enabled')).toBeVisible()
  })
})
