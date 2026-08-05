import { createRef, type ComponentProps } from 'react'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsPanel from './SettingsPanel'
import {
  buildSettingsResponse,
  buildMcpStatusResponse,
  jsonResponse,
} from '../test/settingsFixtures'

const DEFAULT_PROPS: ComponentProps<typeof SettingsPanel> = {
  open: true,
  onClose: vi.fn(),
  status: 'idle',
  pipelineStep: null,
  isSpeaking: false,
  isCortexQuerying: false,
  agentsStatus: [],
  agentsStatusHydrated: false,
  failedConnectors: [],
  hasBriefingEvidence: true,
  onApplied: vi.fn(),
}

function renderPanel(
  overrides: Partial<ComponentProps<typeof SettingsPanel>> = {},
) {
  return render(<SettingsPanel {...DEFAULT_PROPS} {...overrides} />)
}

describe('SettingsPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('traps focus inside the dialog while settings are loading', async () => {
    vi.mocked(fetch).mockImplementationOnce(
      () => new Promise<Response>(() => undefined),
    )
    const user = userEvent.setup()
    renderPanel()

    const dialog = screen.getByRole('dialog', { name: 'Runtime Settings' })
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    await user.tab()
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    await user.tab({ shift: true })
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
  })

  it('keeps focus trapped after settings become ready', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    const user = userEvent.setup()
    renderPanel()

    await screen.findByRole('switch', { name: 'Weather' })
    const dialog = screen.getByRole('dialog', { name: 'Runtime Settings' })

    for (let index = 0; index < 18; index += 1) {
      await user.tab()
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
    }
  })

  it('restores focus to the opener after Escape closes the dialog', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    const onClose = vi.fn()
    const restoreFocusRef = createRef<HTMLButtonElement>()
    const props = { ...DEFAULT_PROPS, onClose, restoreFocusRef }
    const { rerender } = render(
      <>
        <button ref={restoreFocusRef}>Open settings</button>
        <SettingsPanel {...props} open={false} />
      </>,
    )
    restoreFocusRef.current?.focus()

    rerender(
      <>
        <button ref={restoreFocusRef}>Open settings</button>
        <SettingsPanel {...props} open />
      </>,
    )
    await screen.findByRole('switch', { name: 'Weather' })
    fireEvent.keyDown(
      screen.getByRole('dialog', { name: 'Runtime Settings' }),
      { key: 'Escape' },
    )
    expect(onClose).toHaveBeenCalledOnce()

    rerender(
      <>
        <button ref={restoreFocusRef}>Open settings</button>
        <SettingsPanel {...props} open={false} />
      </>,
    )
    expect(restoreFocusRef.current).toHaveFocus()
  })

  it('closes when the backdrop is clicked', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    const onClose = vi.fn()
    renderPanel({ onClose })

    const dialog = await screen.findByRole('dialog', { name: 'Runtime Settings' })
    fireEvent.click(dialog.parentElement as HTMLElement)

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('requires confirmation before discarding a dirty draft', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    const onClose = vi.fn()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderPanel({ onClose })

    await user.click(await screen.findByRole('switch', { name: 'Weather' }))
    fireEvent.keyDown(
      screen.getByRole('dialog', { name: 'Runtime Settings' }),
      { key: 'Escape' },
    )

    expect(confirm).toHaveBeenCalledOnce()
    expect(onClose).not.toHaveBeenCalled()

    confirm.mockReturnValue(true)
    fireEvent.click(
      screen.getByRole('dialog', { name: 'Runtime Settings' }).parentElement as HTMLElement,
    )
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('keeps runtime status bound to persisted settings while editing the draft', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('switch', { name: 'Weather' }))
    const runtimeSection = screen
      .getByRole('heading', { name: 'Runtime Status' })
      .closest('section')

    expect(runtimeSection).not.toBeNull()
    const weatherStatusRow = within(runtimeSection as HTMLElement)
      .getByText('Weather')
      .parentElement
    expect(weatherStatusRow).not.toBeNull()
    expect(within(weatherStatusRow as HTMLElement).getByText('Clear last briefing')).toBeVisible()
    expect(within(weatherStatusRow as HTMLElement).queryByText('Disabled')).not.toBeInTheDocument()
  })

  it('keeps assistant configuration in Cortex while retaining the global enable switch', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel()

    expect(await screen.findByRole('switch', { name: 'Ask APEX enabled' })).toBeVisible()
    expect(screen.queryByLabelText('Agent runtime')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Cloud profile')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Local profile')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Cloud effort')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Google Search grounding')).not.toBeInTheDocument()
  })

  it('exposes Apodemus context under Local Runtime with experimental 32K only', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    const user = userEvent.setup()
    renderPanel({ agentsStatusHydrated: true })

    expect(await screen.findByRole('heading', { name: 'Local Runtime' })).toBeVisible()
    const contextSelect = screen.getByLabelText('Apodemus context')
    expect(contextSelect).toBeEnabled()
    expect(contextSelect).toHaveValue('8192')
    expect(screen.getByRole('option', { name: '4K' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '8K (default)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '16K' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '32K (experimental)' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /131072|128K/i })).not.toBeInTheDocument()
    expect(
      screen.getByText(
        'Applies the next time Apex Apodemus loads. To change the context of an already loaded Apodemus, unload it first.',
      ),
    ).toBeVisible()

    await user.selectOptions(contextSelect, '16384')
    expect(contextSelect).toHaveValue('16384')
  })

  it('locks Apodemus context while Apodemus is active or loading', async () => {
    const apodemusLoaded = {
      key: 'apodemus' as const,
      display_name: 'Apex Apodemus',
      description: 'Local llama.cpp agent.',
      configured_model: 'gemma-4-E2B-Q4_K_M.gguf',
      sort_order: 6,
      capabilities: [],
      native_tools: {},
      provider: 'llama_cpp' as const,
      version: '1.0',
      runtime: 'local' as const,
      tier: 'balanced',
      stability: 'preview' as const,
      effort_options: null,
      default_effort: null,
      status: 'available' as const,
      status_source: 'runtime' as const,
      status_checked_at: null,
      provider_account_tier: null,
      pricing: {
        currency: 'USD' as const,
        pricing_version: 'test',
        billing_basis: 'local' as const,
        input_per_million: 0,
        output_per_million: 0,
        cached_input_per_million: null,
        long_context_threshold_tokens: null,
        long_context_input_per_million: null,
        long_context_output_per_million: null,
        long_context_cached_input_per_million: null,
      },
      active: true,
      loading: false,
      reason: null,
      idle_unload_remaining_seconds: 120,
      loaded_model: {
        provider: 'llama_cpp' as const,
        name: 'apodemus-8k',
        model: 'apodemus-8k',
        state: 'loaded' as const,
        context_window: 8192,
        size_bytes: null,
        size_vram_bytes: null,
        processor: null,
        context: null,
        expires_at: null,
      },
    }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel({ agentsStatus: [apodemusLoaded], agentsStatusHydrated: true })

    expect(await screen.findByLabelText('Apodemus context')).toBeDisabled()
  })

  it('keeps Apodemus context editable while an idle Mus model is merely resident', async () => {
    const idleMus = {
      key: 'mus' as const,
      display_name: 'Apex Mus',
      description: 'Balanced local profile.',
      configured_model: 'qwen3:4b-instruct',
      sort_order: 5,
      capabilities: [],
      native_tools: {},
      provider: 'ollama' as const,
      version: '7.4',
      runtime: 'local' as const,
      tier: 'balanced',
      stability: 'stable' as const,
      effort_options: null,
      default_effort: null,
      status: 'available' as const,
      status_source: 'runtime' as const,
      status_checked_at: null,
      provider_account_tier: null,
      pricing: {
        currency: 'USD' as const,
        pricing_version: 'test',
        billing_basis: 'local' as const,
        input_per_million: 0,
        output_per_million: 0,
        cached_input_per_million: null,
        long_context_threshold_tokens: null,
        long_context_input_per_million: null,
        long_context_output_per_million: null,
        long_context_cached_input_per_million: null,
      },
      active: true,
      loading: false,
      reason: null,
      idle_unload_remaining_seconds: 90,
      loaded_model: {
        provider: 'ollama' as const,
        name: 'qwen3:4b-instruct',
        model: 'qwen3:4b-instruct',
        state: 'loaded' as const,
        context_window: 4096,
        size_bytes: null,
        size_vram_bytes: null,
        processor: null,
        context: null,
        expires_at: null,
      },
    }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel({
      agentsStatus: [idleMus],
      agentsStatusHydrated: true,
      isCortexQuerying: false,
      localLifecycleBusy: false,
    })

    expect(await screen.findByLabelText('Apodemus context')).toBeEnabled()
  })

  it('locks Apodemus context while local lifecycle or Cortex generation is busy', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel({ localLifecycleBusy: true })

    expect(await screen.findByLabelText('Apodemus context')).toBeDisabled()
  })


  it('edits the optional user designation through local settings', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
      .mockResolvedValueOnce(
        jsonResponse({
          ...buildSettingsResponse(),
          settings: { ...buildSettingsResponse().settings, user_designation: 'Chief' },
        }),
      )
    const user = userEvent.setup()
    renderPanel()

    const designation = await screen.findByRole('textbox', { name: 'User designation' })
    await user.type(designation, 'Chief')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'PATCH'),
      ).toBe(true),
    )
    const saveCall = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(saveCall?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ user_designation: 'Chief' }),
    })
  })

  it('preserves the dirty controls and reports a failed save', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
      .mockResolvedValueOnce(jsonResponse(buildMcpStatusResponse()))
      .mockResolvedValueOnce(
        jsonResponse({
          configured: false,
          state: 'not-configured',
          permission: 'Tasks.Read',
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: 'Write failed.' }, { status: 503 }),
      )
    const user = userEvent.setup()
    renderPanel()

    const weather = await screen.findByRole('switch', { name: 'Weather' })
    await user.click(weather)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Write failed.'))
    expect(weather).toHaveAttribute('aria-checked', 'false')
  })

  it('renders the Market toggle with immediate timing and dark selects', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel()

    expect(await screen.findByRole('switch', { name: 'Market' })).toBeVisible()
    const market = screen.getByRole('switch', { name: 'Market' }).closest('div')
    expect(market).toHaveTextContent('Active')
    const runtimeSection = screen.getByRole('heading', { name: 'Runtime Status' }).closest('section')
    expect(runtimeSection).not.toBeNull()
    const marketStatus = within(runtimeSection as HTMLElement).getByText('Market').parentElement
    expect(marketStatus).not.toBeNull()
    expect(within(marketStatus as HTMLElement).getByText('Enabled')).toBeVisible()
    for (const select of screen.getAllByRole('combobox')) {
      expect(select).toHaveClass('bg-zinc-950', 'text-zinc-100', '[color-scheme:dark]')
      for (const option of within(select).getAllByRole('option')) {
        expect(option).toHaveClass('bg-zinc-950', 'text-zinc-100')
      }
    }
  })

  it('gates MCP providers behind the master toggle and applies them on Save', async () => {
    const saved = structuredClone(buildSettingsResponse())
    saved.settings.mcp.enabled = true
    saved.settings.mcp.servers.github.enabled = true
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
      .mockResolvedValueOnce(jsonResponse(buildMcpStatusResponse()))
      .mockResolvedValueOnce(jsonResponse(saved))
      .mockResolvedValueOnce(
        jsonResponse(
          buildMcpStatusResponse({
            enabled: true,
            status: 'configured',
            reason: 'Connecting.',
            servers: [
              {
                id: 'github',
                enabled: true,
                transport: 'http',
                status: 'configured',
                reason: 'Connecting.',
                registered_tools: [],
              },
            ],
          }),
        ),
      )
    const user = userEvent.setup()
    renderPanel()

    const master = await screen.findByRole('switch', { name: 'External MCP tools' })
    const github = screen.getByRole('switch', { name: 'GitHub' })
    expect(github).toBeDisabled()

    await user.click(master)
    expect(github).toBeEnabled()
    await user.click(github)
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/settings'),
        expect.objectContaining({
          method: 'PATCH',
          body: JSON.stringify({
            mcp: {
              enabled: true,
              servers: { github: { enabled: true } },
            },
          }),
        }),
      ),
    )
  })

  it('shows sanitized MCP status and approved registered tools', async () => {
    const settings = structuredClone(buildSettingsResponse())
    settings.settings.mcp.enabled = true
    settings.settings.mcp.servers.github.enabled = true
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(settings))
      .mockResolvedValueOnce(
        jsonResponse(
          buildMcpStatusResponse({
            enabled: true,
            status: 'connected',
            reason: 'secret aggregate detail',
            servers: [
              {
                id: 'github',
                enabled: true,
                transport: 'http',
                status: 'connected',
                reason: 'Bearer should-never-render',
                registered_tools: ['github_search_code'],
              },
            ],
          }),
        ),
      )
    renderPanel()

    expect(await screen.findByText('Connected')).toBeVisible()
    expect(screen.getByText('github_search_code')).toBeVisible()
    expect(screen.queryByText(/should-never-render/)).not.toBeInTheDocument()
    expect(screen.queryByText(/secret aggregate detail/)).not.toBeInTheDocument()
  })

  it('keeps briefing mode persistence out of the visible settings surface', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel()

    await screen.findByRole('switch', { name: 'Ask APEX enabled' })
    expect(screen.queryByLabelText('Default mode')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Briefing' })).not.toBeInTheDocument()
  })
})
