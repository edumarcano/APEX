import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type {
  AgentAvailabilityStatus,
  BriefingMode,
  BriefingTargetStatus,
} from '../types/telemetry'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'

function target(
  mode: BriefingMode,
  status: AgentAvailabilityStatus = 'available',
  reason: string | null = null,
): BriefingTargetStatus {
  const local = mode === 'felis'
  return {
    mode,
    label: mode === 'panthera' ? 'Apex Panthera' : mode === 'felis' ? 'Apex Felis' : 'Structured Digest',
    description: mode === 'panthera' ? 'Full briefing · GPT-5.6 Luna' : mode === 'felis' ? 'Full briefing · Gemma 4 E2B' : 'Structured facts · no model or synthesis',
    model_id: mode === 'structured_digest' ? null : mode,
    model_display_name: mode === 'structured_digest' ? null : mode,
    provider: mode === 'panthera' ? 'openai' : local ? 'llama_cpp' : null,
    runtime: mode === 'structured_digest' ? 'none' : local ? 'local' : 'cloud',
    status,
    reason,
    pricing: mode === 'structured_digest' ? null : {
      currency: 'USD',
      pricing_version: 'test',
      billing_basis: local ? 'local' : 'standard',
      input_per_million: local ? 0 : 0.2,
      output_per_million: local ? 0 : 1.2,
      cached_input_per_million: null,
      long_context_threshold_tokens: null,
      long_context_input_per_million: null,
      long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
  }
}

const AVAILABLE_TARGETS = [
  target('panthera'),
  target('felis'),
  target('structured_digest'),
]

function renderSelector(overrides: Partial<ComponentProps<typeof BriefingModeSelector>> = {}) {
  const props: ComponentProps<typeof BriefingModeSelector> = {
    value: 'panthera',
    onChange: vi.fn(),
    targets: AVAILABLE_TARGETS,
    disabled: false,
    ...overrides,
  }
  return { ...render(<BriefingModeSelector {...props} />), props }
}

describe('BriefingModeSelector', () => {
  it('groups and describes cloud, local, and model-free modes', async () => {
    const user = userEvent.setup()
    renderSelector()

    await user.click(screen.getByRole('button', { name: /briefing: apex panthera/i }))
    const listbox = screen.getByRole('listbox', { name: /select briefing mode/i })

    expect(screen.getByText('Briefing Synthesis')).toBeVisible()
    expect(screen.getByText('Select a mode for the next briefing.')).toBeVisible()
    expect(screen.getAllByLabelText('Panthera agent mark')).toHaveLength(2)
    expect(screen.getByLabelText('Structured Digest mark')).toBeVisible()
    expect(screen.getAllByText('No provider token charge')).toHaveLength(1)
    expect(screen.getByText('No model cost')).toBeVisible()
    expect(within(listbox).getByRole('group', { name: 'Cloud' })).toBeInTheDocument()
    expect(within(listbox).getByRole('group', { name: 'Local' })).toBeInTheDocument()
    expect(within(listbox).getByText('Full briefing · GPT-5.6 Luna')).toBeVisible()
    expect(within(listbox).getByText('Full briefing · Gemma 4 E2B')).toBeVisible()
    expect(within(listbox).getByText('Structured facts · no model or synthesis')).toBeVisible()
    expect(within(listbox).queryByRole('option', { name: /^Mus\b/i })).not.toBeInTheDocument()
    expect(within(listbox).queryByRole('option', { name: /^Sorex\b/i })).not.toBeInTheDocument()
  })

  it('blocks unavailable model modes but always allows Structured Digest', async () => {
    const onModeChange = vi.fn()
    const user = userEvent.setup()
    renderSelector({
      onChange: onModeChange,
      targets: [
        target('panthera'),
        target('felis', 'insufficient_ram', 'Current memory pressure exceeds threshold'),
        target('structured_digest'),
      ],
    })

    await user.click(screen.getByRole('button', { name: /briefing: apex panthera/i }))
    expect(screen.getByRole('option', { name: /felis/i })).toBeDisabled()

    await user.click(screen.getByRole('option', { name: /structured digest/i }))
    expect(onModeChange).toHaveBeenCalledWith('structured_digest')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores focus to the selector', async () => {
    const user = userEvent.setup()
    renderSelector()
    const trigger = screen.getByRole('button', { name: /briefing: apex panthera/i })

    await user.click(trigger)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('shows the selected mode description rather than pricing while closed', () => {
    renderSelector()

    expect(screen.getByRole('button', { name: /briefing: apex panthera/i })).toHaveTextContent(/Full briefing/)
    expect(screen.getByRole('button', { name: /briefing: apex panthera/i })).not.toHaveTextContent(/In \$/)
  })

  it('does not use interactive Agent pricing when a briefing target is missing', async () => {
    const user = userEvent.setup()
    renderSelector({ targets: [target('structured_digest')] })

    await user.click(screen.getByRole('button', { name: /briefing: apex panthera/i }))

    expect(screen.getAllByText('Pricing unavailable')).toHaveLength(2)
  })
})

describe('BriefingGenerateControl', () => {
  it('keeps refresh-and-synthesize available when current-snapshot synthesis is disabled', async () => {
    const onGenerate = vi.fn()
    const onRefreshAll = vi.fn()
    const onRefreshAndGenerate = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingGenerateControl
        mainDisabled
        refreshDisabled={false}
        busy={false}
        onGenerate={onGenerate}
        onRefreshAll={onRefreshAll}
        onRefreshAndGenerate={onRefreshAndGenerate}
      />,
    )

    expect(screen.getByRole('button', { name: /synthesize briefing from current telemetry/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /more briefing synthesis options/i }))
    await user.click(screen.getByRole('menuitem', { name: /refresh all & synthesize/i }))

    expect(onGenerate).not.toHaveBeenCalled()
    expect(onRefreshAndGenerate).toHaveBeenCalledTimes(1)
  })

  it('offers refresh-only work from the synthesis menu', async () => {
    const onRefreshAll = vi.fn()
    const user = userEvent.setup()
    render(
      <BriefingGenerateControl
        mainDisabled={false}
        refreshDisabled={false}
        busy={false}
        onGenerate={vi.fn()}
        onRefreshAll={onRefreshAll}
        onRefreshAndGenerate={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('button', { name: /more briefing synthesis options/i }))
    await user.click(screen.getAllByRole('menuitem')[0])

    expect(onRefreshAll).toHaveBeenCalledTimes(1)
  })

})
