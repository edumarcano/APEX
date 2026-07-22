import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { StandbyActions } from './StandbyActions'
import { PreflightDialog } from './PreflightDialog'
import { BriefingDigest } from './BriefingDigest'

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
