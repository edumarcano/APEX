import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ModelCatalogEntry } from '../types/telemetry'
import { ModelSelector } from './ModelSelector'

const catalog: ModelCatalogEntry[] = [
  { model_id: 'openai/gpt-6-luna', display_name: 'GPT-6 Luna', provider: 'openrouter', runtime: 'cloud', stability: 'stable', hosted_capabilities: [], status: 'verified', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0.1, output_per_million: 0.5, cached_input_per_million: 0.01, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, reasoning_options: ['none', 'low', 'medium', 'high', 'xhigh', 'max'], default_reasoning: 'medium' },
  { model_id: 'gemini-3.7-flash', display_name: 'Gemini 3.7 Flash', provider: 'gemini', runtime: 'cloud', stability: 'stable', hosted_capabilities: ['google_search'], status: 'configured', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0.75, output_per_million: 3.75, cached_input_per_million: 0.075, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null } },
  { model_id: 'gemma-4-E2B-Q4_K_M.gguf', display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', stability: 'stable', hosted_capabilities: [], status: 'available', active: true, context_options: [4096, 16384], default_context_window: 16384, reasoning_modes: ['none', 'focused'], default_reasoning_mode: 'none' },
]

describe('ModelSelector', () => {
  it('shows selected model pricing, capabilities, and per-model status', () => {
    render(<ModelSelector selectedModelId="openai/gpt-6-luna" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText('GPT-6 Luna')).toBeVisible()
    expect(screen.getByText('$0.10/M in · $0.50/M out')).toBeVisible()
    expect(screen.getByText('Verified')).toBeVisible()
  })

  it('groups cloud and local models and selects by model id', async () => {
    const change = vi.fn()
    const user = userEvent.setup()
    render(<ModelSelector selectedModelId="openai/gpt-6-luna" onModelChange={change} catalog={catalog} />)
    await user.click(screen.getByRole('button', { name: 'Model' }))
    const listbox = screen.getByRole('listbox', { name: 'Select Lynx model' })
    expect(within(listbox).getByRole('group', { name: 'Cloud models' })).toBeVisible()
    expect(within(listbox).getByRole('group', { name: 'Local models' })).toBeVisible()
    await user.click(screen.getByRole('option', { name: /Gemma 4 E2B/i }))
    expect(change).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
  })

  it('shows capabilities and local residency from the model entry', () => {
    const { rerender } = render(<ModelSelector selectedModelId="gemini-3.7-flash" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText('Search')).toBeVisible()
    rerender(<ModelSelector selectedModelId="gemma-4-E2B-Q4_K_M.gguf" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText('Loaded')).toBeVisible()
    expect(screen.getByText('Selectable context')).toBeVisible()
  })

  it('verifies the selected cloud model id', async () => {
    const verify = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(<ModelSelector selectedModelId="openai/gpt-6-luna" onModelChange={vi.fn()} catalog={catalog} onVerify={verify} />)
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(verify).toHaveBeenCalledWith('openai/gpt-6-luna')
  })

  it('shows configured credentials neutrally and cached cloud success as offline when needed', () => {
    const configuredCatalog = [{ ...catalog[0], credentials_configured: true, status: 'configured' as const }]
    const { rerender } = render(<ModelSelector selectedModelId="openai/gpt-6-luna" onModelChange={vi.fn()} catalog={configuredCatalog} />)
    expect(screen.getByText('Configured')).toHaveClass('text-zinc-400')

    rerender(<ModelSelector selectedModelId="openai/gpt-6-luna" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText('Verified')).toHaveClass('text-emerald-300')
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
    fireEvent.offline(window)
    expect(screen.getByText('Browser offline')).toHaveClass('text-[#DC2626]')
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    fireEvent.online(window)
  })

  it('shows rate limiting as a red cloud blocker', () => {
    const limitedCatalog = [{ ...catalog[0], status: 'rate_limited' as const }]
    render(<ModelSelector selectedModelId="openai/gpt-6-luna" onModelChange={vi.fn()} catalog={limitedCatalog} />)
    expect(screen.getByText('Rate limited')).toHaveClass('text-[#DC2626]')
  })
})
