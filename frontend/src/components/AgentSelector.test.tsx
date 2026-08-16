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

const lynx = agent({
  key: 'lynx',
  display_name: 'Apex Lynx',
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

const previewLynx = agent({
  key: 'lynx',
  display_name: 'Apex Lynx',
  description: 'Preview local Agent.',
  configured_model: 'gemma-4-E4B-Q4_K_M.gguf',
  sort_order: 2,
  stability: 'preview',
  model_stability: 'preview',
  provider: 'llama_cpp',
  runtime: 'local',
  capabilities: ['Local'],
  status: 'available',
  status_source: 'runtime',
})

describe('AgentSelector', () => {
  it('formats Lynx gguf models and labels llama.cpp', async () => {
    const user = userEvent.setup()
    render(
      <AgentSelector
        activeAgent="lynx"
        onChange={vi.fn()}
        agentsStatus={[lynx]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    expect(screen.getByText('Apex Lynx')).toBeVisible()
    expect(
      screen.getByText('Powered by Gemma 4 E2B Q4_K_M · Runs locally through llama.cpp'),
    ).toBeVisible()

    await user.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByRole('button', { name: 'Use Apex Lynx' })).toBeVisible()
  })

  it('shows preview stability badges for any agent marked preview', async () => {
    const user = userEvent.setup()
    render(
      <AgentSelector
        activeAgent="lynx"
        onChange={vi.fn()}
        agentsStatus={[agent(), previewLynx]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    expect(screen.getByText('Preview')).toBeVisible()

    await user.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getAllByText('Preview')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Use Apex Panthera' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Use Apex Lynx' })).toBeVisible()
  })

  it('omits preview badges for stable agents', () => {
    render(
      <AgentSelector
        activeAgent="panthera"
        onChange={vi.fn()}
        agentsStatus={[agent()]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    expect(screen.queryByText('Preview')).not.toBeInTheDocument()
  })

  it('shows preview badge on the home presentation trigger', () => {
    render(
      <AgentSelector
        activeAgent="lynx"
        onChange={vi.fn()}
        agentsStatus={[previewLynx]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
        presentation="home"
      />,
    )

    expect(screen.getByRole('button', { name: 'Agent Lynx, Available, Preview' })).toBeVisible()
    expect(screen.getByText('Preview')).toBeVisible()
  })

  it('allows Lynx selection when the local runtime is not yet ready', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const notReady = agent({
      ...lynx,
      status: 'model_not_installed',
      reason: 'Model is not installed or configured locally',
    })

    render(
      <AgentSelector
        activeAgent="panthera"
        onChange={onChange}
        agentsStatus={[agent(), notReady]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    await user.click(screen.getByRole('button', { expanded: false }))
    await user.click(screen.getByRole('button', { name: 'Use Apex Lynx' }))
    expect(onChange).toHaveBeenCalledWith('lynx')
  })

  it('shows experimental stability badges for any agent marked experimental', () => {
    const experimental = agent({
      key: 'panthera',
      display_name: 'Apex Panthera',
      description: 'Experimental cloud model.',
      configured_model: 'gemini-3.5-flash-lite',
      sort_order: 1,
      stability: 'experimental',
      model_stability: 'experimental',
      provider: 'gemini',
      capabilities: ['Privacy sandbox'],
    })
    render(
      <AgentSelector
        activeAgent="panthera"
        onChange={vi.fn()}
        agentsStatus={[experimental]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    expect(screen.getByText('Experimental')).toBeVisible()
  })
})
