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
  const local = mode === 'flash'
  return {
    mode,
    label: mode === 'focused' ? 'Focused' : mode === 'flash' ? 'Flash' : 'Structured',
    description: mode === 'focused' ? 'Panthera · DeepSeek V4 Flash' : mode === 'flash' ? 'Felis · local model' : 'Deterministic · no model',
    model_id: mode === 'structured' ? null : mode,
    model_display_name: mode === 'structured' ? null : mode,
    provider: mode === 'focused' ? 'openrouter' : local ? 'llama_cpp' : null,
    runtime: mode === 'structured' ? 'none' : local ? 'local' : 'cloud',
    status,
    reason,
    pricing: mode === 'structured' ? null : {
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
  target('flash'),
  target('focused'),
  target('structured'),
]

function renderSelector(overrides: Partial<ComponentProps<typeof BriefingModeSelector>> = {}) {
  const props: ComponentProps<typeof BriefingModeSelector> = {
    value: 'flash',
    onChange: vi.fn(),
    targets: AVAILABLE_TARGETS,
    disabled: false,
    ...overrides,
  }
  return { ...render(<BriefingModeSelector {...props} />), props }
}

describe('BriefingModeSelector', () => {
  it('orders and describes Flash, Focused, and Structured modes', async () => {
    const user = userEvent.setup()
    renderSelector()

    await user.click(screen.getByRole('button', { name: /briefing mode: flash/i }))
    const listbox = screen.getByRole('listbox', { name: /select briefing mode/i })

    expect(screen.getByText('Briefing Mode')).toBeVisible()
    expect(screen.getByText('Select a briefing type for the next briefing.')).toBeVisible()
    expect(screen.getAllByLabelText('Flash Briefing mark')).toHaveLength(2)
    expect(screen.getByLabelText('Focused Briefing mark')).toBeVisible()
    expect(screen.getByLabelText('Structured Briefing mark')).toBeVisible()
    expect(screen.getAllByText('No provider token charge')).toHaveLength(1)
    expect(screen.getByText('No model cost')).toBeVisible()
    expect(within(listbox).getAllByRole('option')).toHaveLength(3)
    expect(within(listbox).getByText('Felis · local model')).toBeVisible()
    expect(within(listbox).getByText('Panthera · DeepSeek V4 Flash')).toBeVisible()
    expect(within(listbox).getByText('Deterministic · no model')).toBeVisible()
    expect(within(listbox).queryByRole('option', { name: /^Mus\b/i })).not.toBeInTheDocument()
    expect(within(listbox).queryByRole('option', { name: /^Sorex\b/i })).not.toBeInTheDocument()
  })

  it('blocks unavailable model modes but always allows Structured', async () => {
    const onModeChange = vi.fn()
    const user = userEvent.setup()
    renderSelector({
      onChange: onModeChange,
      targets: [
        target('flash', 'insufficient_ram', 'Current memory pressure exceeds threshold'),
        target('focused'),
        target('structured'),
      ],
    })

    await user.click(screen.getByRole('button', { name: /briefing mode: flash/i }))
    expect(screen.getAllByRole('option')[0]).toBeDisabled()

    await user.click(screen.getByRole('option', { name: /structured/i }))
    expect(onModeChange).toHaveBeenCalledWith('structured')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores focus to the selector', async () => {
    const user = userEvent.setup()
    renderSelector()
    const trigger = screen.getByRole('button', { name: /briefing mode: flash/i })

    await user.click(trigger)
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('shows the selected mode description rather than pricing while closed', () => {
    renderSelector()

    expect(screen.getByRole('button', { name: /briefing mode: flash/i })).toHaveTextContent(/Flash/)
    expect(screen.getByRole('button', { name: /briefing mode: flash/i })).not.toHaveTextContent(/In \$/)
  })

  it('does not use interactive Agent pricing when a briefing target is missing', async () => {
    const user = userEvent.setup()
    renderSelector({ targets: [target('structured')] })

    await user.click(screen.getByRole('button', { name: /briefing mode: flash/i }))

    expect(screen.getAllByText('Pricing unavailable')).toHaveLength(2)
  })
})

describe('BriefingGenerateControl', () => {
  it('keeps refresh-and-generate available when current-snapshot generation is disabled', async () => {
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

    expect(screen.getByRole('button', { name: /generate briefing from current telemetry/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /more briefing generation options/i }))
    await user.click(screen.getByRole('menuitem', { name: /refresh all & generate briefing/i }))

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

    await user.click(screen.getByRole('button', { name: /more briefing generation options/i }))
    await user.click(screen.getAllByRole('menuitem')[0])

    expect(onRefreshAll).toHaveBeenCalledTimes(1)
  })

})
