import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus } from '../types/telemetry'

import { AgentSelector } from './AgentSelector'

function agent(overrides: Partial<AgentStatus> = {}): AgentStatus {
  const stability = overrides.stability ?? 'stable'
  return {
    key: 'panthera',
    display_name: 'Apex Panthera',
    description: 'Cloud generalist.',
    configured_model: 'gpt-5.6-luna',
    sort_order: 1,
    capabilities: ['Generalist'],
    native_tools: {},
    provider: 'openai',
    version: '2.0',
    runtime: 'cloud',
    tier: 'balanced',
    stability,
    model_stability: overrides.model_stability ?? stability,
    effort_options: ['light', 'focused', 'extended'],
    default_effort: 'focused',
    context_window: null,
    context_window_options: null,
    context_window_high_resource_options: null,
    default_context_window: null,
    reasoning_mode: null,
    reasoning_mode_options: null,
    default_reasoning_mode: null,
    status: 'configured',
    status_source: 'configuration',
    status_checked_at: null,
    provider_account_tier: null,
    pricing: {
      currency: 'USD',
      pricing_version: 'test',
      billing_basis: 'standard',
      input_per_million: 0.2,
      output_per_million: 1.2,
      cached_input_per_million: null,
      long_context_threshold_tokens: null,
      long_context_input_per_million: null,
      long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
    active: false,
    loading: false,
    reason: null,
    idle_unload_remaining_seconds: null,
    loaded_model: null,
    ...overrides,
  }
}

const felis = agent({
  key: 'felis',
  display_name: 'Apex Felis',
  description: 'Local Agent for private on-device work.',
  configured_model: 'gemma-4-E2B-Q4_K_M.gguf',
  sort_order: 2,
  capabilities: ['Local', 'Private'],
  provider: 'llama_cpp',
  runtime: 'local',
  effort_options: null,
  default_effort: null,
  status: 'available',
  status_source: 'runtime',
  pricing: {
    currency: 'USD',
    pricing_version: 'test',
    billing_basis: 'local',
    input_per_million: 0,
    output_per_million: 0,
    cached_input_per_million: null,
    long_context_threshold_tokens: null,
    long_context_input_per_million: null,
    long_context_output_per_million: null,
    long_context_cached_input_per_million: null,
  },
})

describe('AgentSelector', () => {
  it('renders segmented 2-choice buttons in Cortex without opening a popover', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <AgentSelector
        activeAgent="panthera"
        onChange={onChange}
        agentsStatus={[agent(), felis]}
        agentsStatusHydrated
        isQuerying={false}
      />,
    )

    expect(screen.getByRole('radio', { name: /Apex Panthera, Cloud · Generalist/i })).toBeVisible()
    expect(screen.getByRole('radio', { name: /Apex Felis, Local · Private/i })).toBeVisible()

    await user.click(screen.getByRole('radio', { name: /Apex Felis, Local · Private/i }))
    expect(onChange).toHaveBeenCalledWith('felis')
  })

  it('indicates the active agent in Cortex with checked state', () => {
    render(
      <AgentSelector
        activeAgent="felis"
        onChange={vi.fn()}
        agentsStatus={[agent(), felis]}
        agentsStatusHydrated
        isQuerying={false}
      />,
    )

    const pantheraRadio = screen.getByRole('radio', { name: /Apex Panthera/i })
    const felisRadio = screen.getByRole('radio', { name: /Apex Felis/i })

    expect(pantheraRadio).toHaveAttribute('aria-checked', 'false')
    expect(felisRadio).toHaveAttribute('aria-checked', 'true')
  })

  it('renders a compact trigger on home presentation and opens simplified popover', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <AgentSelector
        activeAgent="panthera"
        onChange={onChange}
        agentsStatus={[agent(), felis]}
        agentsStatusHydrated
        isQuerying={false}
        presentation="home"
      />,
    )

    const trigger = screen.getByRole('button', { name: /Agent Panthera/i })
    expect(trigger).toBeVisible()

    await user.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Select Agent' })).toBeVisible()
    expect(screen.getByRole('option', { name: 'Use Apex Panthera' })).toBeVisible()
    expect(screen.getByRole('option', { name: 'Use Apex Felis' })).toBeVisible()

    await user.click(screen.getByRole('option', { name: 'Use Apex Felis' }))
    expect(onChange).toHaveBeenCalledWith('felis')
  })

  it('disables switching while an agent query is in flight', () => {
    render(
      <AgentSelector
        activeAgent="panthera"
        onChange={vi.fn()}
        agentsStatus={[agent(), felis]}
        agentsStatusHydrated
        isQuerying
      />,
    )

    expect(screen.getByRole('radio', { name: /Apex Panthera/i })).toBeDisabled()
    expect(screen.getByRole('radio', { name: /Apex Felis/i })).toBeDisabled()
  })
})


