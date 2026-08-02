import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentProfileStatus, AssistantProfile } from '../types/telemetry'

import { OverviewCommandRail } from './OverviewCommandRail'

function profile(key: AssistantProfile, status: AgentProfileStatus['status'] = 'available'): AgentProfileStatus {
  const local = key === 'mus' || key === 'sorex'
  return {
    key,
    display_name: `APEX ${key.slice(0, 1).toUpperCase()}${key.slice(1)}`,
    description: `${key} profile.`,
    configured_model: local ? 'qwen3:4b-instruct' : 'gpt-5.6-luna',
    sort_order: key === 'panthera' ? 1 : 2,
    capabilities: [],
    native_tools: {},
    provider: local ? 'ollama' : 'openai',
    version: '2.0',
    mode: local ? 'local' : 'cloud',
    tier: 'stable',
    stability: 'stable',
    effort_options: local ? null : ['light', 'focused', 'extended'],
    default_effort: local ? null : 'focused',
    status,
    status_source: local ? 'runtime' : 'configuration',
    status_checked_at: null,
    provider_account_tier: null,
    pricing: {
      currency: 'USD', pricing_version: 'test', billing_basis: local ? 'local' : 'standard',
      input_per_million: local ? 0 : 1, output_per_million: local ? 0 : 6,
      cached_input_per_million: null, long_context_threshold_tokens: null,
      long_context_input_per_million: null, long_context_output_per_million: null,
      long_context_cached_input_per_million: null,
    },
    active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
  }
}

function renderRail(overrides: Partial<ComponentProps<typeof OverviewCommandRail>> = {}) {
  const props: ComponentProps<typeof OverviewCommandRail> = {
    activated: true,
    askApexEnabled: true,
    activeProfile: 'panthera',
    profilesStatus: [profile('panthera'), profile('mus'), profile('sorex')],
    profilesStatusHydrated: true,
    devModeActive: false,
    isAssistantQuerying: false,
    verifyingCloudProfile: null,
    onProfileChange: vi.fn(),
    onVerifyCloudProfile: vi.fn(async () => true),
    onAssistantSubmit: vi.fn(),
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
    ...overrides,
  }
  return { props, ...render(<OverviewCommandRail {...props} />) }
}

describe('OverviewCommandRail', () => {
  it('keeps standby activation actions with briefing selection while hiding active-only controls', () => {
    renderRail({ activated: false })

    expect(screen.getByRole('button', { name: 'Start APEX' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Start APEX with briefing' })).toBeVisible()
    expect(screen.getByRole('button', { name: /briefing: panthera/i })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Refresh all telemetry' })).toBeNull()
    expect(screen.queryByRole('button', { name: /synthesize briefing/i })).toBeNull()
  })

  it('uses a compact assistant menu without changing briefing selection', async () => {
    const onProfileChange = vi.fn()
    const onBriefingModeChange = vi.fn()
    const user = userEvent.setup()
    renderRail({ onProfileChange, onBriefingModeChange })

    await user.click(screen.getByRole('button', { name: /panthera.*available/i }))
    expect(screen.getByText('Assistant profile')).toBeVisible()
    const selector = screen.getByRole('dialog', { name: 'Select assistant profile' })
    expect(selector).toHaveAttribute('id', 'overview-profile-popover')
    expect(selector.style.bottom).not.toBe('')
    expect(selector.style.top).toBe('')
    expect(screen.queryByText(/powered by/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /verify access/i })).toBeNull()
    await user.click(within(screen.getByRole('listbox', { name: 'Local assistant profiles' })).getByRole('option', { name: 'Use APEX Mus' }))

    expect(onProfileChange).toHaveBeenCalledWith('mus')
    expect(onBriefingModeChange).not.toHaveBeenCalled()
  })

  it('omits only the active assistant row when Ask APEX is disabled', () => {
    renderRail({ askApexEnabled: false })

    expect(screen.queryByLabelText('Ask APEX')).toBeNull()
    expect(screen.getByRole('button', { name: /briefing: panthera/i })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Refresh all telemetry' })).toBeVisible()
  })

  it('submits with the active assistant profile while keeping the composer free of a second selector', async () => {
    const onAssistantSubmit = vi.fn()
    const user = userEvent.setup()
    renderRail({ onAssistantSubmit })

    expect(screen.queryByLabelText('Active profile Panthera')).toBeNull()
    await user.type(screen.getByLabelText('Ask APEX query'), 'Summarize my day')
    await user.click(screen.getByRole('button', { name: 'Send query' }))

    expect(onAssistantSubmit).toHaveBeenCalledWith('Summarize my day', 'panthera', null)
  })
})
