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
  { model_id: 'cloud-a', display_name: 'Cloud A', provider: 'openrouter', runtime: 'cloud', stability: 'stable', reasoning_options: ['low', 'high'], default_reasoning: 'high', hosted_capabilities: [], status: 'available' },
  { model_id: 'cloud-b', display_name: 'Cloud B', provider: 'openai', runtime: 'cloud', stability: 'stable', reasoning_options: ['none', 'low'], default_reasoning: 'low', hosted_capabilities: [], status: 'verified' },
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
  it('opens accessible setup and submits the selected profile and reasoning draft', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn().mockResolvedValue(undefined)
    const onProfileChange = vi.fn()
    render(<BriefingProfilePanel {...baseProps({ onGenerate, onProfileChange })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const dialog = screen.getByRole('dialog', { name: 'Set up your briefing' })
    const cards = within(dialog).getByRole('group', { name: 'Briefing profile' })
    expect(within(cards).getByRole('button', { name: /Daily/ })).toHaveTextContent('Current information.')
    expect(within(cards).getByRole('button', { name: /Catch Up/ })).toHaveTextContent('What changed since a briefing was presented.')
    expect(within(cards).getByRole('button', { name: /Deep/ })).toHaveTextContent('evidence-backed investigation')
    const modelSelect = screen.getByLabelText('Apex Agent model')
    expect(within(modelSelect).getByRole('group', { name: 'Cloud' })).toBeInTheDocument()
    expect(within(modelSelect).getByRole('group', { name: 'Local' })).toBeInTheDocument()
    expect(screen.getByLabelText('Cloud reasoning effort')).toHaveValue('high')
    await user.click(within(cards).getByRole('button', { name: /Catch Up/ }))
    expect(onProfileChange).not.toHaveBeenCalled()
    expect(onGenerate).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Generate Catch Up' }))

    await waitFor(() => expect(onGenerate).toHaveBeenCalledWith({
      profileId: 'catch_up',
      modelId: 'cloud-a',
      cloudEffort: 'high',
      localReasoningMode: null,
    }))
    expect(onProfileChange).toHaveBeenCalledWith('catch_up')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('exposes profile cards as pressed buttons with normal Tab navigation', async () => {
    const user = userEvent.setup()
    render(<BriefingProfilePanel {...baseProps()} />)
    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))

    const cards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Briefing profile' })
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
    const cards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Briefing profile' })
    await user.click(within(cards).getByRole('button', { name: /Catch Up/ }))
    await user.selectOptions(screen.getByLabelText('Apex Agent model'), 'cloud-b')
    expect(screen.getByLabelText('Cloud reasoning effort')).toHaveValue('')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onGenerate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const reopenedCards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Briefing profile' })
    expect(within(reopenedCards).getByRole('button', { name: /Daily/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('Apex Agent model')).toHaveValue('cloud-a')
    expect(screen.getByLabelText('Cloud reasoning effort')).toHaveValue('high')
  })

  it('reopens a failed submission with the same draft and an actionable error', async () => {
    const user = userEvent.setup()
    const onGenerate = vi.fn().mockRejectedValue(new Error('Briefing settings could not be saved.'))
    render(<BriefingProfilePanel {...baseProps({ onGenerate })} />)

    await user.click(screen.getByRole('button', { name: 'Set up briefing' }))
    const initialCards = within(screen.getByRole('dialog')).getByRole('group', { name: 'Briefing profile' })
    await user.click(within(initialCards).getByRole('button', { name: /Catch Up/ }))
    await user.selectOptions(screen.getByLabelText('Cloud reasoning effort'), 'low')
    await user.click(screen.getByRole('button', { name: 'Generate Catch Up' }))

    const dialog = await screen.findByRole('dialog', { name: 'Set up your briefing' })
    const reopenedCards = within(dialog).getByRole('group', { name: 'Briefing profile' })
    expect(within(reopenedCards).getByRole('button', { name: /Catch Up/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('Cloud reasoning effort')).toHaveValue('low')
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
    const localSelect = screen.getByLabelText('Local reasoning mode')
    expect(localSelect).toHaveValue('none')
    await user.selectOptions(localSelect, 'focused')
    expect(onGenerate).not.toHaveBeenCalled()
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
})
