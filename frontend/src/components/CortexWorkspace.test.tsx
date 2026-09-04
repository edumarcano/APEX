import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApexAssistantRuntime } from './ApexAssistantRuntime'
import { CortexWorkspace, ResponseMetrics } from './CortexWorkspace'
import type { AgentQueryMetadata } from '../lib/cortexResponse'
import type { AgentStatus, ModelCatalogEntry, ToolCatalog } from '../types/telemetry'

const cloudModel: ModelCatalogEntry = { model_id: 'deepseek/deepseek-v4-flash-0731', display_name: 'DeepSeek V4 Flash', provider: 'openrouter', runtime: 'cloud', stability: 'stable', hosted_capabilities: [], status: 'configured', reasoning_options: ['none', 'low', 'high'], default_reasoning: 'low' }
const localModel: ModelCatalogEntry = { model_id: 'gemma-4-E2B-Q4_K_M.gguf', display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', stability: 'stable', hosted_capabilities: [], status: 'available', context_options: [4096, 16384], default_context_window: 16384, reasoning_modes: ['none', 'focused'], default_reasoning_mode: 'none', active: false, loading: false }
const apex: AgentStatus = { key: 'apex', display_name: 'Apex Agent', description: 'Native assistant.', configured_model: cloudModel.model_id, sort_order: 0, capabilities: [], native_tools: {}, provider: 'openrouter', runtime: 'cloud', model_stability: 'stable', reasoning_options: ['none', 'low', 'high'], default_reasoning: 'low', context_window: null, context_window_options: null, context_window_high_resource_options: null, default_context_window: null, reasoning_mode: null, reasoning_mode_options: null, default_reasoning_mode: null, status: 'configured', status_source: 'configuration', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0, output_per_million: 0, cached_input_per_million: null, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null, model_catalog: [cloudModel, localModel] }
const toolCatalog: ToolCatalog = { agent: 'apex', groups: [], tools: [], profiles: [], default_profile_id: 'no_tools', default_profile_name: 'No APEX Tools', default_selected_tool_names: [], provider_hosted_tools: [], context_window: 4096, reserved_response_tokens: 512 }

function props(overrides: Partial<ComponentProps<typeof CortexWorkspace>> = {}): ComponentProps<typeof CortexWorkspace> {
  return { activeAgent: 'apex', cloudEffort: 'low', selectedModel: cloudModel.model_id, localContextWindow: 16384, localReasoningMode: 'none', hostedTools: { google_search: true, google_maps: true }, devModeActive: false, sandboxMode: false, agentQueriesEnabled: true, agentsStatus: [apex], agentsStatusHydrated: true, latestTrace: [], error: null, contextUsage: null, toolCatalog, selectedToolNames: [], activeToolProfileId: null, selectionReady: true, isQuerying: false, logoProps: { step: null, status: 'idle' }, lifecycleBusy: false, lifecycleActionPending: false, onLoadLocalModel: vi.fn().mockResolvedValue(true), onUnloadLocalModel: vi.fn().mockResolvedValue(true), onVerifyCloudAgent: vi.fn().mockResolvedValue(true), snapshotAttached: true, snapshotAvailable: true, onSnapshotAttachedChange: vi.fn(), onModelChange: vi.fn(), onEffortChange: vi.fn(), onHostedToolChange: vi.fn(), onSandboxModeChange: vi.fn(), onLocalContextWindowChange: vi.fn().mockResolvedValue(true), onLocalReasoningModeChange: vi.fn().mockResolvedValue(true), actions: { actions: [], pendingCount: 0, isLoading: false, error: null, selectedActionId: null, detail: null, isDetailLoading: false, mutation: null, setSelectedActionId: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), resolve: vi.fn().mockResolvedValue(undefined) }, demoModeActive: false, assistantRunConfig: { agent: 'apex', effort: 'low', selectedToolNames: [], toolProfileId: null, snapshotId: null }, ...overrides }
}
function renderWorkspace(overrides: Partial<ComponentProps<typeof CortexWorkspace>> = {}) { const value = props(overrides); return render(<ApexAssistantRuntime config={value.assistantRunConfig}><CortexWorkspace {...value} /></ApexAssistantRuntime>) }

describe('CortexWorkspace', () => {
  beforeEach(() => vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify([]), { status: 200 })))
  afterEach(() => vi.restoreAllMocks())

  it('identifies the singular Apex Agent and groups its selectable models', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    expect(screen.getAllByText('Apex Agent').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: 'Model' }))
    const picker = screen.getByRole('listbox', { name: 'Select Apex Agent model' })
    expect(within(picker).getByRole('group', { name: 'Cloud models' })).toBeVisible()
    expect(within(picker).getByRole('group', { name: 'Local models' })).toBeVisible()
  })

  it('routes verification and model selection by model id', async () => {
    const onModelChange = vi.fn()
    const onVerifyCloudAgent = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderWorkspace({ onModelChange, onVerifyCloudAgent })
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(onVerifyCloudAgent).toHaveBeenCalledWith(cloudModel.model_id)
    await user.click(screen.getByRole('button', { name: 'Model' }))
    await user.click(screen.getByRole('option', { name: /Gemma 4 E2B/i }))
    expect(onModelChange).toHaveBeenCalledWith(localModel.model_id)
  })

  it('shows local controls from the selected model rather than a second Agent', () => {
    renderWorkspace({ selectedModel: localModel.model_id, localContextWindow: 4096, localReasoningMode: 'focused' })
    expect(screen.getByRole('region', { name: 'Apex Agent reasoning' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Apex Agent context window' })).toBeVisible()
    expect(screen.getByLabelText('Reasoning')).toHaveValue('focused')
    expect(screen.getByLabelText('Context window')).toHaveValue('4096')
  })

  it('discloses model/provider response evidence', async () => {
    const metadata: AgentQueryMetadata = { agent: { key: 'apex', version: null, provider: 'openrouter', configuredModel: cloudModel.model_id, resolvedModel: cloudModel.model_id, requestedEffort: 'low', resolvedEffort: 'low' }, usage: { inputTokens: 1, cachedInputTokens: null, reasoningTokens: null, outputTokens: 1, totalTokens: 2 }, timing: { totalMs: 10, providerMs: 8, apexToolMs: 0 }, cost: { tokenCost: 0, hostedToolCost: 0, totalCost: 0, currency: 'USD', pricingVersion: 'test', completeness: 'complete' }, citations: [], grounding: null, toolSelection: null }
    const user = userEvent.setup()
    render(<ResponseMetrics metadata={metadata} />)
    await user.click(screen.getByText('Response information'))
    expect(screen.getByText('OpenRouter / apex')).toBeVisible()
  })

  it('supports 4-tab keyboard navigation across controls, context, actions, and activity', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    const controlsTab = screen.getByRole('tab', { name: 'controls' })
    const contextTab = screen.getByRole('tab', { name: 'context' })
    const actionsTab = screen.getByRole('tab', { name: 'actions' })
    const activityTab = screen.getByRole('tab', { name: 'activity' })

    expect(controlsTab).toHaveAttribute('aria-selected', 'true')

    await user.click(controlsTab)
    await user.keyboard('{ArrowRight}')
    expect(contextTab).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{ArrowRight}')
    expect(actionsTab).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{ArrowRight}')
    expect(activityTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('cortex-activity-panel')).toBeInTheDocument()

    // Wrap around to first tab
    await user.keyboard('{ArrowRight}')
    expect(controlsTab).toHaveAttribute('aria-selected', 'true')

    // ArrowLeft backwards
    await user.keyboard('{ArrowLeft}')
    expect(activityTab).toHaveAttribute('aria-selected', 'true')

    // Home and End keys
    await user.keyboard('{Home}')
    expect(controlsTab).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{End}')
    expect(activityTab).toHaveAttribute('aria-selected', 'true')
  })
})
