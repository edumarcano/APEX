import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { StandbyActions } from './StandbyActions'

describe('StandbyActions', () => {
  it('routes the Overview and Briefing actions to their own handlers', async () => {
    const onStartOverview = vi.fn()
    const onStartBriefing = vi.fn()
    const user = userEvent.setup()

    render(<StandbyActions onStartOverview={onStartOverview} onStartBriefing={onStartBriefing} />)

    await user.click(screen.getByRole('button', { name: 'Start Overview' }))
    expect(onStartOverview).toHaveBeenCalledTimes(1)
    expect(onStartBriefing).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Start Briefing with Daily' }))
    expect(onStartBriefing).toHaveBeenCalledTimes(1)
  })

  it('keeps Overview available when only briefing generation is unavailable', () => {
    render(<StandbyActions onStartOverview={vi.fn()} onStartBriefing={vi.fn()} briefingDisabled />)

    expect(screen.getByRole('button', { name: 'Start Overview' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Start Briefing with Daily' })).toBeDisabled()
  })

  it('disables both actions while activation is blocked', () => {
    render(<StandbyActions onStartOverview={vi.fn()} onStartBriefing={vi.fn()} disabled />)

    expect(screen.getByRole('button', { name: 'Start Overview' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Start Briefing with Daily' })).toBeDisabled()
  })
})
