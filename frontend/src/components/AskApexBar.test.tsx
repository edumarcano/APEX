import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { AgentStatus, LocalCommandStatus } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'

const localAgent: AgentStatus = {
  key: 'mus', display_name: 'Apex Mus', description: 'Balanced local profile.', configured_model: 'qwen3:4b-instruct', sort_order: 5, capabilities: ['Larger model'], native_tools: {}, provider: 'ollama', version: '7.4', runtime: 'local', tier: 'balanced', stability: 'stable', effort_options: null, default_effort: null, status: 'available', status_source: 'runtime', status_checked_at: null, provider_account_tier: null, pricing: { currency: 'USD', pricing_version: '2026.08.02', billing_basis: 'local', input_per_million: 0, output_per_million: 0, cached_input_per_million: 0, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, active: false, loading: false, reason: null, idle_unload_remaining_seconds: null, loaded_model: null,
}

const weatherCommand: LocalCommandStatus = {
  key: 'weather', command: '/weather', label: 'Weather', description: 'Configured-location forecast up to five days.', tool_count: 1, estimated_schema_tokens: 120, available: true, unavailable_reason: null,
}

describe('AskApexBar local command shortcuts', () => {
  it('uses Cortex-only active and brief error feedback', () => {
    vi.useFakeTimers()
    const { rerender } = render(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={vi.fn()} agentsStatus={[localAgent]} isSubmitting={false} />)

    const form = screen.getByLabelText('Ask APEX')
    expect(form).toHaveClass('min-h-12')
    expect(screen.getByLabelText('Ask APEX query')).toHaveAttribute('placeholder', 'Ask APEX')

    rerender(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={vi.fn()} agentsStatus={[localAgent]} isSubmitting />)
    expect(form).toHaveClass('cortex-ask-apex-bar--active')
    expect(screen.getByRole('button', { name: 'Sending query' })).toBeDisabled()
    expect(document.querySelector('.cortex-query-spinner')).toBeInTheDocument()

    rerender(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={vi.fn()} agentsStatus={[localAgent]} isSubmitting={false} error="Model request failed" />)
    expect(form).toHaveClass('cortex-ask-apex-bar--error')
    expect(screen.getByRole('status', { name: 'Last query failed: Model request failed' })).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(4_000))
    expect(screen.queryByRole('status', { name: 'Last query failed: Model request failed' })).not.toBeInTheDocument()
    vi.useRealTimers()
  })

  it('submits from the right-side send button only when a query is present', () => {
    const onSubmit = vi.fn()
    render(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={onSubmit} agentsStatus={[localAgent]} isSubmitting={false} />)

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
    const { rerender } = render(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={onSubmit} agentsStatus={[localAgent]} commands={[weatherCommand]} armedToolScope={null} onArmedToolScopeChange={onArmedToolScopeChange} isSubmitting={false} />)
    const input = screen.getByLabelText('Ask APEX query')

    fireEvent.change(input, { target: { value: '/weather' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onArmedToolScopeChange).toHaveBeenCalledWith('weather')

    rerender(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={onSubmit} agentsStatus={[localAgent]} commands={[weatherCommand]} armedToolScope="weather" onArmedToolScopeChange={onArmedToolScopeChange} isSubmitting={false} />)
    expect(screen.getByText('Tool scope: /weather')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Ask APEX query'), { target: { value: 'What is the forecast?' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))

    expect(onSubmit).toHaveBeenCalledWith('What is the forecast?', 'mus', 'weather')
    expect(onArmedToolScopeChange).toHaveBeenLastCalledWith(null)
  })

  it('lets an available typed slash command override the armed inspector scope', () => {
    const onSubmit = vi.fn()
    render(<AskApexBar presentation="cortex" activeAgent="mus" onSubmit={onSubmit} agentsStatus={[localAgent]} commands={[weatherCommand]} armedToolScope="mail" onArmedToolScopeChange={vi.fn()} isSubmitting={false} />)
    fireEvent.change(screen.getByLabelText('Ask APEX query'), { target: { value: '/weather tomorrow' } })
    fireEvent.submit(screen.getByLabelText('Ask APEX'))
    expect(onSubmit).toHaveBeenCalledWith('tomorrow', 'mus', 'weather')
  })

  it('treats Apodemus as a local Agent for slash-command tooling', () => {
    const apodemusAgent: AgentStatus = {
      ...localAgent,
      key: 'apodemus',
      display_name: 'Apex Apodemus',
      configured_model: 'gemma-4-E2B-Q4_K_M.gguf',
      provider: 'llama_cpp',
    }
    render(
      <AskApexBar
        presentation="cortex"
        activeAgent="apodemus"
        onSubmit={vi.fn()}
        agentsStatus={[apodemusAgent]}
        commands={[weatherCommand]}
        armedToolScope="weather"
        onArmedToolScopeChange={vi.fn()}
        isSubmitting={false}
      />,
    )

    expect(screen.getByText('Tool scope: /weather')).toBeInTheDocument()
  })
})
