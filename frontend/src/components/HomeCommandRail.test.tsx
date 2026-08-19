import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, AgentKey, ToolCatalog, ModelCatalogEntry } from '../types/telemetry'

import { HomeCommandRail } from './HomeCommandRail'

const mockCatalog: ModelCatalogEntry[] = [
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

function profile(key: AgentKey, status: AgentStatus['status'] = 'available'): AgentStatus {
  const local = key === 'felis'
  return {
    key,
    display_name: key === 'panthera' ? 'Apex Panthera' : 'Apex Felis',
    description: `${key} profile.`,
    configured_model: local ? 'gemma-4-E2B-Q4_K_M.gguf' : 'gpt-5.6-luna',
    sort_order: key === 'panthera' ? 1 : 2,
    capabilities: [],
    native_tools: {},
    provider: local ? 'llama_cpp' : 'openai',
    runtime: local ? 'local' : 'cloud',
    model_stability: 'stable',
    reasoning_options: local ? null : ['none', 'minimal', 'low', 'medium', 'high', 'xhigh'],
    default_reasoning: local ? null : 'medium',
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

function renderRail(overrides: Partial<ComponentProps<typeof HomeCommandRail>> = {}) {
  const toolCatalog: ToolCatalog = {
    agent: 'panthera',
    groups: [],
    tools: [],
    profiles: [],
    default_profile_id: 'no_tools',
    default_profile_name: 'No APEX Tools',
    default_selected_tool_names: [],
    provider_hosted_tools: [],
    context_window: null,
    reserved_response_tokens: null,
  }
  const props: ComponentProps<typeof HomeCommandRail> = {
    activated: true,
    agentQueriesEnabled: true,
    selectedModelId: 'gpt-5.6-luna',
    onModelChange: vi.fn(),
    modelCatalog: mockCatalog,
    agentsStatus: [profile('panthera'), profile('felis')],
    isCortexQuerying: false,
    onAgentSubmit: vi.fn().mockResolvedValue(true),
    toolCatalog,
    selectedToolNames: [],
    activeToolProfileId: null,
    selectionReady: true,
    onStartApex: vi.fn(),
    onStartWithBriefing: vi.fn(),
    startDisabled: false,
    briefingMode: 'panthera',
    onBriefingModeChange: vi.fn(),
    briefingControlsBusy: false,
    briefingModeAvailable: true,
    hasSnapshot: true,
    isRefreshingAll: false,
    onRefreshAll: vi.fn(),
    onGenerateBriefing: vi.fn(),
    onRefreshAllAndGenerate: vi.fn(),
    activeLocalModel: null,
    loadingLocalAgent: null,
    localLifecycleBusy: false,
    onUnloadLocalModel: vi.fn(async () => true),
    ...overrides,
  }
  return { props, ...render(<HomeCommandRail {...props} />) }
}

describe('HomeCommandRail', () => {
  it('keeps standby activation actions with briefing selection while hiding active-only controls', () => {
    renderRail({ activated: false })

    expect(screen.getByRole('button', { name: 'Start APEX' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Start APEX with briefing' })).toBeVisible()
    expect(screen.getByRole('button', { name: /briefing mode: full briefing/i })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).toBeNull()
    expect(screen.queryByRole('button', { name: /synthesize briefing/i })).toBeNull()
  })

  it('uses a compact model selector menu without changing briefing selection', async () => {
    const onModelChange = vi.fn()
    const onBriefingModeChange = vi.fn()
    const user = userEvent.setup()
    renderRail({ onModelChange, onBriefingModeChange })

    const trigger = screen.getByRole('button', { name: /model: gpt-5\.6 luna/i })
    expect(screen.getByText('GPT-5.6 Luna')).toBeVisible()
    expect(screen.getByText(/Panthera · OpenAI · Reasoning off/i)).toBeVisible()
    await user.click(trigger)
    const listbox = screen.getByRole('listbox', { name: /select model/i })
    expect(listbox).toBeVisible()
    await user.click(within(listbox).getByRole('option', { name: /gemma 4 e2b/i }))

    expect(onModelChange).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
    expect(onBriefingModeChange).not.toHaveBeenCalled()
  })

  it('omits only the active assistant row when Agent queries are disabled', () => {
    renderRail({ agentQueriesEnabled: false })

    expect(screen.queryByLabelText('Agent query bar')).toBeNull()
    expect(screen.getByRole('button', { name: /briefing mode: full briefing/i })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Synthesize briefing from current telemetry' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).not.toBeInTheDocument()
  })

  it('submits with the inferred Agent while keeping the composer free of a second selector', async () => {
    const onAgentSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderRail({ onAgentSubmit, selectedModelId: 'gpt-5.6-luna' })

    expect(screen.queryByLabelText('Active profile Panthera')).toBeNull()
    await user.type(screen.getByLabelText('Agent query'), 'Summarize my day')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onAgentSubmit).toHaveBeenCalledWith('Summarize my day', 'panthera', [], null)
  })

  it('submits with Felis when local model is selected', async () => {
    const onAgentSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderRail({ onAgentSubmit, selectedModelId: 'gemma-4-E2B-Q4_K_M.gguf' })

    await user.type(screen.getByLabelText('Agent query'), 'Check local status')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onAgentSubmit).toHaveBeenCalledWith('Check local status', 'felis', [], null)
  })

  it('shows the resident local runtime beneath command rows and keeps its unload action separate from synthesis', async () => {
    const onUnloadLocalModel = vi.fn(async () => true)
    const activeFelis = { ...profile('felis'), active: true, display_name: 'Apex Felis' }
    const user = userEvent.setup()
    renderRail({ activeLocalModel: activeFelis, onUnloadLocalModel })

    expect(document.querySelector('[data-slot="home-agent-row"]')).toBeVisible()
    expect(document.querySelector('[data-slot="home-briefing-row"]')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).not.toBeInTheDocument()
    const actions = document.querySelector<HTMLElement>('[data-slot="home-briefing-actions"]')
    const runtime = document.querySelector<HTMLElement>('[data-slot="home-local-runtime"]')
    expect(runtime).toHaveTextContent('Felis · llama.cpp · Loaded')
    expect(actions).not.toContainElement(runtime)
    await user.click(screen.getByRole('button', { name: 'Unload Apex Felis' }))
    expect(onUnloadLocalModel).toHaveBeenCalledTimes(1)
  })

  it('includes known Felis context in the local runtime strip', () => {
    const activeFelis = {
      ...profile('felis'),
      active: true,
      display_name: 'Apex Felis',
      loaded_model: {
        provider: 'llama_cpp' as const,
        name: 'felis-16k',
        model: 'felis-16k',
        state: 'loaded' as const,
        context_window: 16384,
        size_bytes: null,
        size_vram_bytes: null,
        processor: null,
        context: null,
        expires_at: null,
      },
    }
    renderRail({ activeLocalModel: activeFelis })

    expect(screen.getByText('Felis · llama.cpp · 16K · Loaded')).toBeVisible()
  })

  it('keeps the local runtime strip visible and disables unloading while a model is loading', () => {
    renderRail({ activeLocalModel: null, loadingLocalAgent: profile('felis') })

    expect(screen.getByText('Felis · llama.cpp · Loading')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Unload Apex Felis' })).toBeDisabled()
  })
})
