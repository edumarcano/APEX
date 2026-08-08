import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, AgentKey, ToolCatalog } from '../types/telemetry'

import { HomeCommandRail } from './HomeCommandRail'

function profile(key: AgentKey, status: AgentStatus['status'] = 'available'): AgentStatus {
  const local = key === 'mus' || key === 'sorex' || key === 'apodemus' || key === 'neotoma'
  return {
    key,
    display_name: `Apex ${key.slice(0, 1).toUpperCase()}${key.slice(1)}`,
    description: `${key} profile.`,
    configured_model:
      key === 'apodemus' ? 'gemma-4-E2B-Q4_K_M.gguf' : key === 'neotoma' ? 'Qwen3.5-4B-Q4_K_M.gguf' : local ? 'qwen3:4b-instruct' : 'gpt-5.6-luna',
    sort_order: key === 'panthera' ? 1 : 2,
    capabilities: [],
    native_tools: {},
    provider: key === 'apodemus' || key === 'neotoma' ? 'llama_cpp' : local ? 'ollama' : 'openai',
    version: '7.4',
    runtime: local ? 'local' : 'cloud',
    tier: 'stable',
    stability: key === 'apodemus' || key === 'neotoma' ? 'preview' : 'stable',
    effort_options: local ? null : ['light', 'focused', 'extended'],
    default_effort: local ? null : 'focused',
    context_window: key === 'apodemus' ? 16384 : key === 'neotoma' ? 16384 : null,
    context_window_options: key === 'apodemus' ? [4096, 16384, 32768, 131072] : key === 'neotoma' ? [4096, 16384, 32768, 65536] : null,
    context_window_high_resource_options: key === 'apodemus' ? [131072] : key === 'neotoma' ? [65536] : null,
    default_context_window: key === 'apodemus' ? 16384 : key === 'neotoma' ? 16384 : null,
    reasoning_mode: key === 'apodemus' || key === 'neotoma' ? 'none' : local ? 'none' : null,
    reasoning_mode_options: key === 'apodemus' || key === 'neotoma' ? ['none', 'focused'] : local ? ['none'] : null,
    default_reasoning_mode: key === 'apodemus' || key === 'neotoma' ? 'none' : local ? 'none' : null,
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
    askApexEnabled: true,
    activeAgent: 'panthera',
    agentsStatus: [profile('panthera'), profile('mus'), profile('sorex'), profile('apodemus')],
    agentsStatusHydrated: true,
    isCortexQuerying: false,
    verifyingCloudAgent: null,
    onAgentChange: vi.fn(),
    onVerifyCloudAgent: vi.fn(async () => true),
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
    expect(screen.getByRole('button', { name: /briefing: panthera/i })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).toBeNull()
    expect(screen.queryByRole('button', { name: /synthesize briefing/i })).toBeNull()
    expect(document.querySelector('[data-slot="home-standby-controls"]')).toHaveClass('grid')
    expect(document.querySelector('[data-slot="home-standby-actions"]')).toHaveClass('col-span-2')
  })

  it('uses a compact assistant menu without changing briefing selection', async () => {
    const onAgentChange = vi.fn()
    const onBriefingModeChange = vi.fn()
    const user = userEvent.setup()
    renderRail({ onAgentChange, onBriefingModeChange })

    const trigger = screen.getByRole('button', { name: /panthera.*available/i })
    expect(trigger).not.toHaveClass('bg-[#7E22CE]/10')
    expect(trigger).toHaveClass('border-white/10')
    expect(document.querySelector('[data-slot="home-agent-status-dot"]')).toHaveAttribute('data-status', 'available')
    await user.click(trigger)
    expect(screen.getByText('Agent')).toBeVisible()
    const selector = screen.getByRole('dialog', { name: 'Select Agent' })
    expect(selector).toHaveAttribute('id', 'home-agent-popover')
    expect(selector.style.bottom).not.toBe('')
    expect(selector.style.top).toBe('')
    expect(screen.queryByText(/powered by/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /verify access/i })).toBeNull()
    await user.click(within(screen.getByRole('listbox', { name: 'Local Agents' })).getByRole('option', { name: 'Use Apex Mus' }))

    expect(onAgentChange).toHaveBeenCalledWith('mus')
    expect(onBriefingModeChange).not.toHaveBeenCalled()
  })

  it('uses the canonical Apex red for unavailable Agents', () => {
    renderRail({ agentsStatus: [profile('panthera', 'model_unavailable')] })

    const statusDot = document.querySelector('[data-slot="home-agent-status-dot"]')
    expect(statusDot).toHaveClass('bg-[#DC2626]')
    expect(statusDot).toHaveClass('shadow-[0_0_7px_rgba(220,38,38,0.8)]')
  })

  it('omits only the active assistant row when Ask Apex is disabled', () => {
    renderRail({ askApexEnabled: false })

    expect(screen.queryByLabelText('Ask APEX')).toBeNull()
    expect(screen.getByRole('button', { name: /briefing: panthera/i })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Synthesize briefing from current telemetry' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).not.toBeInTheDocument()
  })

  it('submits with the active Agent while keeping the composer free of a second selector', async () => {
    const onAgentSubmit = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    renderRail({ onAgentSubmit })

    expect(screen.queryByLabelText('Active profile Panthera')).toBeNull()
    await user.type(screen.getByLabelText('Ask APEX query'), 'Summarize my day')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onAgentSubmit).toHaveBeenCalledWith('Summarize my day', 'panthera', [], null)
  })

  it('shows the resident local runtime beneath command rows and keeps its unload action separate from synthesis', async () => {
    const onUnloadLocalModel = vi.fn(async () => true)
    const activeMus = { ...profile('mus'), active: true, display_name: 'Apex Mus' }
    const user = userEvent.setup()
    renderRail({ activeLocalModel: activeMus, onUnloadLocalModel })

    expect(document.querySelector('[data-slot="home-active-controls"]')).toHaveClass('home-command-grid--with-agent')
    expect(document.querySelector('[data-slot="home-agent-row"]')).toBeVisible()
    expect(document.querySelector('[data-slot="home-briefing-row"]')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).not.toBeInTheDocument()
    const actions = document.querySelector<HTMLElement>('[data-slot="home-briefing-actions"]')
    const runtime = document.querySelector<HTMLElement>('[data-slot="home-local-runtime"]')
    expect(runtime).toHaveTextContent('Mus · Ollama · Loaded')
    expect(actions).not.toContainElement(runtime)
    expect(actions).toContainElement(document.querySelector('.home-command-grid__synthesize'))
    await user.click(screen.getByRole('button', { name: 'Unload Apex Mus' }))
    expect(onUnloadLocalModel).toHaveBeenCalledTimes(1)
  })

  it('includes known Apodemus context in the local runtime strip', () => {
    const activeApodemus = {
      ...profile('apodemus'),
      active: true,
      display_name: 'Apex Apodemus',
      loaded_model: {
        provider: 'llama_cpp' as const,
        name: 'apodemus-16k',
        model: 'apodemus-16k',
        state: 'loaded' as const,
        context_window: 16384,
        size_bytes: null,
        size_vram_bytes: null,
        processor: null,
        context: null,
        expires_at: null,
      },
    }
    renderRail({ activeLocalModel: activeApodemus })

    expect(screen.getByText('Apodemus · llama.cpp · 16K · Loaded')).toBeVisible()
  })

  it('keeps the local runtime strip visible and disables unloading while a model is loading', () => {
    renderRail({ activeLocalModel: null, loadingLocalAgent: profile('mus') })

    expect(screen.getByText('Mus · Ollama · Loading')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Unload Apex Mus' })).toBeDisabled()
  })
})
