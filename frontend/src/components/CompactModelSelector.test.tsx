import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ModelCatalogEntry } from '../types/telemetry'
import { CompactModelSelector } from './CompactModelSelector'

const catalog: ModelCatalogEntry[] = [
  { model_id: 'deepseek/deepseek-v4-flash-0731', display_name: 'DeepSeek V4 Flash', provider: 'openrouter', runtime: 'cloud', stability: 'stable', reasoning_options: ['none', 'low', 'high', 'max'], default_reasoning: 'high', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 0.4, cached_input_per_million: null, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, hosted_capabilities: [], status: 'configured' },
  { model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', provider: 'openai', runtime: 'cloud', stability: 'preview', reasoning_options: ['none', 'low', 'high'], default_reasoning: 'low', hosted_capabilities: [], status: 'verified' },
  { model_id: 'gemma-4-E2B-Q4_K_M.gguf', display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', stability: 'experimental', reasoning_options: null, default_reasoning: null, maximum_context_window: 131072, hosted_capabilities: [], status: 'available' },
]

describe('CompactModelSelector', () => {
  it('shows the selected model and its provider metadata', async () => {
    const user = userEvent.setup()
    render(<CompactModelSelector selectedModelId={catalog[0].model_id} onModelChange={vi.fn()} catalog={catalog} />)
    await user.click(screen.getByRole('button', { name: /model: deepseek v4 flash/i }))
    const listbox = screen.getByRole('listbox', { name: /select model/i })
    expect(within(listbox).getByText('DeepSeek V4 Flash')).toBeInTheDocument()
    expect(within(listbox).getByText(/OpenRouter · Reasoning configurable/i)).toBeInTheDocument()
  })

  it('groups selectable models by cloud and local runtime', async () => {
    const onModelChange = vi.fn()
    const user = userEvent.setup()
    render(<CompactModelSelector selectedModelId={catalog[0].model_id} onModelChange={onModelChange} catalog={catalog} />)
    await user.click(screen.getByRole('button', { name: /model: deepseek v4 flash/i }))
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(within(popover).getByRole('group', { name: 'Cloud models' })).toBeInTheDocument()
    expect(within(popover).getByRole('group', { name: 'Local models' })).toBeInTheDocument()
    await user.click(within(popover).getByRole('option', { name: /gemma 4 e2b/i }))
    expect(onModelChange).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
  })

  it('uses per-model availability without treating another runtime as authoritative', async () => {
    const user = userEvent.setup()
    const availabilityCatalog: ModelCatalogEntry[] = [
      { ...catalog[0], credentials_configured: false, status: 'disabled' },
      { ...catalog[1], status: 'configured' },
      { ...catalog[2], status: 'available' },
    ]
    render(<CompactModelSelector selectedModelId={catalog[1].model_id} onModelChange={vi.fn()} catalog={availabilityCatalog} />)
    await user.click(screen.getByRole('button', { name: /model: gpt-5\.6 luna/i }))
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(within(popover).getByRole('option', { name: /deepseek v4 flash/i })).toBeDisabled()
    expect(within(popover).getByText(/OpenRouter · Missing API key/i)).toBeInTheDocument()
    expect(within(popover).getByRole('option', { name: /gemma 4 e2b/i })).not.toBeDisabled()
  })

  it('labels the selected cloud LED accessibly and overrides cached green while offline', async () => {
    const user = userEvent.setup()
    render(<CompactModelSelector selectedModelId={catalog[1].model_id} onModelChange={vi.fn()} catalog={catalog} />)

    const led = screen.getByRole('img', { name: 'Availability: Verified' })
    expect(led).toHaveClass('hud-led--live')
    expect(screen.getByRole('button', { name: /availability verified/i })).toBeInTheDocument()
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    fireEvent.offline(window)
    expect(screen.getByRole('img', { name: 'Availability: Browser offline' })).toHaveClass('hud-led--error')

    await user.click(screen.getByRole('button', { name: /model: gpt-5\.6 luna/i }))
    expect(screen.getByRole('option', { name: /gpt-5\.6 luna/i })).toBeEnabled()
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    fireEvent.online(window)
  })

  it('shows configured credentials as neutral and rate limits as errors', () => {
    const configured = [{ ...catalog[0], credentials_configured: true, status: 'configured' as const }]
    const { rerender } = render(<CompactModelSelector selectedModelId={catalog[0].model_id} onModelChange={vi.fn()} catalog={configured} />)
    expect(screen.getByRole('img', { name: 'Availability: Configured' })).not.toHaveClass('hud-led--live')

    rerender(<CompactModelSelector selectedModelId={catalog[0].model_id} onModelChange={vi.fn()} catalog={[{ ...catalog[0], status: 'rate_limited' }]} />)
    expect(screen.getByRole('img', { name: 'Availability: Rate limited' })).toHaveClass('hud-led--error')
  })

  it('uses the local runtime failure as the accessible availability label', () => {
    const unavailableLocal = [{ ...catalog[2], status: 'ollama_unreachable' as const, active: false, loading: false }]
    render(<CompactModelSelector selectedModelId={catalog[2].model_id} onModelChange={vi.fn()} catalog={unavailableLocal} />)

    expect(screen.getByRole('img', { name: 'Availability: Ollama offline' })).toHaveClass('hud-led--error')
    expect(screen.getByRole('button', { name: /availability ollama offline/i })).toBeInTheDocument()
  })

  it('describes local providers with their model-specific context behavior', async () => {
    const user = userEvent.setup()
    const localCatalog: ModelCatalogEntry[] = [{ model_id: 'qwen3:1.7b', display_name: 'Qwen 3 1.7B', provider: 'ollama', runtime: 'local', stability: 'stable', hosted_capabilities: [], status: 'available' }, ...catalog]
    render(<CompactModelSelector selectedModelId="qwen3:1.7b" onModelChange={vi.fn()} catalog={localCatalog} />)
    await user.click(screen.getByRole('button', { name: /model: qwen 3 1\.7b/i }))
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(within(popover).getByText(/Ollama · 4K context/i)).toBeInTheDocument()
    expect(within(popover).getByText(/llama\.cpp · 16K context/i)).toBeInTheDocument()
  })

  it('integrates the selected model and reasoning value and exposes supported effort choices separately', async () => {
    const user = userEvent.setup()
    const onEffortChange = vi.fn()
    render(<CompactModelSelector
      selectedModelId={catalog[0].model_id}
      onModelChange={vi.fn()}
      catalog={catalog}
      presentation="composer"
      cloudEffort="high"
      onEffortChange={onEffortChange}
    />)

    const trigger = screen.getByRole('button', { name: /model: deepseek v4 flash, reasoning high/i })
    expect(trigger).toHaveTextContent('DeepSeek V4 Flash')
    expect(trigger).toHaveTextContent('High')
    await user.click(trigger)
    const menu = screen.getByRole('listbox', { name: /select model/i })
    expect(within(menu).getByText(/In .*Out .* \/ 1M/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reasoning, currently High' }))
    expect(screen.getByRole('group', { name: 'Reasoning effort' })).toBeInTheDocument()
    await user.click(trigger)
    await user.click(trigger)
    expect(screen.queryByRole('group', { name: 'Reasoning effort' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reasoning, currently High' }))
    await user.click(screen.getByRole('button', { name: 'Low' }))
    expect(onEffortChange).toHaveBeenCalledWith('low')
  })

  it('scrolls the model menu to the final reasoning choice when reasoning expands', async () => {
    const user = userEvent.setup()
    const geminiCatalog: ModelCatalogEntry[] = [{
      ...catalog[0],
      model_id: 'google/gemini-test',
      display_name: 'Gemini',
      provider: 'gemini',
      reasoning_options: ['low', 'medium', 'high'],
    }]
    render(<CompactModelSelector
      selectedModelId={geminiCatalog[0].model_id}
      onModelChange={vi.fn()}
      catalog={geminiCatalog}
      presentation="composer"
      cloudEffort="low"
    />)

    await user.click(screen.getByRole('button', { name: /model: gemini, reasoning low/i }))
    const reasoningToggle = screen.getByRole('button', { name: 'Reasoning, currently Low' })
    const menuScrollContainer = screen.getByRole('listbox', { name: /select model/i }).parentElement
    expect(menuScrollContainer).not.toBeNull()
    Object.defineProperty(menuScrollContainer, 'scrollHeight', { configurable: true, value: 360 })

    await user.click(reasoningToggle)

    await waitFor(() => {
      expect(menuScrollContainer).toHaveProperty('scrollTop', 360)
    })
    const reasoningChoices = screen.getByRole('group', { name: 'Reasoning effort' })
    expect(within(reasoningChoices).getByRole('button', { name: 'High' })).toBeInTheDocument()
    await waitFor(() => {
      expect(document.activeElement).toBe(reasoningToggle)
    })
  })

  it('offers local reasoning modes and disables both selectors while the thread is running', async () => {
    const user = userEvent.setup()
    const localCatalog: ModelCatalogEntry[] = [{ ...catalog[2], reasoning_modes: ['none', 'focused'], default_reasoning_mode: 'none' }]
    const onLocalReasoningModeChange = vi.fn()
    const { rerender } = render(<CompactModelSelector
      selectedModelId={localCatalog[0].model_id}
      onModelChange={vi.fn()}
      catalog={localCatalog}
      presentation="composer"
      localReasoningMode="none"
      onLocalReasoningModeChange={onLocalReasoningModeChange}
    />)
    const trigger = screen.getByRole('button', { name: /model: gemma 4 e2b, reasoning none/i })
    await user.click(trigger)
    await user.click(screen.getByRole('button', { name: 'Reasoning, currently None' }))
    await user.click(screen.getByRole('button', { name: 'High' }))
    expect(onLocalReasoningModeChange).toHaveBeenCalledWith('focused')
    expect(screen.getByRole('button', { name: /model: gemma 4 e2b, reasoning none/i })).toBeEnabled()
    rerender(<CompactModelSelector selectedModelId={localCatalog[0].model_id} onModelChange={vi.fn()} catalog={localCatalog} presentation="composer" disabled isQuerying />)
    expect(screen.getByRole('button', { name: /model: gemma 4 e2b/i })).toBeDisabled()
  })
})
