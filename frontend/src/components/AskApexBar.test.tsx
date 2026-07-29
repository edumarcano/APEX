import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AgentProfileStatus, LocalCommandStatus } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'

const localProfile: AgentProfileStatus = {
  key: 'lynx',
  display_name: 'Apex Lynx',
  provider: 'ollama',
  tier: 'lightweight',
  stability: 'stable',
  status: 'available',
  active: false,
  loading: false,
  reason: null,
  idle_unload_remaining_seconds: null,
  loaded_model: null,
}

const weatherCommand: LocalCommandStatus = {
  key: 'weather',
  command: '/weather',
  label: 'Weather',
  description: 'Configured-location forecast up to five days.',
  tool_count: 1,
  estimated_schema_tokens: 120,
  available: true,
  unavailable_reason: null,
}

const unavailableWeatherCommand: LocalCommandStatus = {
  ...weatherCommand,
  available: false,
  unavailable_reason: 'Required provider tools are not currently connected.',
}

describe('AskApexBar local commands', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('arms a bare slash command for one submitted query', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([weatherCommand]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const onSubmit = vi.fn()

    render(
      <AskApexBar
        activeProfile="lynx"
        onProfileChange={vi.fn()}
        onSubmit={onSubmit}
        profilesStatus={[localProfile]}
        profilesStatusHydrated
        isSubmitting={false}
        showCommands
        integrated
      />,
    )

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce())
    const input = screen.getByLabelText('Ask APEX query')
    fireEvent.change(input, { target: { value: '/weather' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('/weather armed · one shot')).toBeInTheDocument()

    fireEvent.change(input, { target: { value: 'What is the forecast?' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))

    expect(onSubmit).toHaveBeenCalledWith(
      'What is the forecast?',
      'lynx',
      'weather',
    )
    expect(screen.getByText('No tools')).toBeInTheDocument()
  })

  it('refreshes provider availability when the command panel opens', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify([unavailableWeatherCommand]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([weatherCommand]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    render(
      <AskApexBar
        activeProfile="lynx"
        onProfileChange={vi.fn()}
        onSubmit={vi.fn()}
        profilesStatus={[localProfile]}
        profilesStatusHydrated
        isSubmitting={false}
        showCommands
        integrated
      />,
    )

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce())
    fireEvent.click(screen.getByRole('button', { name: 'Commands' }))

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /\/weather/ })).toBeEnabled(),
    )
  })
})
