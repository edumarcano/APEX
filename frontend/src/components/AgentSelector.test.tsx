import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus } from '../types/telemetry'

import { AgentSelector } from './AgentSelector'

function agent(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    key: 'panthera',
    display_name: 'Apex Panthera',
    description: 'Cloud generalist.',
    configured_model: 'gpt-5.6-luna',
    sort_order: 1,
    capabilities: ['Generalist'],
    native_tools: {},
    provider: 'openai',
    version: '7.4',
    runtime: 'cloud',
    tier: 'balanced',
    stability: 'stable',
    effort_options: ['light', 'focused', 'extended'],
    default_effort: 'focused',
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

const apodemus = agent({
  key: 'apodemus',
  display_name: 'Apex Apodemus',
  description: 'Preview private local Agent for efficient tool-driven work through llama.cpp.',
  configured_model: 'gemma-4-E2B-Q4_K_M.gguf',
  sort_order: 6,
  stability: 'preview',
  capabilities: ['Efficient local', 'Tool use', 'Selectable context'],
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

const previewCloud = agent({
  key: 'acinonyx',
  display_name: 'Apex Acinonyx',
  description: 'Experimental cloud profile.',
  configured_model: 'gemini-3.6-flash',
  sort_order: 2,
  stability: 'preview',
  provider: 'gemini',
  capabilities: ['Privacy sandbox'],
  status: 'configured',
})

describe('AgentSelector', () => {
  it('formats Apodemus gguf models and labels llama.cpp', async () => {
    const user = userEvent.setup()
    render(
      <AgentSelector
        activeAgent="apodemus"
        onChange={vi.fn()}
        agentsStatus={[apodemus]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    expect(screen.getByText('Apex Apodemus')).toBeVisible()
    expect(
      screen.getByText('Powered by Gemma 4 E2B Q4_K_M · Runs locally through llama.cpp'),
    ).toBeVisible()

    await user.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByRole('button', { name: 'Use Apex Apodemus' })).toBeVisible()
  })

  it('shows preview stability badges for any agent marked preview', async () => {
    const user = userEvent.setup()
    render(
      <AgentSelector
        activeAgent="apodemus"
        onChange={vi.fn()}
        agentsStatus={[agent(), previewCloud, apodemus]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
      />,
    )

    expect(screen.getByText('Preview')).toBeVisible()

    await user.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getAllByText('Preview')).toHaveLength(2)

    await user.click(screen.getByRole('tab', { name: 'Cloud agents' }))
    expect(screen.getByRole('button', { name: 'Use Apex Acinonyx' })).toBeVisible()
    expect(screen.getAllByText('Preview')).toHaveLength(2)
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
        activeAgent="apodemus"
        onChange={vi.fn()}
        agentsStatus={[apodemus]}
        agentsStatusHydrated
        isQuerying={false}
        verifyingAgent={null}
        onVerify={vi.fn(async () => true)}
        presentation="home"
      />,
    )

    expect(screen.getByRole('button', { name: 'Agent Apodemus, Available, Preview' })).toBeVisible()
    expect(screen.getByText('Preview')).toBeVisible()
  })
})
