import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApexAssistantRuntime } from '../ApexAssistantRuntime'
import type { BriefingProfilePanelProps } from './BriefingProfilePanel'
import { BriefingView, type BriefingViewConversation } from './BriefingView'
import type { HudIdentityProps } from '../overview/HudIdentity'
import type { HudTelemetryData } from '../overview/HudTelemetry'
import type { BriefingSessionDetail } from '../../types/briefings'

vi.mock('../../hooks/useCompactLayout', () => ({ useCompactLayout: () => false }))
vi.mock('../overview/HudIdentity', () => ({ HudIdentityMark: () => null }))
vi.mock('../overview/HudTelemetryRail', () => ({ HudTelemetryRail: () => null }))
vi.mock('./BriefingProfilePanel', () => ({ BriefingProfilePanel: () => null }))

const conversationId = '00000000-0000-4000-8000-000000000211'
const conversationSummary = {
  id: conversationId,
  title: 'Saved briefing conversation',
  archived_at: null,
  agent: 'apex' as const,
  selected_tool_names: [],
  tool_profile_id: null,
  updated_at: '2026-09-27T10:00:00Z',
}

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.restoreAllMocks())

describe('BriefingView', () => {
  it('passes shared model and tool controls into a ready saved conversation composer', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/cortex/conversations?archived=true')) return response([])
      if (url.endsWith('/api/v1/cortex/conversations')) return response([conversationSummary])
      if (url.endsWith(`/api/v1/cortex/conversations/${conversationId}`)) {
        return response({ ...conversationSummary, active_leaf_message_id: null, messages: [] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const conversation: BriefingViewConversation = {
      ready: true,
      canFollowUp: true,
      session: {
        id: '00000000-0000-4000-8000-000000000212',
        conversation_id: conversationId,
        opening_message_id: '00000000-0000-4000-8000-000000000213',
        run_id: 'saved-run',
        run_status: 'completed',
        run_error_code: null,
        configuration: {
          profile: { id: 'daily', label: 'Daily', purpose: 'Current information.', definition_version: 1 },
          model: { model_id: 'provider/model-a', provider: 'openrouter', runtime: 'cloud', reasoning: 'medium', context_window: null, local_reasoning_mode: null },
          origin: 'hud',
          execution_kind: 'model',
        },
        artifact: null,
        evidence_count: 0,
        evidence_ids: [],
        created_at: '2026-09-27T10:00:00Z',
        presented_at: null,
        speech_status: 'not_requested',
      } as BriefingSessionDetail,
      isLoadingSession: false,
      evidence: {} as BriefingViewConversation['evidence'],
      onMarkPresented: async () => undefined,
      onOpenConversation: vi.fn(),
      composer: {
        activeAgent: 'apex',
        activeAgentName: 'Apex Agent',
        integrated: true,
        selectedModelId: 'provider/model-a',
        onModelChange: vi.fn(),
        modelCatalog: [{ model_id: 'provider/model-a', display_name: 'Model A', provider: 'openrouter', runtime: 'cloud', stability: 'stable', reasoning_options: ['low', 'medium', 'high'], default_reasoning: 'medium', hosted_capabilities: [] }],
        cloudEffort: 'medium',
        onEffortChange: vi.fn(),
        tools: {
          catalog: null,
          selectedToolNames: [],
          activeToolProfileId: null,
          onSelectionChange: vi.fn(),
          onProfileChange: vi.fn(),
        },
      },
    }

    render(<ApexAssistantRuntime config={{ agent: 'apex', effort: 'medium', selectedToolNames: [], toolProfileId: null, snapshotId: null }}>
      <BriefingView
        phase="workspace"
        identity={{} as HudIdentityProps}
        telemetry={{} as HudTelemetryData}
        controls={{} as BriefingProfilePanelProps}
        conversation={conversation}
        telemetryCollection={{ hasUsableSnapshot: false, state: 'idle', error: null, disabled: false, onCollect: vi.fn() }}
      />
    </ApexAssistantRuntime>)

    const query = await screen.findByPlaceholderText('Add a follow up')
    const shell = query.closest('[data-slot="briefing-query-composer"]')
    expect(shell).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Tools:/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Model: Model A, reasoning Medium/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })
})
