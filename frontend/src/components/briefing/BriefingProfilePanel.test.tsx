import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { BriefingProfileSummary, BriefingSessionDetail } from '../../types/briefings'
import type { ModelCatalogEntry } from '../../types/telemetry'
import { BriefingProfilePanel } from './BriefingProfilePanel'

const profiles: BriefingProfileSummary[] = [
  { id: 'daily', label: 'Daily', purpose: 'Current information.', investigation_required: false, available: true, unavailable_reason: null },
  { id: 'catch_up', label: 'Catch Up', purpose: 'What changed since a briefing was presented.', investigation_required: false, available: true, unavailable_reason: null },
  { id: 'deep', label: 'Deep', purpose: 'An evidence-backed investigation across relevant current information and context.', investigation_required: true, available: true, unavailable_reason: null },
]

const catalog: ModelCatalogEntry[] = [
  { model_id: 'cloud-a', display_name: 'Cloud A', provider: 'openrouter', runtime: 'cloud', stability: 'preview', reasoning_options: ['low', 'high'], default_reasoning: 'high', hosted_capabilities: [], status: 'available', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 1.2, cached_input_per_million: null, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null } },
  { model_id: 'cloud-b', display_name: 'Cloud B', provider: 'openrouter', runtime: 'cloud', stability: 'experimental', reasoning_options: ['none', 'low'], default_reasoning: 'low', hosted_capabilities: [], status: 'verified', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0.75, output_per_million: 3.75, cached_input_per_million: null, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null } },
  { model_id: 'local-a', display_name: 'Local A', provider: 'llama_cpp', runtime: 'local', stability: 'stable', reasoning_modes: ['none', 'focused'], default_reasoning_mode: 'none', context_options: [16384, 32768], hosted_capabilities: [], status: 'available' },
]

function localModel(overrides: Partial<ModelCatalogEntry> = {}): ModelCatalogEntry {
  return {
    model_id: 'local-a',
    display_name: 'Local A',
    provider: 'llama_cpp',
    runtime: 'local',
    stability: 'stable',
    reasoning_modes: ['none', 'focused'],
    hosted_capabilities: [],
    status: 'available',
    active: false,
    loading: false,
    ...overrides,
  }
}

function session(overrides: Partial<BriefingSessionDetail> = {}): BriefingSessionDetail {
  return {
    id: 'session-1',
    conversation_id: 'conversation-1',
    opening_message_id: 'message-1',
    run_id: 'run-1',
    run_status: 'failed',
    run_error_code: null,
    configuration: {
      profile: { id: 'catch_up', label: 'Catch Up', purpose: 'What changed.', definition_version: 2 },
      model: { model_id: 'cloud-a', provider: 'openrouter', runtime: 'cloud', reasoning: 'high', context_window: 16384, local_reasoning_mode: null },
      origin: 'cli',
      execution_kind: 'model',
    },
    artifact: null,
    evidence_count: 0,
    evidence_ids: [],
    created_at: '2026-09-25T13:00:00Z',
    presented_at: null,
    speech_status: 'not_requested',
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
    cloudEffort: 'high',
    localReasoningMode: 'none',
    modelCatalog: catalog,
    canGenerate: true,
    busy: false,
    hasActiveSession: false,
    isGenerating: false,
    onGenerate: vi.fn().mockResolvedValue(undefined),
    onRepeat: vi.fn().mockResolvedValue(undefined),
    autoOpenSetup: false,
    onAutoOpenSetupConsumed: vi.fn(),
    demoModeActive: false,
    onCancel: vi.fn(),
    sessions: [],
    selectedSessionId: null,
    isLoadingSessions: false,
    onOpenSession: vi.fn(),
    activeSession: null,
    latestSession: null,
    latestError: null,
    isLoadingLatestSession: false,
    error: null,
    activeLocalModel: null,
    loadingLocalModel: null,
    localLifecycleBusy: false,
    onUnloadLocalModel: vi.fn(async () => true),
    ...overrides,
  }
}

describe('BriefingProfilePanel', () => {
  it('shows the configured agent display name in the setup dialog', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps({ agentDisplayName: 'Commander' })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const dialog = screen.getByRole('dialog', { name: 'Set up your briefing' })
    expect(within(dialog).getByText('Configure Commander')).toBeInTheDocument()
    expect(within(dialog).getByText(/configure Commander/)).toBeInTheDocument()
    expect(within(dialog).getByRole('group', { name: 'Commander model and effort' })).toBeInTheDocument()
    expect(within(dialog).queryByText('Lynx')).not.toBeInTheDocument()
  })

  it('names APEX or the agent as the actor in running briefing status', () => {
    const running = session({ id: 'run-session', run_status: 'running' })
    const props = baseProps({ agentDisplayName: 'Commander', selectedSessionId: 'run-session', activeSession: running })
    const { rerender } = render(<BriefingProfilePanel {...props} />)
    expect(screen.getByText(/^Commander is preparing your Catch Up briefing/)).toBeInTheDocument()

    const deep = (stage: 'collecting' | 'investigating' | 'synthesizing' | null) => session({
      id: 'run-session',
      run_status: 'running',
      configuration: { ...running.configuration, profile: { ...running.configuration.profile, id: 'deep', label: 'Deep' } },
      active_stage: stage ? { stage, state: 'started' } : null,
    })
    rerender(<BriefingProfilePanel {...props} activeSession={deep(null)} />)
    expect(screen.getByText(/^APEX is collecting the briefing snapshot/)).toBeInTheDocument()
    rerender(<BriefingProfilePanel {...props} activeSession={deep('investigating')} />)
    expect(screen.getByText(/^Commander is checking your connected sources/)).toBeInTheDocument()
    rerender(<BriefingProfilePanel {...props} activeSession={deep('synthesizing')} />)
    expect(screen.getByText(/^Commander is preparing your evidence-backed briefing/)).toBeInTheDocument()
  })

  it('opens accessible setup and submits the selected profile and reasoning draft', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn().mockResolvedValue(undefined)
    const onProfileChange = vi.fn()
    render(<BriefingProfilePanel {...baseProps({ onGenerate, onProfileChange })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const dialog = screen.getByRole('dialog', { name: 'Set up your briefing' })
    const cards = within(dialog).getByRole('group', { name: 'Select briefing' })
    expect(within(cards).getByRole('button', { name: /Daily/ })).toHaveTextContent('Current information.')
    expect(within(cards).getByRole('button', { name: /Catch Up/ })).toHaveTextContent('What changed since a briefing was presented.')
    expect(within(cards).getByRole('button', { name: /Deep/ })).toHaveTextContent('evidence-backed investigation')
    const agentTrigger = within(dialog).getByRole('button', { name: /Cloud A/ })
    expect(agentTrigger).toHaveTextContent('OpenRouter')
    expect(agentTrigger).toHaveTextContent('$0.20/M in · $1.20/M out')
    expect(agentTrigger).toHaveTextContent('Preview')
    expect(within(dialog).getByRole('button', { name: /^Select effort/ })).toHaveTextContent('High')
    await user.click(agentTrigger)
    const modelChoices = within(dialog).getByRole('group', { name: 'Lynx model choices' })
    const cloudModels = within(modelChoices).getByRole('group', { name: 'Cloud models' })
    expect(within(cloudModels).getByRole('button', { name: /Cloud A/ })).toHaveTextContent('Preview')
    expect(within(cloudModels).getByRole('button', { name: /Cloud B/ })).toHaveTextContent('Experimental')
    expect(within(modelChoices).getByRole('group', { name: 'Local models' })).toBeInTheDocument()
    const effortTrigger = within(dialog).getByRole('button', { name: /^Select effort/ })
    expect(effortTrigger).toHaveTextContent(/Effort.*High/)
    await user.click(effortTrigger)
    const effortChoices = within(dialog).getByRole('group', { name: 'Reasoning effort choices' })
    expect(within(effortChoices).getByRole('button', { name: 'High' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(effortChoices).getByRole('button', { name: 'Low' }))
    await user.click(within(cards).getByRole('button', { name: /Catch Up/ }))
    expect(onProfileChange).not.toHaveBeenCalled()
    expect(onGenerate).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Generate Catch Up' }))

    await waitFor(() => expect(onGenerate).toHaveBeenCalledWith({
      profileId: 'catch_up',
      modelId: 'cloud-a',
      cloudEffort: 'low',
      localReasoningMode: null,
    }))
    expect(onProfileChange).toHaveBeenCalledWith('catch_up')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('exposes profile cards as pressed buttons with normal Tab navigation', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps()} />)
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))

    const cards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Select briefing' })
    const daily = within(cards).getByRole('button', { name: /Daily/ })
    const catchUp = within(cards).getByRole('button', { name: /Catch Up/ })
    expect(daily).toHaveAttribute('aria-pressed', 'true')
    expect(catchUp).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()

    daily.focus()
    await user.keyboard('{ArrowRight}')
    expect(daily).toHaveFocus()
    expect(daily).toHaveAttribute('aria-pressed', 'true')
    await user.tab()
    expect(catchUp).toHaveFocus()
  })

  it('discards unsubmitted profile, model, and reasoning changes on close and reopens from shared settings', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn().mockResolvedValue(undefined)
    render(<BriefingProfilePanel {...baseProps({ onGenerate })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const cards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Select briefing' })
    await user.click(within(cards).getByRole('button', { name: /Catch Up/ }))
    const agentTrigger = screen.getByRole('button', { name: /Cloud A/ })
    await user.click(agentTrigger)
    const modelChoices = screen.getByRole('group', { name: 'Lynx model choices' })
    await user.click(within(modelChoices).getByRole('button', { name: /Cloud B/ }))
    expect(agentTrigger).toHaveTextContent('Experimental')
    const effortTrigger = screen.getByRole('button', { name: /^Select effort/ })
    expect(effortTrigger).toHaveTextContent('Choose effort')
    await user.click(effortTrigger)
    const effortChoices = screen.getByRole('group', { name: 'Reasoning effort choices' })
    expect(within(effortChoices).getByRole('button', { name: 'Low' })).toHaveAttribute('aria-pressed', 'false')
    await user.click(within(effortChoices).getByRole('button', { name: 'Low' }))
    await user.click(effortTrigger)
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onGenerate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const reopenedCards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Select briefing' })
    expect(within(reopenedCards).getByRole('button', { name: /Daily/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /^Select effort/ })).toHaveTextContent('High')
  })

  it('reopens a failed submission with the same draft and an actionable error', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn().mockRejectedValue(new Error('Briefing settings could not be saved.'))
    render(<BriefingProfilePanel {...baseProps({ onGenerate })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const initialCards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Select briefing' })
    await user.click(within(initialCards).getByRole('button', { name: /Catch Up/ }))
    await user.click(screen.getByRole('button', { name: /^Select effort/ }))
    await user.click(within(screen.getByRole('group', { name: 'Reasoning effort choices' })).getByRole('button', { name: 'Low' }))
    await user.click(screen.getByRole('button', { name: 'Generate Catch Up' }))

    const dialog = await screen.findByRole('dialog', { name: 'Set up your briefing' })
    const reopenedCards = within(dialog).getByRole('group', { name: 'Select briefing' })
    expect(within(reopenedCards).getByRole('button', { name: /Catch Up/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /^Select effort/ })).toHaveTextContent('Low')
    expect(screen.getByRole('alert')).toHaveTextContent('Briefing settings could not be saved.')
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })

  it('traps focus, restores it to Set up, and closes on backdrop click', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps()} />)
    const opener = screen.getByRole('button', { name: 'Set up briefing' })
    await user.click(opener)
    const close = screen.getByRole('button', { name: 'Close briefing setup' })
    expect(close).toHaveFocus()

    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Generate Daily' })).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(opener).toHaveFocus()

    await user.click(opener)
    const backdrop = screen.getByRole('dialog').parentElement
    if (!backdrop) throw new Error('The setup dialog should be inside its backdrop.')
    fireEvent.mouseDown(backdrop)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('opens each selector directly and closes it before the setup dialog on Escape', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps()} />)
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const dialog = screen.getByRole('dialog')
    const modelTrigger = within(dialog).getByRole('button', { name: /^Select model/ })
    const effortTrigger = within(dialog).getByRole('button', { name: /^Select effort/ })
    await user.click(modelTrigger)
    expect(within(dialog).getByRole('group', { name: 'Lynx model choices' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(modelTrigger).toHaveFocus()
    expect(screen.queryByRole('group', { name: 'Lynx model choices' })).not.toBeInTheDocument()
    await user.click(effortTrigger)
    expect(within(dialog).getByRole('group', { name: 'Reasoning effort choices' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(effortTrigger).toHaveFocus()
    expect(screen.queryByRole('group', { name: 'Reasoning effort choices' })).not.toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps setup available during an active run while disabling Generate and Repeat', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps({ hasActiveSession: true })} />)

    const repeat = screen.getByRole('button', { name: 'Repeat last briefing' })
    expect(repeat).toBeDisabled()
    expect(screen.getByText('A briefing is already running.')).toBeInTheDocument()
    const setup = screen.getByRole('button', { name: 'Set up briefing' })
    expect(setup).toBeEnabled()
    await user.click(setup)
    expect(screen.getByRole('button', { name: 'Generate Daily' })).toBeDisabled()
  })

  it('blocks setup and repeat from racing an in-flight submission or repeat', async () => {
    const user = userEvent.setup()
    let resolveGenerate!: () => void
    const onGenerate = vi.fn(() => new Promise<void>((resolve) => { resolveGenerate = resolve }))
    const props = baseProps({ latestSession: session(), onGenerate })
    const { rerender } = render(<BriefingProfilePanel {...props} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    await user.click(screen.getByRole('button', { name: 'Generate Daily' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set up briefing' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Repeat last briefing' })).toBeDisabled()
    resolveGenerate()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Set up briefing' })).toBeEnabled())

    let resolveRepeat!: () => void
    const onRepeat = vi.fn(() => new Promise<void>((resolve) => { resolveRepeat = resolve }))
    rerender(<BriefingProfilePanel {...baseProps({ latestSession: session(), onRepeat })} />)
    await user.click(screen.getByRole('button', { name: 'Repeat last briefing' }))
    expect(screen.getByRole('button', { name: 'Set up briefing' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Repeating…' })).toBeDisabled()
    resolveRepeat()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Set up briefing' })).toBeEnabled())
  })

  it('repeats the newest saved failed CLI session and reports its configuration', async () => {
    const user = userEvent.setup()
    const onRepeat = vi.fn().mockResolvedValue(undefined)
    render(<BriefingProfilePanel {...baseProps({ latestSession: session(), onRepeat })} />)

    expect(screen.getByText(/Catch Up · Cloud A · failed/)).toBeInTheDocument()
    const repeat = screen.getByRole('button', { name: 'Repeat last briefing' })
    expect(repeat).toBeEnabled()
    await user.click(repeat)
    await waitFor(() => expect(onRepeat).toHaveBeenCalledTimes(1))
  })

  it('disables repeat with a reason when the saved model is no longer available', () => {
    const latest = session({
      configuration: {
        ...session().configuration,
        model: { ...session().configuration.model, model_id: 'removed-model' },
      },
    })
    render(<BriefingProfilePanel {...baseProps({ latestSession: latest })} />)

    expect(screen.getByRole('button', { name: 'Repeat last briefing' })).toBeDisabled()
    expect(screen.getByText('The model used by this briefing is not currently available.')).toBeInTheDocument()
  })

  it('allows a user to retry the latest-history check after a transient lookup error', async () => {
    const user = userEvent.setup()
    const onRepeat = vi.fn().mockResolvedValue(undefined)
    render(<BriefingProfilePanel {...baseProps({ latestError: 'Saved sessions unavailable.', onRepeat })} />)

    expect(screen.getByText('The latest saved briefing could not be checked. Saved sessions unavailable.')).toBeInTheDocument()
    const repeat = screen.getByRole('button', { name: 'Repeat last briefing' })
    expect(repeat).toBeEnabled()
    await user.click(repeat)
    await waitFor(() => expect(onRepeat).toHaveBeenCalledTimes(1))
  })

  it('disables repeat when saved reasoning fields do not match the current runtime', () => {
    const malformed = session({
      configuration: {
        ...session().configuration,
        model: { ...session().configuration.model, local_reasoning_mode: 'focused' },
      },
    })
    render(<BriefingProfilePanel {...baseProps({ latestSession: malformed })} />)

    expect(screen.getByRole('button', { name: 'Repeat last briefing' })).toBeDisabled()
    expect(screen.getByText('The saved cloud model configuration contains an unsupported local reasoning mode.')).toBeInTheDocument()
  })

  it('keeps Deep unavailable in demo mode and repeats the saved demo profile through fixtures', async () => {
    const user = userEvent.setup()
    const onRepeat = vi.fn().mockResolvedValue(undefined)
    const demoSession = session({
      configuration: {
        ...session().configuration,
        profile: { id: 'catch_up', label: 'Catch Up', purpose: 'What changed.', definition_version: 2 },
        model: { model_id: 'demo/daily-fixture', provider: 'demo', runtime: 'demo', reasoning: null, context_window: 16384, local_reasoning_mode: null },
        execution_kind: 'demo',
      },
    })
    render(<BriefingProfilePanel {...baseProps({ latestSession: demoSession, demoModeActive: true, onRepeat })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    expect(screen.getByRole('button', { name: /Deep/ })).toBeDisabled()
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', { name: 'Repeat last briefing' }))
    await waitFor(() => expect(onRepeat).toHaveBeenCalledTimes(1))
  })

  it('shows local reasoning modes without saving a draft selection before Generate', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn().mockResolvedValue(undefined)
    render(<BriefingProfilePanel {...baseProps({
      selectedModelId: 'local-a',
      localReasoningMode: 'none',
      modelCatalog: [localModel()],
      onGenerate,
    })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const effortTrigger = screen.getByRole('button', { name: /^Select effort/ })
    expect(effortTrigger).toHaveTextContent('None')
    await user.click(effortTrigger)
    const effortChoices = screen.getByRole('group', { name: 'Reasoning effort choices' })
    expect(within(effortChoices).getByRole('button', { name: 'None' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(effortChoices).getByRole('button', { name: 'High' }))
    expect(onGenerate).not.toHaveBeenCalled()
    expect(effortTrigger).toHaveTextContent('High')
    await user.click(screen.getByRole('button', { name: 'Generate Daily' }))
    await waitFor(() => expect(onGenerate).toHaveBeenCalledWith({
      profileId: 'daily', modelId: 'local-a', cloudEffort: null, localReasoningMode: 'focused',
    }))
  })

  it('places the resident local model unload control beside other briefing controls', async () => {
    const user = userEvent.setup()
    const onUnloadLocalModel = vi.fn(async () => true)
    render(<BriefingProfilePanel {...baseProps({ activeLocalModel: localModel({ active: true }), onUnloadLocalModel })} />)

    await user.click(screen.getByRole('button', { name: 'Unload local-a' }))
    expect(onUnloadLocalModel).toHaveBeenCalledTimes(1)
  })

  it('toggles auto-generate spoken highlights and respects voiceMode off', async () => {
    const user = userEvent.setup()
    const onAutoGenerateHighlightsChange = vi.fn()
    const { rerender } = render(<BriefingProfilePanel
      {...baseProps()}
      autoGenerateHighlights={false}
      onAutoGenerateHighlightsChange={onAutoGenerateHighlightsChange}
      configuredTtsEngine="google"
      voiceMode="manual"
    />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    expect(screen.getByText('Configure Lynx')).toBeInTheDocument()
    expect(screen.getByText('Voice engine · Google TTS')).toBeInTheDocument()
    const toggle = screen.getByRole('switch', { name: 'Auto-generate spoken highlights' })
    expect(toggle).toBeEnabled()
    expect(toggle).toHaveAttribute('aria-checked', 'false')

    await user.click(toggle)
    expect(onAutoGenerateHighlightsChange).toHaveBeenCalledWith(true)

    rerender(<BriefingProfilePanel
      {...baseProps()}
      autoGenerateHighlights={true}
      onAutoGenerateHighlightsChange={onAutoGenerateHighlightsChange}
      configuredTtsEngine="kokoro"
      voiceMode="off"
    />)
    expect(screen.getByText('Voice engine · Kokoro')).toBeInTheDocument()
    expect(screen.getByText('Voice output is turned off in Settings.')).toBeInTheDocument()
    expect(toggle).toBeDisabled()
    expect(toggle).toHaveAttribute('aria-checked', 'false')
  })
})
