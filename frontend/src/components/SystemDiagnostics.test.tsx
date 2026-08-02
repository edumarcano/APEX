import { render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_SYSTEM_DIAGNOSTICS, type AgentProfileStatus } from '../types/telemetry'
import { SystemDiagnostics } from './SystemDiagnostics'

const panthera: AgentProfileStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.',
  configured_model: 'gpt-5.6-luna', sort_order: 1, capabilities: [], native_tools: {}, provider: 'openai', version: '2.0',
  mode: 'cloud', tier: 'balanced', stability: 'stable', effort_options: ['light', 'focused', 'extended'],
  default_effort: 'focused', status: 'configured', status_source: 'configuration', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 1, output_per_million: 6, cached_input_per_million: 0.1, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, active: false, loading: false, reason: null,
  idle_unload_remaining_seconds: null, loaded_model: null,
}

function renderDiagnostics(overrides: Partial<ComponentProps<typeof SystemDiagnostics>> = {}) {
  return render(
    <SystemDiagnostics
      diagnostics={DEFAULT_SYSTEM_DIAGNOSTICS}
      diagnosticsStatus="ready"
      status="idle"
      confidenceScore={0}
      briefingMode="panthera"
      onBriefingModeChange={vi.fn()}
      profilesStatus={[panthera]}
      profilesStatusHydrated
      briefingControlsBusy={false}
      {...overrides}
    />,
  )
}

describe('SystemDiagnostics', () => {
  it('keeps workspace controls visually grouped with, but semantically outside, the sync-health trigger', () => {
    renderDiagnostics({
      workspaceNavigation: <nav aria-label="Workspace"><button type="button">Overview</button><button type="button">Cortex</button></nav>,
    })

    const workspace = screen.getByRole('navigation', { name: 'Workspace' })
    expect(workspace).toBeInTheDocument()
    expect(workspace.closest('[role="button"]')).toBeNull()
    expect(screen.getByRole('button', { name: 'APEX sync health' })).toBeInTheDocument()
  })
})
