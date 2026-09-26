import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ComponentProps, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { BriefingProfileId, BriefingProfileSummary, BriefingSessionDetail } from '../../types/briefings'
import type { ModelCatalogEntry } from '../../types/telemetry'
import { BriefingProfilePanel } from './BriefingProfilePanel'

const profiles: BriefingProfileSummary[] = [
  { id: 'daily', label: 'Daily', purpose: 'Current information.', investigation_required: false, available: true, unavailable_reason: null },
  { id: 'catch_up', label: 'Catch Up', purpose: 'What changed since a briefing was presented.', investigation_required: false, available: true, unavailable_reason: null },
  { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation across relevant current information and context.', investigation_required: true, available: true, unavailable_reason: null },
]

const catalog: ModelCatalogEntry[] = [
  { model_id: 'cloud-a', display_name: 'Cloud A', provider: 'openrouter', runtime: 'cloud', stability: 'stable', hosted_capabilities: [], status: 'available' },
  { model_id: 'cloud-b', display_name: 'Cloud B', provider: 'openrouter', runtime: 'cloud', stability: 'stable', hosted_capabilities: [], status: 'available' },
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

type PanelProps = ComponentProps<typeof BriefingProfilePanel>

function baseProps(overrides: Partial<PanelProps> = {}): PanelProps {
  return {
    profiles,
    profileId: 'daily',
    onProfileChange: vi.fn(),
    selectedModelId: 'cloud-a',
    modelCatalog: catalog,
    onModelChange: vi.fn(),
    canGenerate: true,
    busy: false,
    hasActiveSession: false,
    isGenerating: false,
    onGenerate: vi.fn(),
    onCancel: vi.fn(),
    sessions: [],
    selectedSessionId: null,
    isLoadingSessions: false,
    onOpenSession: vi.fn(),
    activeSession: null,
    error: null,
    activeLocalModel: null,
    loadingLocalModel: null,
    localLifecycleBusy: false,
    onUnloadLocalModel: vi.fn(async () => true),
    ...overrides,
  }
}

function failedSession(): BriefingSessionDetail {
  return {
    id: 'session-1',
    conversation_id: 'conversation-1',
    opening_message_id: 'message-1',
    run_id: 'run-1',
    run_status: 'failed',
    run_error_code: 'invalid_model_output',
    configuration: {
      profile: { id: 'daily', label: 'Daily', purpose: 'Current information.', definition_version: 2 },
      model: { model_id: 'cloud-a', provider: 'openrouter', runtime: 'cloud', reasoning: null, context_window: null, local_reasoning_mode: null },
      origin: 'hud',
      execution_kind: 'model',
    },
    artifact: null,
    evidence_count: 0,
    evidence_ids: [],
    created_at: '2026-09-25T13:00:00Z',
    presented_at: null,
    speech_status: 'not_requested',
  }
}

describe('BriefingProfilePanel', () => {
  it('enables the built-in briefing profiles, including Deep', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps()} />)

    await user.click(screen.getByRole('button', { name: /Briefing profile/ }))

    expect(screen.getByRole('radio', { name: /Daily/ })).toBeEnabled()
    const catchUp = screen.getByRole('radio', { name: /Catch Up/ })
    expect(catchUp).toBeEnabled()
    expect(catchUp).toHaveTextContent('What changed since a briefing was presented.')
    expect(screen.getByRole('radio', { name: /Deep/ })).toBeEnabled()
  })

  it('shows the bounded investigation expectation and live Deep stage', () => {
    const session = failedSession()
    session.run_status = 'running'
    session.configuration.profile = { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation.', definition_version: 1 }
    session.active_stage = { stage: 'investigating', state: 'started' }
    render(<BriefingProfilePanel {...baseProps({
      profileId: 'deep',
      activeSession: session,
      selectedSessionId: session.id,
      hasActiveSession: true,
    })} />)

    expect(screen.getByText(/take longer and use more model time.*small, read-only set of relevant sources/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Deep is checking relevant read sources')
  })

  it('generates Catch Up with the selected model only when Generate is pressed', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn()
    const onProfileChange = vi.fn()
    function Harness(): ReactElement {
      const [profileId, setProfileId] = useState<BriefingProfileId>('daily')
      return <BriefingProfilePanel {...baseProps({
        profileId,
        onProfileChange: (next) => { onProfileChange(next); setProfileId(next) },
        onGenerate,
      })} />
    }
    render(<Harness />)

    await user.click(screen.getByRole('button', { name: /Briefing profile/ }))
    await user.click(screen.getByRole('radio', { name: /Catch Up/ }))
    expect(onProfileChange).toHaveBeenCalledWith('catch_up')
    expect(onGenerate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Generate Catch Up' }))
    expect(onGenerate).toHaveBeenCalledWith('catch_up')
  })

  it('generates the selected profile only when Generate is pressed', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn()
    const onProfileChange = vi.fn()
    render(<BriefingProfilePanel {...baseProps({ onGenerate, onProfileChange })} />)

    await user.click(screen.getByRole('button', { name: /Briefing profile/ }))
    await user.click(screen.getByRole('radio', { name: /Daily/ }))
    expect(onProfileChange).toHaveBeenCalledWith('daily')
    expect(onGenerate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Generate Daily' }))
    expect(onGenerate).toHaveBeenCalledWith('daily')
  })

  it('keeps the model choice independent of the profile and never generates on model change', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn()
    const onProfileChange = vi.fn()
    function Harness(): ReactElement {
      const [modelId, setModelId] = useState('cloud-a')
      const [profileId, setProfileId] = useState<BriefingProfileId>('daily')
      return <BriefingProfilePanel {...baseProps({
        selectedModelId: modelId,
        onModelChange: setModelId,
        profileId,
        onProfileChange: (next) => { onProfileChange(next); setProfileId(next) },
        onGenerate,
      })} />
    }
    render(<Harness />)

    await user.click(screen.getByRole('button', { name: 'Model: Cloud A' }))
    await user.click(await screen.findByRole('option', { name: /Cloud B/ }))

    expect(screen.getByRole('button', { name: 'Model: Cloud B' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Briefing profile: Daily' })).toBeInTheDocument()
    expect(onProfileChange).not.toHaveBeenCalled()
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('shows a classified model-output failure in the controls', () => {
    const session = failedSession()
    render(<BriefingProfilePanel {...baseProps({ activeSession: session, selectedSessionId: session.id })} />)

    expect(screen.getByText(/did not pass Daily validation after one repair attempt/)).toBeInTheDocument()
    expect(screen.getByText(/Start a new Daily run to try again/)).toBeInTheDocument()
  })

  it('places a resident local model unload control beside Generate', async () => {
    const user = userEvent.setup()
    const onUnloadLocalModel = vi.fn(async () => true)
    render(<BriefingProfilePanel {...baseProps({ activeLocalModel: localModel({ active: true }), onUnloadLocalModel })} />)

    await user.click(screen.getByRole('button', { name: 'Unload gemma-4-E2B-Q4_K_M.gguf' }))
    expect(onUnloadLocalModel).toHaveBeenCalledTimes(1)
  })

  it('disables unloading while a local model is loading', () => {
    render(<BriefingProfilePanel {...baseProps({ loadingLocalModel: localModel({ loading: true }) })} />)

    expect(screen.getByRole('button', { name: 'Unload gemma-4-E2B-Q4_K_M.gguf' })).toBeDisabled()
  })
})
