import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CloudSun } from 'lucide-react'

import { PreflightDialog } from './PreflightDialog'
import { TelemetryCard } from './TelemetryCard'

describe('PreflightDialog', () => {
  it('offers continue once, continue for session, and cancel for warnings', async () => {
    const onChoice = vi.fn()
    const user = userEvent.setup()
    render(
      <PreflightDialog
        open
        operation="activate"
        warnings={[{ code: 'running_on_battery', message: 'Running on battery' }]}
        blockers={[]}
        isChecking={false}
        error={null}
        onChoice={onChoice}
      />,
    )

    expect(screen.getByRole('dialog')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /continue once/i }))
    expect(onChoice).toHaveBeenCalledWith('continue_once')
  })

  it('blocks with close only when blockers present', async () => {
    const onChoice = vi.fn()
    const user = userEvent.setup()
    render(
      <PreflightDialog
        open
        operation="activate"
        warnings={[]}
        blockers={[{ code: 'missing_credentials', message: 'Missing credentials' }]}
        isChecking={false}
        error={null}
        onChoice={onChoice}
      />,
    )

    expect(screen.queryByRole('button', { name: /continue once/i })).toBeNull()
    await user.click(screen.getByRole('button', { name: /^close$/i }))
    expect(onChoice).toHaveBeenCalledWith('cancel')
  })

  it('traps keyboard focus inside the dialog and restores it after close', async () => {
    const onChoice = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(
      <>
        <button type="button">Open preflight</button>
        <PreflightDialog
          open={false}
          operation={null}
          warnings={[]}
          blockers={[]}
          isChecking={false}
          error={null}
          onChoice={onChoice}
        />
      </>,
    )
    const trigger = screen.getByRole('button', { name: 'Open preflight' })
    trigger.focus()

    rerender(
      <>
        <button type="button">Open preflight</button>
        <PreflightDialog
          open
          operation="activate"
          warnings={[{ code: 'running_on_battery', message: 'Running on battery' }]}
          blockers={[]}
          isChecking={false}
          error={null}
          onChoice={onChoice}
        />
      </>,
    )

    expect(screen.getByRole('button', { name: 'Close preflight dialog' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: /continue for this session/i })).toHaveFocus()

    rerender(
      <>
        <button type="button">Open preflight</button>
        <PreflightDialog
          open={false}
          operation={null}
          warnings={[]}
          blockers={[]}
          isChecking={false}
          error={null}
          onChoice={onChoice}
        />
      </>,
    )
    expect(screen.getByRole('button', { name: 'Open preflight' })).toHaveFocus()
  })
})

describe('TelemetryCard refresh and module state', () => {
  it('keeps refresh available in compact cards', async () => {
    const onRefresh = vi.fn()
    const user = userEvent.setup()
    render(
      <TelemetryCard
        title="Weather"
        icon={CloudSun}
        isCompact
        compactValue="72°"
        onRefresh={onRefresh}
        statusMessage="Stale — connector timeout"
      />,
    )

    expect(screen.getByText('Stale — connector timeout')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Refresh Weather' }))
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it.each([false, true])('selects grouped refresh actions from one menu (compact: %s)', async (isCompact) => {
    const refreshCalendar = vi.fn()
    const refreshF1 = vi.fn()
    const refreshFootball = vi.fn()
    const user = userEvent.setup()
    render(
      <TelemetryCard
        title="Events"
        icon={CloudSun}
        isCompact={isCompact}
        compactValue={isCompact ? '3 events' : undefined}
        refreshActions={[
          { label: 'Calendar', onRefresh: refreshCalendar },
          { label: 'F1', onRefresh: refreshF1 },
          { label: 'Football', onRefresh: refreshFootball },
        ]}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Choose Events module to refresh' })
    expect(screen.queryByRole('button', { name: 'Refresh Calendar' })).toBeNull()

    await user.click(trigger)
    await user.click(screen.getByRole('menuitem', { name: 'Calendar' }))
    expect(refreshCalendar).toHaveBeenCalledTimes(1)
    expect(refreshF1).not.toHaveBeenCalled()
    expect(refreshFootball).not.toHaveBeenCalled()
    expect(screen.queryByRole('menu')).toBeNull()
    expect(trigger).toHaveFocus()
  })

  it('supports keyboard navigation and dismisses the grouped refresh menu', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <TelemetryCard
          title="Events"
          icon={CloudSun}
          refreshActions={[
            { label: 'Calendar', onRefresh: vi.fn() },
            { label: 'F1', onRefresh: vi.fn(), disabled: true },
            { label: 'Football', onRefresh: vi.fn() },
          ]}
        />
        <button type="button">Outside</button>
      </div>,
    )

    const trigger = screen.getByRole('button', { name: 'Choose Events module to refresh' })
    await user.click(trigger)
    expect(screen.getByRole('menuitem', { name: 'Calendar' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Football' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    await user.click(screen.getByRole('button', { name: 'Outside' }))
    expect(screen.queryByRole('menu')).toBeNull()
  })
})
