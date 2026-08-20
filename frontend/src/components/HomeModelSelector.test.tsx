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
    stability: 'preview',
    reasoning_options: ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'],
    default_reasoning: 'medium',
    hosted_capabilities: [],
  },
  {
    model_id: 'gemma-4-E2B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E2B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'experimental',
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
  it('renders compact icon trigger and exposes full Panthera metadata in dropdown', async () => {
    const user = userEvent.setup()
    render(
      <HomeModelSelector
        selectedModelId="deepseek/deepseek-v4-flash-0731"
        onModelChange={vi.fn()}
        catalog={mockCatalog}
        agentsStatus={mockAgentsStatus}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Model: DeepSeek V4 Flash' })
    expect(trigger).toBeInTheDocument()

    await user.click(trigger)
    const listbox = screen.getByRole('listbox', { name: /select model/i })
    expect(listbox).toBeInTheDocument()
    expect(within(listbox).getByText('DeepSeek V4 Flash')).toBeInTheDocument()
    expect(within(listbox).getByText(/Panthera · OpenRouter · Reasoning off/i)).toBeInTheDocument()
  })

  it('renders selected local model with experimental badge and full Felis metadata in dropdown', async () => {
    const user = userEvent.setup()
    render(
      <HomeModelSelector
        selectedModelId="gemma-4-E2B-Q4_K_M.gguf"
        onModelChange={vi.fn()}
        catalog={mockCatalog}
        agentsStatus={mockAgentsStatus}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Model: Gemma 4 E2B' })
    expect(trigger).toBeInTheDocument()

    await user.click(trigger)
    const listbox = screen.getByRole('listbox', { name: /select model/i })
    expect(listbox).toBeInTheDocument()
    expect(within(listbox).getByText('Gemma 4 E2B')).toBeInTheDocument()
    expect(within(listbox).getByText(/Felis · llama\.cpp · 16K context/i)).toBeInTheDocument()
    expect(within(listbox).getByText(/experimental/i)).toBeInTheDocument()
    expect(within(listbox).getByText(/preview/i)).toBeInTheDocument()
  })

  it('opens popover grouped by Cloud (Apex Panthera) and Local (Apex Felis) and selects a model', async () => {
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

    await user.click(screen.getByRole('button', { name: /model: deepseek v4 flash/i }))
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(popover).toBeInTheDocument()

    expect(screen.getByText('Model Selection')).toBeVisible()
    expect(screen.getByText('Select an operational model for Home queries.')).toBeVisible()
    expect(within(popover).getByText(/Apex Panthera · Cloud/i)).toBeInTheDocument()
    expect(within(popover).getByText(/Apex Felis · Local/i)).toBeInTheDocument()

    await user.click(within(popover).getByRole('option', { name: /gemma 4 e2b/i }))
    expect(onModelChange).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
  })

  it('uses per-model credentials for cloud options and keeps local options selectable independently', async () => {
    const user = userEvent.setup()
    const customCatalog: ModelCatalogEntry[] = [
      {
        ...mockCatalog[0],
        credentials_configured: false,
      },
      {
        ...mockCatalog[1],
        credentials_configured: true,
      },
      {
        ...mockCatalog[2],
      },
    ]

    render(
      <HomeModelSelector
        selectedModelId="gpt-5.6-luna"
        onModelChange={vi.fn()}
        catalog={customCatalog}
        agentsStatus={[
          profile('panthera', 'configured', 'gpt-5.6-luna'),
          profile('felis', 'model_not_installed', 'other-model.gguf'),
        ]}
      />,
    )

    await user.click(screen.getByRole('button', { name: /model: gpt-5\.6 luna/i }))
    const popover = screen.getByRole('listbox', { name: /select model/i })

    // DeepSeek is missing key and disabled
    const deepseekOption = within(popover).getByRole('option', { name: /deepseek v4 flash/i })
    expect(deepseekOption).toBeDisabled()
    expect(within(popover).getByText(/Panthera · OpenRouter · Missing API key/i)).toBeInTheDocument()

    // Luna is configured and enabled
    const lunaOption = within(popover).getByRole('option', { name: /gpt-5\.6 luna/i })
    expect(lunaOption).not.toBeDisabled()

    // Gemma is local and disabled when Felis availability status is not ready (e.g., model_not_installed)
    const gemmaOption = within(popover).getByRole('option', { name: /gemma 4 e2b/i })
    expect(gemmaOption).toBeDisabled()
  })

  it('renders 4K context for Ollama models in dropdown descriptions', async () => {
    const user = userEvent.setup()
    const ollamaCatalog: ModelCatalogEntry[] = [
      {
        model_id: 'qwen3:1.7b',
        display_name: 'Qwen 3 1.7B',
        provider: 'ollama',
        runtime: 'local',
        stability: 'stable',
        hosted_capabilities: [],
      },
      ...mockCatalog,
    ]

    render(
      <HomeModelSelector
        selectedModelId="qwen3:1.7b"
        onModelChange={vi.fn()}
        catalog={ollamaCatalog}
        agentsStatus={mockAgentsStatus}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Model: Qwen 3 1.7B' })
    expect(trigger).toBeInTheDocument()

    await user.click(trigger)
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(within(popover).getByText('Qwen 3 1.7B')).toBeInTheDocument()
    expect(within(popover).getByText(/Felis · Ollama · 4K context/i)).toBeInTheDocument()
    expect(within(popover).getByText(/Felis · llama\.cpp · 16K context/i)).toBeInTheDocument()
  })
})
