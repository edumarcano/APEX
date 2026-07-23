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
  jsonResponse,
} from '../test/settingsFixtures'

const DEFAULT_PROPS: ComponentProps<typeof SettingsPanel> = {
  open: true,
  onClose: vi.fn(),
  status: 'idle',
  pipelineStep: null,
  isSpeaking: false,
  isAssistantQuerying: false,
  profilesStatus: [],
  profilesStatusHydrated: false,
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

  it('preserves the dirty controls and reports a failed save', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
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

  it('describes briefing modes and recommends only Acinonyx', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(buildSettingsResponse()))
    renderPanel()

    const select = await screen.findByRole('combobox', { name: 'Default mode' })
    const labels = within(select).getAllByRole('option').map((option) => option.textContent)

    expect(labels).toEqual([
      'Comet — Full briefing · fast cloud synthesis',
      'Lynx — Quick briefing · limited telemetry',
      'Acinonyx — Full briefing · balanced synthesis (Recommended)',
      'Neofelis — Full briefing · higher capacity, slower',
      'Structured Digest — Structured facts · no model or synthesis',
    ])
    expect(labels.filter((label) => label?.includes('Recommended'))).toHaveLength(1)
  })
})
