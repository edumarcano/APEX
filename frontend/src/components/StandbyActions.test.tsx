import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { StandbyActions } from './StandbyActions'

describe('StandbyActions', () => {
  it('routes Collect Telemetry to its handler', async () => {
    const onCollectTelemetry = vi.fn()
    const user = userEvent.setup()

    render(<StandbyActions onCollectTelemetry={onCollectTelemetry} />)

    await user.click(screen.getByRole('button', { name: 'Collect Telemetry' }))
    expect(onCollectTelemetry).toHaveBeenCalledTimes(1)
  })

  it('exposes Collect Telemetry when no briefing model is ready', () => {
    render(<StandbyActions onCollectTelemetry={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Collect Telemetry' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Open Briefing setup' })).not.toBeInTheDocument()
  })

  it('disables Collect Telemetry while activation is blocked', () => {
    render(<StandbyActions onCollectTelemetry={vi.fn()} disabled />)

    expect(screen.getByRole('button', { name: 'Collect Telemetry' })).toBeDisabled()
  })
})
