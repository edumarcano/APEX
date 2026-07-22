import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { CloudSun } from 'lucide-react'

import { StandbyActions } from './StandbyActions'
import { PreflightDialog } from './PreflightDialog'
import { BriefingDigest } from './BriefingDigest'
import { TelemetryCard } from './TelemetryCard'
import { ApexLogo } from './ApexLogo'

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

describe('ApexLogo telemetry collection state', () => {
  it('surges the core and sequences all blue segments while collecting', () => {
    const { container, rerender } = render(
      <ApexLogo step={null} status="success" isTelemetryCollecting />,
    )

    expect(container.querySelector('.apex-core-metal--green-surge')).toBeTruthy()
    expect(container.querySelectorAll('.apex-blue-metal--collection-surge')).toHaveLength(7)

    rerender(<ApexLogo step={null} status="success" />)
    expect(container.querySelector('.apex-core-metal--green-surge')).toBeNull()
    expect(container.querySelectorAll('.apex-blue-metal--collection-surge')).toHaveLength(0)
    expect(container.querySelectorAll('.apex-blue-metal--active')).toHaveLength(7)
  })
})

describe('BriefingDigest empty generate action', () => {
  it('shows Generate Briefing when activated with empty insights', async () => {
    const onGenerate = vi.fn()
    const onModeChange = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingDigest
        insights={[]}
        briefingText=""
        status="idle"
        isLoading={false}
        activated
        briefingMode="comet"
        onBriefingModeChange={onModeChange}
        onGenerateBriefing={onGenerate}
      />,
    )

    expect(screen.getByLabelText(/briefing mode/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /generate briefing/i }))
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })

  it('disables generate when generateDisabled is set', () => {
    render(
      <BriefingDigest
        insights={[]}
        briefingText=""
        status="idle"
        isLoading={false}
        activated
        briefingMode="acinonyx"
        onBriefingModeChange={() => undefined}
        onGenerateBriefing={() => undefined}
        generateDisabled
      />,
    )

    expect(screen.getByRole('button', { name: /generate briefing/i })).toBeDisabled()
  })

  it('disables replay and exposes voice delivery failures', () => {
    render(
      <BriefingDigest
        insights={['Ready']}
        briefingText="Current briefing."
        status="success"
        isLoading={false}
        activated
        briefingMode="comet"
        onBriefingModeChange={() => undefined}
        onGenerateBriefing={() => undefined}
        onSpeakBriefing={() => undefined}
        showSpeakAction
        speakDisabled
        speechError="Speech delivery failed."
      />,
    )

    expect(screen.getByRole('button', { name: /speak \/ replay/i })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Speech delivery failed.')
  })
})
