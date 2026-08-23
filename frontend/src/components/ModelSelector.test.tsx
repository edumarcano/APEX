import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, ModelCatalogEntry } from '../types/telemetry'
import { ModelSelector } from './ModelSelector'

const cloudModels: ModelCatalogEntry[] = [
  {
    model_id: 'gpt-5.6-luna',
    display_name: 'GPT-5.6 Luna',
    provider: 'openai',
    runtime: 'cloud',
    stability: 'stable',
    pricing: {
      currency: 'USD',
      pricing_version: '2026.08.02',
      billing_basis: 'standard',
      input_per_million: 0.2,
      output_per_million: 1.2,
      cached_input_per_million: 0.02,
      long_context_threshold_tokens: 272000,
      long_context_input_per_million: 0.4,
      long_context_output_per_million: 1.8,
      long_context_cached_input_per_million: 0.04,
    },
    default_reasoning: 'medium',
    reasoning_options: ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'],
    hosted_capabilities: [],
  },
  {
    model_id: 'gemini-3.6-flash',
    display_name: 'Gemini 3.6 Flash',
    provider: 'gemini',
    runtime: 'cloud',
    stability: 'stable',
    pricing: {
      currency: 'USD',
      pricing_version: '2026.08.02',
      billing_basis: 'standard',
      input_per_million: 0.75,
      output_per_million: 3.75,
      cached_input_per_million: 0.075,
      long_context_threshold_tokens: null,
      long_context_input_per_million: null,
      long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
    default_reasoning: 'medium',
    reasoning_options: ['minimal', 'low', 'medium', 'high'],
    hosted_capabilities: ['google_search', 'google_maps'],
    dev_only: true,
  },
  {
    model_id: 'gemini-3.5-flash-lite',
    display_name: 'Gemini 3.5 Flash Lite',
    provider: 'gemini',
    runtime: 'cloud',
    stability: 'experimental',
    pricing: {
      currency: 'USD',
      pricing_version: '2026.08.02',
      billing_basis: 'free_tier',
      input_per_million: 0,
      output_per_million: 0,
      cached_input_per_million: null,
      long_context_threshold_tokens: null,
      long_context_input_per_million: null,
      long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
    default_reasoning: 'medium',
    reasoning_options: ['minimal', 'low', 'medium', 'high'],
    hosted_capabilities: [],
    dev_only: true,
  },
]

const localModels: ModelCatalogEntry[] = [
  {
    model_id: 'gemma-4-E2B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E2B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'stable',
    pricing: {
      currency: 'USD',
      pricing_version: '2026.08.02',
      billing_basis: 'local',
      input_per_million: 0,
      output_per_million: 0,
      cached_input_per_million: null,
      long_context_threshold_tokens: null,
      long_context_input_per_million: null,
      long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
    default_reasoning: null,
    reasoning_options: null,
    context_options: [4096, 16384, 32768, 131072],
    default_context_window: 16384,
    high_resource_context_options: [131072],
    maximum_context_window: 131072,
    reasoning_modes: ['none', 'focused'],
    default_reasoning_mode: 'none',
    hosted_capabilities: [],
  },
]

const pantheraStatus: AgentStatus = {
  key: 'cloud',
  display_name: 'Apex Panthera',
  description: 'Cloud profile',
  configured_model: 'gpt-5.6-luna',
  sort_order: 1,
  capabilities: ['Generalist'],
  native_tools: {},
  provider: 'openai',
  runtime: 'cloud',
  model_stability: 'stable',
  reasoning_options: ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'],
  default_reasoning: 'medium',
  context_window: null,
  context_window_options: null,
  context_window_high_resource_options: null,
  default_context_window: null,
  reasoning_mode: null,
  reasoning_mode_options: null,
  default_reasoning_mode: null,
  status: 'verified',
  status_source: 'verification',
  status_checked_at: null,
  provider_account_tier: null,
  pricing: {
    currency: 'USD',
    pricing_version: '2026.08.02',
    billing_basis: 'standard',
    input_per_million: 0.2,
    output_per_million: 1.2,
    cached_input_per_million: 0.02,
    long_context_threshold_tokens: 272000,
    long_context_input_per_million: 0.4,
    long_context_output_per_million: 1.8,
    long_context_cached_input_per_million: 0.04,
  },
  active: false,
  loading: false,
  reason: null,
  idle_unload_remaining_seconds: null,
  loaded_model: null,
  model_catalog: cloudModels,
}

describe('ModelSelector', () => {
  it('renders selected model card with pricing, capabilities, and no badge for stable models', () => {
    render(
      <ModelSelector
        activeAgent="cloud"
        selectedModelId="gpt-5.6-luna"
        onModelChange={vi.fn()}
        catalog={cloudModels}
        activeStatus={pantheraStatus}
      />,
    )

    expect(screen.getByText('GPT-5.6 Luna')).toBeVisible()
    expect(screen.getAllByText('OpenAI').length).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText('Stable')).toBeNull()
    expect(screen.getByText('$0.20/M in · $1.20/M out')).toBeVisible()
    expect(screen.getByText('Reasoning')).toBeVisible()
    expect(screen.getByText('272K+ context')).toBeVisible()
    expect(screen.getByText('Verified')).toBeVisible()
  })

  it('renders privacy banner when free-tier model is selected', () => {
    render(
      <ModelSelector
        activeAgent="cloud"
        selectedModelId="gemini-3.5-flash-lite"
        onModelChange={vi.fn()}
        catalog={cloudModels}
        activeStatus={pantheraStatus}
      />,
    )

    expect(screen.getByText('Gemini 3.5 Flash Lite')).toBeVisible()
    expect(screen.getByText('Free tier')).toBeVisible()
    expect(
      screen.getByText('Free tier · Content may be used to improve Google products'),
    ).toBeVisible()
  })

  it('opens model browser when trigger card is clicked and allows selecting a new model', async () => {
    const user = userEvent.setup()
    const onModelChange = vi.fn()

    render(
      <ModelSelector
        activeAgent="cloud"
        selectedModelId="gpt-5.6-luna"
        onModelChange={onModelChange}
        catalog={cloudModels}
        activeStatus={pantheraStatus}
      />,
    )

    const trigger = screen.getByRole('button', { name: /Model/i })
    await user.click(trigger)

    expect(screen.getByRole('listbox', { name: 'Select model for cloud' })).toBeVisible()
    expect(screen.getByText('Gemini 3.6 Flash')).toBeVisible()
    expect(screen.getByText('Gemini 3.5 Flash Lite')).toBeVisible()

    await user.click(screen.getByRole('option', { name: /Gemini 3.6 Flash/i }))
    expect(onModelChange).toHaveBeenCalledWith('gemini-3.6-flash')
  })

  it('renders local model card with no provider charge, context, and residency state', () => {
    const felisStatus: AgentStatus = {
      ...pantheraStatus,
      key: 'local',
      display_name: 'Apex Felis',
      configured_model: 'gemma-4-E2B-Q4_K_M.gguf',
      provider: 'llama_cpp',
      runtime: 'local',
      active: true,
      model_catalog: localModels,
    }

    render(
      <ModelSelector
        activeAgent="local"
        selectedModelId="gemma-4-E2B-Q4_K_M.gguf"
        onModelChange={vi.fn()}
        catalog={localModels}
        activeStatus={felisStatus}
      />,
    )

    expect(screen.getByText('Gemma 4 E2B')).toBeVisible()
    expect(screen.getByText('llama.cpp')).toBeVisible()
    expect(screen.getByText('Local · No provider charge')).toBeVisible()
    expect(screen.getByText('Loaded')).toBeVisible()
    expect(screen.getByText('Selectable context')).toBeVisible()
  })

  it('provides a verify access action on cloud models', async () => {
    const user = userEvent.setup()
    const onVerify = vi.fn(async () => true)

    render(
      <ModelSelector
        activeAgent="cloud"
        selectedModelId="gpt-5.6-luna"
        onModelChange={vi.fn()}
        catalog={cloudModels}
        activeStatus={pantheraStatus}
        onVerify={onVerify}
      />,
    )

    const verifyBtn = screen.getByRole('button', { name: 'Verify' })
    expect(verifyBtn).toBeVisible()

    await user.click(verifyBtn)
    expect(onVerify).toHaveBeenCalledWith('cloud')
  })
})
