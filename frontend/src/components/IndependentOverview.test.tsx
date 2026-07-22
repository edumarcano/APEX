import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CloudSun } from 'lucide-react'

import { StandbyActions } from './StandbyActions'
import { PreflightDialog } from './PreflightDialog'
import { BriefingDigest } from './BriefingDigest'
import { TelemetryCard } from './TelemetryCard'

describe('StandbyActions', () => {
  it('exposes both activation actions', async () => {
    const onStartApex = vi.fn()
    const onStartWithBriefing = vi.fn()
    const user = userEvent.setup()
    render(
      <StandbyActions
        onStartApex={onStartApex}
        onStartWithBriefing={onStartWithBriefing}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Start APEX' }))
    await user.click(screen.getByRole('button', { name: 'Start APEX with briefing' }))
    expect(onStartApex).toHaveBeenCalledTimes(1)
    expect(onStartWithBriefing).toHaveBeenCalledTimes(1)
  })
})

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

  it('renders independent refresh controls for a grouped card', async () => {
    const refreshCalendar = vi.fn()
    const refreshF1 = vi.fn()
    const refreshFootball = vi.fn()
    const user = userEvent.setup()
    render(
      <TelemetryCard
        title="Events"
        icon={CloudSun}
        refreshActions={[
          { label: 'Calendar', onRefresh: refreshCalendar },
          { label: 'F1', onRefresh: refreshF1 },
          { label: 'Football', onRefresh: refreshFootball },
        ]}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Refresh Calendar' }))
    await user.click(screen.getByRole('button', { name: 'Refresh F1' }))
    await user.click(screen.getByRole('button', { name: 'Refresh Football' }))
    expect(refreshCalendar).toHaveBeenCalledTimes(1)
    expect(refreshF1).toHaveBeenCalledTimes(1)
    expect(refreshFootball).toHaveBeenCalledTimes(1)
  })
})

describe('BriefingDigest empty generate action', () => {
  it('shows Generate Briefing when activated with empty insights', async () => {
    const onGenerate = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingDigest
        insights={[]}
        briefingText=""
        status="idle"
        isLoading={false}
        activated
        onGenerateBriefing={onGenerate}
      />,
    )

    await user.click(screen.getByRole('button', { name: /generate briefing/i }))
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })
})
