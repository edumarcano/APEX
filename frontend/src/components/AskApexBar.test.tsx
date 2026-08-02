import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentProfileStatus, LocalCommandStatus } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'

const localProfile: AgentProfileStatus = {
  key: 'mus', display_name: 'APEX Mus', description: 'Balanced local profile.', configured_model: 'qwen3:4b-instruct', sort_order: 5, capabilities: ['Larger model'], native_tools: {}, provider: 'ollama', version: '2.0', mode: 'local', tier: 'balanced', stability: 'stable', effort_options: null, default_effort: null, status: 'available', status_source: 'runtime', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: '2026.08.02', billing_basis: 'local', input_per_million: 0, output_per_million: 0, cached_input_per_million: 0, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
}

const weatherCommand: LocalCommandStatus = {
  key: 'weather', command: '/weather', label: 'Weather', description: 'Configured-location forecast up to five days.', tool_count: 1, estimated_schema_tokens: 120, available: true, unavailable_reason: null,
}

describe('AskApexBar local command shortcuts', () => {
  it('uses Cortex-only active and brief error feedback', () => {
    vi.useFakeTimers()
    const { rerender } = render(<AskApexBar activeProfile="mus" onSubmit={vi.fn()} profilesStatus={[localProfile]} isSubmitting={false} integrated />)

    const form = screen.getByLabelText('Ask APEX')
    expect(form).toHaveClass('min-h-12')
    expect(screen.getByLabelText('Ask APEX query')).toHaveAttribute('placeholder', 'Ask APEX')

    rerender(<AskApexBar activeProfile="mus" onSubmit={vi.fn()} profilesStatus={[localProfile]} isSubmitting integrated />)
    expect(form).toHaveClass('cortex-ask-apex-bar--active')
    expect(screen.getByRole('button', { name: 'Sending query' })).toBeDisabled()
    expect(document.querySelector('.cortex-query-spinner')).toBeInTheDocument()

    rerender(<AskApexBar activeProfile="mus" onSubmit={vi.fn()} profilesStatus={[localProfile]} isSubmitting={false} error="Model request failed" integrated />)
    expect(form).toHaveClass('cortex-ask-apex-bar--error')
    expect(screen.getByRole('status', { name: 'Last query failed: Model request failed' })).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(4_000))
    expect(screen.queryByRole('status', { name: 'Last query failed: Model request failed' })).not.toBeInTheDocument()
    vi.useRealTimers()
  })

  it('submits from the right-side send button only when a query is present', () => {
    const onSubmit = vi.fn()
    render(<AskApexBar activeProfile="mus" onSubmit={onSubmit} profilesStatus={[localProfile]} isSubmitting={false} integrated />)

    const send = screen.getByRole('button', { name: 'Send query' })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Ask APEX query'), { target: { value: 'Check status' } })
    expect(send).toBeEnabled()
    fireEvent.click(send)

    expect(onSubmit).toHaveBeenCalledWith('Check status', 'mus', null)
  })

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
