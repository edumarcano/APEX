import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CortexWorkspace } from './CortexWorkspace'
import type { AgentProfileStatus } from '../types/telemetry'

const panthera: AgentProfileStatus = {
  key: 'panthera', display_name: 'Apex Panthera', description: 'Cloud profile.',
  configured_model: 'gpt-5.6-luna', native_tools: {}, provider: 'openai', version: '2.0',
  mode: 'cloud', tier: 'balanced', stability: 'stable', effort_options: ['light', 'focused', 'extended'],
  default_effort: 'focused', status: 'available', active: false, loading: false, reason: null,
  idle_unload_remaining_seconds: null, loaded_model: null,
}

describe('CortexWorkspace', () => {
  it('keeps runtime controls, context diagnostics, and new-session reset available together', async () => {
    const onNewSession = vi.fn()
    const onSnapshotAttachedChange = vi.fn()
    const user = userEvent.setup()
    render(
      <CortexWorkspace
        activeProfile="panthera" cloudEffort="focused" devModeActive={false} askApexEnabled
        profilesStatus={[panthera]} profilesStatusHydrated history={[]} latestTrace={[]} error={null}
        contextUsage={{ estimated_prompt_tokens: 45, peak_prompt_tokens: null, context_window: 4096, history_messages_dropped: 0 }}
        isQuerying={false} snapshotAttached snapshotAvailable
        onSnapshotAttachedChange={onSnapshotAttachedChange} onProfileChange={vi.fn()} onModeChange={vi.fn()}
        onEffortChange={vi.fn()} onGoogleSearchChange={vi.fn()} neofelisGoogleSearchEnabled
        onSubmit={vi.fn()} onNewSession={onNewSession}
      />,
    )

    expect(screen.getByRole('region', { name: 'Cortex workspace' })).toBeInTheDocument()
    expect(screen.getByText('45/4,096')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /new session/i }))
    expect(onNewSession).toHaveBeenCalledOnce()
    await user.click(screen.getByRole('checkbox'))
    expect(onSnapshotAttachedChange).toHaveBeenCalledWith(false)
  })
})
