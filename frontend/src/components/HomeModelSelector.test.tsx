import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ModelCatalogEntry } from '../types/telemetry'
import { HomeModelSelector } from './HomeModelSelector'

const catalog: ModelCatalogEntry[] = [
  { model_id: 'deepseek/deepseek-v4-flash-0731', display_name: 'DeepSeek V4 Flash', provider: 'openrouter', runtime: 'cloud', stability: 'stable', reasoning_options: ['none', 'low', 'high', 'max'], default_reasoning: 'high', hosted_capabilities: [], status: 'configured' },
  { model_id: 'gpt-5.6-luna', display_name: 'GPT-5.6 Luna', provider: 'openai', runtime: 'cloud', stability: 'preview', reasoning_options: ['none', 'low', 'high'], default_reasoning: 'low', hosted_capabilities: [], status: 'verified' },
  { model_id: 'gemma-4-E2B-Q4_K_M.gguf', display_name: 'Gemma 4 E2B', provider: 'llama_cpp', runtime: 'local', stability: 'experimental', reasoning_options: null, default_reasoning: null, maximum_context_window: 131072, hosted_capabilities: [], status: 'available' },
]

describe('HomeModelSelector', () => {
  it('shows the selected model and its provider metadata', async () => {
    const user = userEvent.setup()
    render(<HomeModelSelector selectedModelId={catalog[0].model_id} onModelChange={vi.fn()} catalog={catalog} />)
    await user.click(screen.getByRole('button', { name: 'Model: DeepSeek V4 Flash' }))
    const listbox = screen.getByRole('listbox', { name: /select model/i })
    expect(within(listbox).getByText('DeepSeek V4 Flash')).toBeInTheDocument()
    expect(within(listbox).getByText(/OpenRouter · Reasoning off/i)).toBeInTheDocument()
  })

  it('groups selectable models by cloud and local runtime', async () => {
    const onModelChange = vi.fn()
    const user = userEvent.setup()
    render(<HomeModelSelector selectedModelId={catalog[0].model_id} onModelChange={onModelChange} catalog={catalog} />)
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
    render(<HomeModelSelector selectedModelId={catalog[1].model_id} onModelChange={vi.fn()} catalog={availabilityCatalog} />)
    await user.click(screen.getByRole('button', { name: /model: gpt-5\.6 luna/i }))
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(within(popover).getByRole('option', { name: /deepseek v4 flash/i })).toBeDisabled()
    expect(within(popover).getByText(/OpenRouter · Missing API key/i)).toBeInTheDocument()
    expect(within(popover).getByRole('option', { name: /gemma 4 e2b/i })).not.toBeDisabled()
  })

  it('describes local providers with their model-specific context behavior', async () => {
    const user = userEvent.setup()
    const localCatalog: ModelCatalogEntry[] = [{ model_id: 'qwen3:1.7b', display_name: 'Qwen 3 1.7B', provider: 'ollama', runtime: 'local', stability: 'stable', hosted_capabilities: [], status: 'available' }, ...catalog]
    render(<HomeModelSelector selectedModelId="qwen3:1.7b" onModelChange={vi.fn()} catalog={localCatalog} />)
    await user.click(screen.getByRole('button', { name: 'Model: Qwen 3 1.7B' }))
    const popover = screen.getByRole('listbox', { name: /select model/i })
    expect(within(popover).getByText(/Ollama · 4K context/i)).toBeInTheDocument()
    expect(within(popover).getByText(/llama\.cpp · 16K context/i)).toBeInTheDocument()
  })
})
