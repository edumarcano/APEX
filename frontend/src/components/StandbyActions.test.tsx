import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { StandbyActions } from './StandbyActions'

describe('StandbyActions', () => {
  it('renders title-case action labels and responds to clicks', async () => {
    const onStartApex = vi.fn()
    const onStartWithBriefing = vi.fn()
    const user = userEvent.setup()

    render(
      <StandbyActions
        onStartApex={onStartApex}
        onStartWithBriefing={onStartWithBriefing}
        disabled={false}
      />,
    )

    const startBtn = screen.getByRole('button', { name: 'Start APEX' })
    const briefingBtn = screen.getByRole('button', { name: 'Start APEX with briefing' })

    expect(startBtn).toHaveTextContent('Start APEX')
    expect(briefingBtn).toHaveTextContent('Start with Briefing')

    await user.click(startBtn)
    expect(onStartApex).toHaveBeenCalledTimes(1)

    await user.click(briefingBtn)
    expect(onStartWithBriefing).toHaveBeenCalledTimes(1)
  })

  it('disables both actions when disabled prop is true', () => {
    render(
      <StandbyActions
        onStartApex={vi.fn()}
        onStartWithBriefing={vi.fn()}
        disabled
      />,
    )

    expect(screen.getByRole('button', { name: 'Start APEX' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Start APEX with briefing' })).toBeDisabled()
  })
})
