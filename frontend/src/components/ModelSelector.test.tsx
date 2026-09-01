import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ModelCatalogEntry } from '../types/telemetry'
import { ModelSelector } from './ModelSelector'

const catalog: ModelCatalogEntry[] = [
  { model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', provider: 'openai', runtime: 'cloud', stability: 'stable', hosted_capabilities: [], status: 'verified', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'standard', input_per_million: 0.2, output_per_million: 1.2, cached_input_per_million: null, long_context_threshold_tokens: 272000, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null }, reasoning_options: ['none', 'low'], default_reasoning: 'low' },
  { model_id: 'gemini-free', display_name: 'Gemini Free', provider: 'gemini', runtime: 'cloud', stability: 'experimental', hosted_capabilities: [], status: 'configured', pricing: { currency: 'USD', pricing_version: 'test', billing_basis: 'free_tier', input_per_million: 0, output_per_million: 0, cached_input_per_million: null, long_context_threshold_tokens: null, long_context_input_per_million: null, long_context_output_per_million: null, long_context_cached_input_per_million: null } },
  { model_id: 'gemma-4-E2B-Q4_K_M.gguf', display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', stability: 'stable', hosted_capabilities: [], status: 'available', active: true, context_options: [4096, 16384], default_context_window: 16384, reasoning_modes: ['none', 'focused'], default_reasoning_mode: 'none' },
]

describe('ModelSelector', () => {
  it('shows selected model pricing, capabilities, and per-model status', () => {
    render(<ModelSelector selectedModelId="gpt-5.6-luna" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText('GPT-5.6 Luna')).toBeVisible()
    expect(screen.getByText('$0.20/M in · $1.20/M out')).toBeVisible()
    expect(screen.getByText('Verified')).toBeVisible()
  })

  it('groups cloud and local models and selects by model id', async () => {
    const change = vi.fn()
    const user = userEvent.setup()
    render(<ModelSelector selectedModelId="gpt-5.6-luna" onModelChange={change} catalog={catalog} />)
    await user.click(screen.getByRole('button', { name: 'Model' }))
    const listbox = screen.getByRole('listbox', { name: 'Select Apex Agent model' })
    expect(within(listbox).getByRole('group', { name: 'Cloud models' })).toBeVisible()
    expect(within(listbox).getByRole('group', { name: 'Local models' })).toBeVisible()
    await user.click(screen.getByRole('option', { name: /Gemma 4 E2B/i }))
    expect(change).toHaveBeenCalledWith('gemma-4-E2B-Q4_K_M.gguf')
  })

  it('shows free-tier disclosure and local residency from the model entry', () => {
    const { rerender } = render(<ModelSelector selectedModelId="gemini-free" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText(/Content may be used to improve Google products/)).toBeVisible()
    rerender(<ModelSelector selectedModelId="gemma-4-E2B-Q4_K_M.gguf" onModelChange={vi.fn()} catalog={catalog} />)
    expect(screen.getByText('Loaded')).toBeVisible()
    expect(screen.getByText('Selectable context')).toBeVisible()
  })

  it('verifies the selected cloud model id', async () => {
    const verify = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(<ModelSelector selectedModelId="gpt-5.6-luna" onModelChange={vi.fn()} catalog={catalog} onVerify={verify} />)
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(verify).toHaveBeenCalledWith('gpt-5.6-luna')
  })
})
