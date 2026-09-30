import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CloudSun } from 'lucide-react'

import { TelemetryCard } from './TelemetryCard'

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
