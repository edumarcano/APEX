import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { ToolCatalog, ModelCatalogEntry } from '../types/telemetry'

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

function localModel(overrides: Partial<ModelCatalogEntry> = {}): ModelCatalogEntry {
  return {
    model_id: 'gemma-4-E2B-Q4_K_M.gguf',
    display_name: 'Gemma 4 E2B',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'stable',
    hosted_capabilities: [],
    status: 'available',
    active: false,
    loading: false,
    ...overrides,
  }
}

function renderRail(overrides: Partial<ComponentProps<typeof HomeCommandRail>> = {}) {
  const toolCatalog: ToolCatalog = {
    agent: 'apex',
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
    isCortexQuerying: false,
    onAgentSubmit: vi.fn().mockResolvedValue(true),
    toolCatalog,
    selectedToolNames: [],
    activeToolProfileId: null,
    selectionReady: true,
    onStartApex: vi.fn(),
    onStartWithBriefing: vi.fn(),
    startDisabled: false,
    briefingMode: 'flash',
    onBriefingModeChange: vi.fn(),
    briefingControlsBusy: false,
    briefingModeAvailable: true,
    hasSnapshot: true,
    isRefreshingAll: false,
    onRefreshAll: vi.fn(),
    onGenerateBriefing: vi.fn(),
    onRefreshAllAndGenerate: vi.fn(),
    activeLocalModel: null,
    loadingLocalModel: null,
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
    expect(screen.getByRole('button', { name: /briefing mode: flash/i })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).toBeNull()
    expect(screen.queryByRole('button', { name: /generate briefing/i })).toBeNull()
  })

  it('uses a compact model selector menu without changing briefing selection', async () => {
    const onModelChange = vi.fn()
    const onBriefingModeChange = vi.fn()
    const user = userEvent.setup()
    renderRail({ onModelChange, onBriefingModeChange })

    const trigger = screen.getByRole('button', { name: /model: gpt-5\.6 luna/i })
    expect(trigger).toBeVisible()
    await user.click(trigger)
    const listbox = screen.getByRole('listbox', { name: /select model/i })
    expect(listbox).toBeVisible()
    expect(within(listbox).getByText('GPT-5.6 Luna')).toBeVisible()
    await user.click(within(listbox).getByRole('option', { name: /gemma 4 e2b/i }))

    expect(onModelChange).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
    expect(onBriefingModeChange).not.toHaveBeenCalled()
  })

  it('omits only the active assistant row when Agent queries are disabled', () => {
    renderRail({ agentQueriesEnabled: false })

    expect(screen.queryByLabelText('Agent query bar')).toBeNull()
    expect(screen.getByRole('button', { name: /briefing mode: flash/i })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Generate briefing from current telemetry' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).not.toBeInTheDocument()
  })

  it('submits with the selected model while keeping the composer free of a second selector', async () => {
    const onAgentSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderRail({ onAgentSubmit, selectedModelId: 'gpt-5.6-luna' })

    expect(screen.queryByLabelText('Active profile Apex Agent')).toBeNull()
    await user.type(screen.getByLabelText('Agent query'), 'Summarize my day')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onAgentSubmit).toHaveBeenCalledWith('Summarize my day', [], null)
  })

  it('submits when local model is selected', async () => {
    const onAgentSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderRail({ onAgentSubmit, selectedModelId: 'gemma-4-E2B-Q4_K_M.gguf' })

    await user.type(screen.getByLabelText('Agent query'), 'Check local status')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onAgentSubmit).toHaveBeenCalledWith('Check local status', [], null)
  })

  it('shows the resident local runtime beneath command rows and keeps its unload action separate from synthesis', async () => {
    const onUnloadLocalModel = vi.fn(async () => true)
    const activeLocalModel = localModel({ active: true })
    const user = userEvent.setup()
    renderRail({ activeLocalModel, selectedModelId: 'gemma-4-E2B-Q4_K_M.gguf', onUnloadLocalModel })

    expect(document.querySelector('[data-slot="home-agent-row"]')).toBeVisible()
    expect(document.querySelector('[data-slot="home-briefing-row"]')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).not.toBeInTheDocument()
    const actions = document.querySelector<HTMLElement>('[data-slot="home-briefing-actions"]')
    const runtime = document.querySelector<HTMLElement>('[data-slot="home-local-runtime"]')
    expect(runtime).toHaveTextContent('gemma-4-E2B-Q4_K_M.gguf · llama.cpp · Loaded')
    expect(actions).not.toContainElement(runtime)
    await user.click(screen.getByRole('button', { name: 'Unload gemma-4-E2B-Q4_K_M.gguf' }))
    expect(onUnloadLocalModel).toHaveBeenCalledTimes(1)
  })

  it('includes active local model in the local runtime strip', () => {
    const activeLocalModel = {
      ...localModel(),
      active: true,
      loaded_model: {
        provider: 'llama_cpp' as const,
        name: 'gemma-4-e2b-local',
        model: 'gemma-4-e2b-local',
        state: 'loaded' as const,
        context_window: 16384,
        size_bytes: null,
        size_vram_bytes: null,
        processor: null,
        context: null,
        expires_at: null,
      },
    }
    renderRail({ activeLocalModel })

    expect(screen.getByText('gemma-4-e2b-local · llama.cpp · Loaded')).toBeVisible()
  })

  it('keeps the local runtime strip visible and disables unloading while a model is loading', () => {
    renderRail({ activeLocalModel: null, loadingLocalModel: localModel({ loading: true }), selectedModelId: 'gemma-4-E2B-Q4_K_M.gguf' })

    expect(screen.getByText('gemma-4-E2B-Q4_K_M.gguf · llama.cpp · Loading')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Unload gemma-4-E2B-Q4_K_M.gguf' })).toBeDisabled()
  })

  it('renders local model control during standby below briefing mode selector when a model is active', async () => {
    const onUnloadLocalModel = vi.fn(async () => true)
    const activeLocalModel = {
      ...localModel(),
      active: true,
      loaded_model: {
        provider: 'llama_cpp' as const,
        name: 'gemma-4-E2B-Q4_K_M.gguf',
        model: 'gemma-4-E2B-Q4_K_M.gguf',
        state: 'loaded' as const,
        context_window: 16384,
        size_bytes: null,
        size_vram_bytes: null,
        processor: null,
        context: null,
        expires_at: null,
      },
    }
    const user = userEvent.setup()
    renderRail({ activated: false, activeLocalModel, onUnloadLocalModel })

    expect(document.querySelector('[data-slot="home-standby-controls"]')).toBeVisible()
    const runtime = document.querySelector<HTMLElement>('[data-slot="home-local-runtime"]')
    expect(runtime).toBeVisible()
    expect(runtime).toHaveTextContent('gemma-4-E2B-Q4_K_M.gguf · llama.cpp · Loaded')
    await user.click(screen.getByRole('button', { name: 'Unload gemma-4-E2B-Q4_K_M.gguf' }))
    expect(onUnloadLocalModel).toHaveBeenCalledTimes(1)
  })

  it('renders active command panel with 42rem max width and distinct query/briefing rows', () => {
    renderRail()

    const rail = screen.getByLabelText('Home command rail')
    expect(rail).toHaveClass('max-w-[42rem]')
    expect(document.querySelector('[data-slot="home-agent-row"]')).toBeVisible()
    expect(document.querySelector('[data-slot="home-briefing-row"]')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Generate briefing from current telemetry' })).toBeVisible()
  })
})
