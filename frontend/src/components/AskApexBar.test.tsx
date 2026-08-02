import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentProfileStatus, LocalCommandStatus } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'

const localProfile: AgentProfileStatus = {
  key: 'mus', display_name: 'Apex Mus', description: 'Balanced local profile.', configured_model: 'qwen3:4b-instruct', native_tools: {}, provider: 'ollama', version: '2.0', mode: 'local', tier: 'balanced', stability: 'stable', effort_options: null, default_effort: null, status: 'available', active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
}

const weatherCommand: LocalCommandStatus = {
  key: 'weather', command: '/weather', label: 'Weather', description: 'Configured-location forecast up to five days.', tool_count: 1, estimated_schema_tokens: 120, available: true, unavailable_reason: null,
}

describe('AskApexBar local command shortcuts', () => {
  it('arms a bare slash command and consumes the provided inspector scope on submit', () => {
    const onSubmit = vi.fn()
    const onArmedToolScopeChange = vi.fn()
    const { rerender } = render(<AskApexBar activeProfile="mus" onSubmit={onSubmit} profilesStatus={[localProfile]} commands={[weatherCommand]} armedToolScope={null} onArmedToolScopeChange={onArmedToolScopeChange} isSubmitting={false} integrated />)
    const input = screen.getByLabelText('Ask APEX query')

    fireEvent.change(input, { target: { value: '/weather' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onArmedToolScopeChange).toHaveBeenCalledWith('weather')

    rerender(<AskApexBar activeProfile="mus" onSubmit={onSubmit} profilesStatus={[localProfile]} commands={[weatherCommand]} armedToolScope="weather" onArmedToolScopeChange={onArmedToolScopeChange} isSubmitting={false} integrated />)
    expect(screen.getByText('Tool scope: /weather')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Ask APEX query'), { target: { value: 'What is the forecast?' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))

    expect(onSubmit).toHaveBeenCalledWith('What is the forecast?', 'mus', 'weather')
    expect(onArmedToolScopeChange).toHaveBeenLastCalledWith(null)
  })

  it('lets an available typed slash command override the armed inspector scope', () => {
    const onSubmit = vi.fn()
    render(<AskApexBar activeProfile="mus" onSubmit={onSubmit} profilesStatus={[localProfile]} commands={[weatherCommand]} armedToolScope="mail" onArmedToolScopeChange={vi.fn()} isSubmitting={false} integrated />)
    fireEvent.change(screen.getByLabelText('Ask APEX query'), { target: { value: '/weather tomorrow' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))
    expect(onSubmit).toHaveBeenCalledWith('tomorrow', 'mus', 'weather')
  })
})
