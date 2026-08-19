import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, ModelCatalogEntry } from '../types/telemetry'
import { HomeModelSelector } from './HomeModelSelector'

const mockCatalog: ModelCatalogEntry[] = [
  {
    model_id: 'deepseek/deepseek-v4-flash-0731',
    display_name: 'DeepSeek V4 Flash',
    provider: 'openrouter',
    runtime: 'cloud',
    stability: 'stable',
    reasoning_options: ['none', 'low', 'high', 'max'],
    default_reasoning: 'high',
    hosted_capabilities: [],
  },
  {
    model_id: 'gpt-5.6-luna',
    display_name: 'GPT-5.6 Luna',
    provider: 'openai',
    runtime: 'cloud',
    stability: 'stable',
    reasoning_options: ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'],
    default_reasoning: 'medium',
    hosted_capabilities: [],
  },
  {
    model_id: 'gemma-4-E2B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E2B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'stable',
    reasoning_options: null,
    default_reasoning: null,
    maximum_context_window: 131072,
    hosted_capabilities: [],
  },
]

function profile(
  key: 'panthera' | 'felis',
  status: AgentStatus['status'],
  configuredModel: string,
): AgentStatus {
  const local = key === 'felis'
  return {
    key,
    display_name: key === 'panthera' ? 'Apex Panthera' : 'Apex Felis',
    description: `${key} profile.`,
    configured_model: configuredModel,
    sort_order: key === 'panthera' ? 1 : 2,
    capabilities: [],
    native_tools: {},
    provider: local ? 'llama_cpp' : 'openrouter',
    runtime: local ? 'local' : 'cloud',
    model_stability: 'stable',
    reasoning_options: local ? null : ['none', 'low', 'high', 'max'],
    default_reasoning: local ? null : 'high',
    context_window: local ? 16384 : null,
    context_window_options: local ? [4096, 16384, 32768, 131072] : null,
    context_window_high_resource_options: local ? [131072] : null,
    default_context_window: local ? 16384 : null,
    reasoning_mode: local ? 'none' : null,
    reasoning_mode_options: local ? ['none', 'focused'] : null,
    default_reasoning_mode: local ? 'none' : null,
    status,
    status_source: local ? 'runtime' : 'configuration',
    status_checked_at: null,
    provider_account_tier: null,
    pricing: {
      currency: 'USD', pricing_version: 'test', billing_basis: local ? 'local' : 'standard',
      input_per_million: local ? 0 : 0.2, output_per_million: local ? 0 : 1.2,
      cached_input_per_million: null, long_context_threshold_tokens: null,
      long_context_input_per_million: null, long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
    active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
    model_catalog: mockCatalog,
  }
}

const mockAgentsStatus: AgentStatus[] = [
  profile('panthera', 'configured', 'deepseek/deepseek-v4-flash-0731'),
  profile('felis', 'available', 'gemma-4-E2B-Q4_K_M.gguf'),
]

describe('HomeModelSelector', () => {
  it('renders selected cloud model with secondary Panthera metadata', () => {
    render(
      <HomeModelSelector
        selectedModelId="deepseek/deepseek-v4-flash-0731"
        onModelChange={vi.fn()}
        catalog={mockCatalog}
        agentsStatus={mockAgentsStatus}
      />,
    )

    expect(screen.getByText('DeepSeek V4 Flash')).toBeInTheDocument()
    expect(screen.getByText(/Panthera · OpenRouter · Reasoning off/i)).toBeInTheDocument()
  })

  it('renders selected local model with secondary Felis metadata', () => {
    render(
      <HomeModelSelector
        selectedModelId="gemma-4-E2B-Q4_K_M.gguf"
        onModelChange={vi.fn()}
        catalog={mockCatalog}
        agentsStatus={mockAgentsStatus}
      />,
    )

    expect(screen.getByText('Gemma 4 E2B')).toBeInTheDocument()
    expect(screen.getByText(/Felis · llama\.cpp · 16K · Reasoning off/i)).toBeInTheDocument()
  })

  it('opens popover grouped by Cloud (Panthera) and Local (Felis) and selects a model', async () => {
    const onModelChange = vi.fn()
    const user = userEvent.setup()

    render(
      <HomeModelSelector
        selectedModelId="deepseek/deepseek-v4-flash-0731"
        onModelChange={onModelChange}
        catalog={mockCatalog}
        agentsStatus={mockAgentsStatus}
      />,
    )

    await user.click(screen.getByRole('combobox', { name: /model: deepseek v4 flash/i }))
    const popover = screen.getByRole('listbox', { name: /available models/i })
    expect(popover).toBeInTheDocument()

    expect(within(popover).getByText(/Cloud · Panthera/i)).toBeInTheDocument()
    expect(within(popover).getByText(/Local · Felis/i)).toBeInTheDocument()

    await user.click(within(popover).getByRole('option', { name: /gemma 4 e2b/i }))
    expect(onModelChange).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
  })
})
