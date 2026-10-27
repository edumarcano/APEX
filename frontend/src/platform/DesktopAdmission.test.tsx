import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DesktopAdmission from './DesktopAdmission'
import type { DesktopBackendState, DesktopSetupState, RuntimeIdentity } from './contracts'

const platformMocks = vi.hoisted(() => ({
  getBackendStatus: vi.fn<() => Promise<DesktopBackendState>>(),
  retryBackend: vi.fn<() => Promise<DesktopBackendState>>(),
  quit: vi.fn<() => Promise<void>>(),
  subscribeBackendState: vi.fn<(onWakeup: () => void) => Promise<() => void>>(),
  getSetupStatus: vi.fn<() => Promise<DesktopSetupState>>(),
  pickImportSource: vi.fn<() => Promise<string | null>>(),
  previewImport: vi.fn<(sourceDir: string) => Promise<DesktopSetupState>>(),
  importData: vi.fn<(previewId: string) => Promise<DesktopSetupState>>(),
  freshStart: vi.fn<() => Promise<DesktopSetupState>>(),
  recoverImport: vi.fn<() => Promise<DesktopSetupState>>(),
  subscribeSetupState: vi.fn<(onWakeup: () => void) => Promise<() => void>>(),
}))

vi.mock('./index', () => ({
  loadDesktopPlatform: async () => platformMocks,
}))
vi.mock('../App', () => ({ default: () => <div data-testid="workspace-app">APEX workspace</div> }))

const identity: RuntimeIdentity = {
  app_id: 'apex',
  app_version: '2.1.0',
  build_id: 'desktop-build',
  instance_id: 'e129e32a-d3be-4a53-8000-000000000001',
  pid: 1234,
  hosting_mode: 'managed',
  launch_id: 'e129e32a-d3be-4a53-8000-000000000002',
  data_root_fingerprint: 'a'.repeat(64),
  shutdown_timeout_seconds: 60,
}

const state = (phase: DesktopBackendState['phase'], overrides: Partial<DesktopBackendState> = {}): DesktopBackendState => ({
  revision: 1,
  generation: 1,
  phase,
  error_code: null,
  runtime: phase === 'ready' ? identity : null,
  ...overrides,
})

const setupState = (phase: DesktopSetupState['phase'], overrides: Partial<DesktopSetupState> = {}): DesktopSetupState => ({
  revision: 1,
  phase,
  preview: null,
  progress: null,
  error_code: null,
  ...overrides,
})

function useStatus(...snapshots: DesktopBackendState[]): void {
  let index = 0
  platformMocks.getBackendStatus.mockImplementation(async () => snapshots[Math.min(index++, snapshots.length - 1)])
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

beforeEach(() => {
  platformMocks.quit.mockResolvedValue(undefined)
  platformMocks.getSetupStatus.mockResolvedValue(setupState('ready'))
  platformMocks.pickImportSource.mockResolvedValue('C:\\APEX-source')
  platformMocks.previewImport.mockResolvedValue(setupState('preview_ready'))
  platformMocks.importData.mockResolvedValue(setupState('importing'))
  platformMocks.freshStart.mockResolvedValue(setupState('ready'))
  platformMocks.recoverImport.mockResolvedValue(setupState('ready'))
  platformMocks.subscribeSetupState.mockResolvedValue(vi.fn())
})

describe('desktop backend admission', () => {
  it('keeps App unmounted until the bounded runtime endpoint matches every supervisor identity field', async () => {
    useStatus(state('ready'))
    platformMocks.subscribeBackendState.mockResolvedValue(vi.fn())
    let resolveRuntime!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveRuntime = resolve })))

    render(<DesktopAdmission />)
    await waitFor(() => expect(platformMocks.getSetupStatus).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/runtime', expect.objectContaining({ signal: expect.any(AbortSignal) })))
    expect(screen.queryByTestId('workspace-app')).not.toBeInTheDocument()

    await act(async () => {
      resolveRuntime(new Response(JSON.stringify(identity), { status: 200, headers: { 'content-type': 'application/json' } }))
    })
    expect(await screen.findByTestId('workspace-app')).toBeInTheDocument()
  })

  it('keeps backend admission and API requests blocked until first-run setup is ready', async () => {
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    platformMocks.getBackendStatus.mockResolvedValue(state('ready'))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    expect(await screen.findByText('Choose how to set up APEX')).toBeInTheDocument()
    expect(screen.getByText(/APEX_DATA_DIR/)).toBeInTheDocument()
    expect(platformMocks.getBackendStatus).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Fresh Start' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import from a checkout' })).toBeInTheDocument()
  })

  it('shows readable inventory progress while checking without opening backend admission', async () => {
    platformMocks.getSetupStatus.mockResolvedValue(setupState('checking', {
      revision: 2,
      progress: { stage: 'inventory', completed_bytes: 1_000, total_bytes: 2_000 },
    }))
    platformMocks.getBackendStatus.mockResolvedValue(state('ready'))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    expect(await screen.findByText('Reviewing managed files: 1.0 kB of 2.0 kB')).toBeInTheDocument()
    expect(screen.getByLabelText('Setup progress')).toHaveAttribute('value', '1000')
    expect(screen.getByText('Checking the selected APEX data profile.')).toBeInTheDocument()
    expect(platformMocks.getBackendStatus).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('starts the existing runtime identity admission only after explicit Fresh Start', async () => {
    platformMocks.getSetupStatus.mockResolvedValueOnce(setupState('choice_required')).mockResolvedValue(setupState('ready', { revision: 2 }))
    platformMocks.freshStart.mockResolvedValue(setupState('ready', { revision: 2 }))
    useStatus(state('ready'))
    platformMocks.subscribeBackendState.mockResolvedValue(() => undefined)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(identity), { status: 200 })))

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Fresh Start' }))
    await waitFor(() => expect(platformMocks.freshStart).toHaveBeenCalledOnce())
    expect(await screen.findByTestId('workspace-app')).toBeInTheDocument()
    expect(platformMocks.getBackendStatus).toHaveBeenCalled()
    expect(fetch).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/runtime', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('treats a canceled native source picker as cancellation without previewing or importing', async () => {
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    platformMocks.pickImportSource.mockResolvedValue(null)
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    await waitFor(() => expect(platformMocks.pickImportSource).toHaveBeenCalledOnce())
    expect(platformMocks.previewImport).not.toHaveBeenCalled()
    expect(platformMocks.importData).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('keeps an import preview with blockers visible without offering commit', async () => {
    const preview = {
      preview_id: 'blocked-preview',
      can_import: false,
      items: [{ path: 'data/apex.db', category: 'database', disposition: 'copy' as const, file_count: 1, total_bytes: 2_000 }],
      warnings: [],
      blockers: ['destination_database_exists', 'source_active'],
    }
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    platformMocks.previewImport.mockResolvedValue(setupState('preview_ready', { revision: 2, preview }))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    expect(await screen.findByRole('region', { name: 'Import blockers' })).toHaveTextContent('destination already contains an APEX database')
    expect(screen.getByRole('region', { name: 'Import blockers' })).toHaveTextContent('Stop the source APEX process before importing')
    expect(screen.queryByText('destination_database_exists')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Import these files' })).not.toBeInTheDocument()
    expect(platformMocks.importData).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows recovery-required setup errors without querying the backend', async () => {
    platformMocks.getSetupStatus.mockResolvedValue(setupState('recovery_required', { error_code: 'import_interrupted' }))
    platformMocks.getBackendStatus.mockResolvedValue(state('ready'))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    expect(await screen.findByRole('heading', { name: 'Import recovery is required' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Recover import' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Quit APEX' })).toBeInTheDocument()
    expect(platformMocks.getBackendStatus).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('requires retry to recover a failed initial setup before source selection without opening the backend', async () => {
    platformMocks.getSetupStatus.mockResolvedValue(setupState('failed', { error_code: 'source_activity_uncertain' }))
    platformMocks.getBackendStatus.mockResolvedValue(state('ready'))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    expect(await screen.findByRole('heading', { name: 'APEX setup needs attention' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('could not confirm that the source is stopped')
    expect(screen.getByRole('button', { name: 'Retry setup' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Choose another source folder' })).not.toBeInTheDocument()
    expect(screen.queryByText('source_activity_uncertain')).not.toBeInTheDocument()
    expect(platformMocks.getBackendStatus).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()

    platformMocks.recoverImport.mockResolvedValue(setupState('choice_required', { revision: 2 }))
    fireEvent.click(screen.getByRole('button', { name: 'Retry setup' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    await waitFor(() => expect(platformMocks.pickImportSource).toHaveBeenCalledTimes(1))
    expect(platformMocks.getBackendStatus).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('does not replace setup with a different snapshot that repeats the same revision', async () => {
    let wake!: () => void
    platformMocks.subscribeSetupState.mockImplementation(async (callback) => { wake = callback; return () => undefined })
    platformMocks.getSetupStatus.mockResolvedValueOnce(setupState('choice_required', { revision: 5 })).mockResolvedValue(
      setupState('preview_ready', { revision: 5, preview: { preview_id: 'same-revision', can_import: true, items: [], warnings: [], blockers: [] } }),
    )
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    expect(await screen.findByRole('heading', { name: 'Choose how to set up APEX' })).toBeInTheDocument()
    await act(async () => { wake() })
    expect(screen.queryByRole('heading', { name: 'Review imported data' })).not.toBeInTheDocument()
    expect(platformMocks.getBackendStatus).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows the managed preview and commits only after explicit confirmation with its preview id', async () => {
    const preview = {
      preview_id: 'preview-token',
      can_import: true,
      items: [{ path: 'data/apex.db', category: 'database', disposition: 'copy' as const, file_count: 1, total_bytes: 2_000 }],
      warnings: ['external_path_needs_review', 'retrieval_schema_unsupported'],
      blockers: [],
    }
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    platformMocks.previewImport.mockResolvedValue(setupState('preview_ready', { revision: 2, preview }))
    platformMocks.importData.mockResolvedValue(setupState('importing', {
      revision: 3,
      preview,
      progress: { stage: 'copying', completed_bytes: 1_000, total_bytes: 2_000 },
    }))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    expect(await screen.findByRole('heading', { name: 'Review imported data' })).toBeInTheDocument()
    expect(screen.getByText('data/apex.db')).toBeInTheDocument()
    expect(screen.getByText('Some files are stored outside the managed data folder and will stay in their current location.')).toBeInTheDocument()
    expect(screen.getByText('The retrieval cache uses an unsupported schema. Its database bytes are kept, retrieval remains disabled, and canonical data remains available.')).toBeInTheDocument()
    expect(screen.queryByText('external_path_needs_review')).not.toBeInTheDocument()
    expect(platformMocks.importData).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Import these files' }))
    expect(await screen.findByText('Copying files: 1.0 kB of 2.0 kB')).toBeInTheDocument()
    expect(platformMocks.importData).toHaveBeenCalledExactlyOnceWith('preview-token')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('uses a generic label for unknown import progress stages', async () => {
    const preview = { preview_id: 'preview-token', can_import: true, items: [], warnings: [], blockers: [] }
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    platformMocks.previewImport.mockResolvedValue(setupState('preview_ready', { revision: 2, preview }))
    platformMocks.importData.mockResolvedValue(setupState('importing', {
      revision: 3,
      preview,
      progress: { stage: 'source-path-private-detail', completed_bytes: 0, total_bytes: 0 },
    }))
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Import these files' }))
    expect(await screen.findByText('Working: 0 B of 0 B')).toBeInTheDocument()
    expect(screen.queryByText(/source-path-private-detail/)).not.toBeInTheDocument()
  })

  it('uses wakeups to refresh snapshots and ignores a late preview older than the current revision', async () => {
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    let wake!: () => void
    platformMocks.subscribeSetupState.mockImplementation(async (callback) => { wake = callback; return () => undefined })
    const previewResult = deferred<DesktopSetupState>()
    platformMocks.previewImport.mockReturnValue(previewResult.promise)
    const freshSnapshot = setupState('importing', { revision: 4, progress: { stage: 'validating', completed_bytes: 0, total_bytes: 2_000 } })
    platformMocks.getSetupStatus.mockResolvedValueOnce(setupState('choice_required')).mockResolvedValue(freshSnapshot)
    vi.stubGlobal('fetch', vi.fn())

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    await waitFor(() => expect(platformMocks.previewImport).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: 'Import from a checkout' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Quit APEX' })).toBeEnabled()
    expect(platformMocks.pickImportSource).toHaveBeenCalledOnce()
    await act(async () => { wake() })
    expect(await screen.findByText('Validating imported data: 0 B of 2.0 kB')).toBeInTheDocument()
    await act(async () => {
      previewResult.resolve(setupState('preview_ready', { revision: 3, preview: {
        preview_id: 'late', can_import: true, items: [], warnings: [], blockers: [],
      } }))
    })
    expect(screen.queryByRole('button', { name: 'Import these files' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('keeps Quit available during an import and reports quit failure without leaking native details', async () => {
    const preview = { preview_id: 'preview-token', can_import: true, items: [], warnings: [], blockers: [] }
    const importResult = deferred<DesktopSetupState>()
    platformMocks.getSetupStatus.mockResolvedValue(setupState('choice_required'))
    platformMocks.previewImport.mockResolvedValue(setupState('preview_ready', { revision: 2, preview }))
    platformMocks.importData.mockReturnValue(importResult.promise)
    platformMocks.quit.mockRejectedValue(new Error('private native detail'))

    render(<DesktopAdmission />)
    fireEvent.click(await screen.findByRole('button', { name: 'Import from a checkout' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Import these files' }))
    await waitFor(() => expect(platformMocks.importData).toHaveBeenCalledOnce())
    const quit = screen.getByRole('button', { name: 'Quit APEX' })
    expect(quit).toBeEnabled()
    fireEvent.click(quit)

    expect(await screen.findByRole('alert')).toHaveTextContent('could not quit cleanly')
    expect(screen.queryByText('private native detail')).not.toBeInTheDocument()
    expect(platformMocks.quit).toHaveBeenCalledOnce()
    await act(async () => {
      importResult.resolve(setupState('importing', { revision: 3, preview }))
    })
  })

  it('does not admit from event data and ignores an older status snapshot', async () => {
    const initialStatus = deferred<DesktopBackendState>()
    platformMocks.getBackendStatus.mockReturnValueOnce(initialStatus.promise)
      .mockResolvedValue(state('ready', { revision: 3 }))
    let wake!: () => void
    const unsubscribe = vi.fn<() => void>()
    vi.stubGlobal('fetch', vi.fn())
    platformMocks.subscribeBackendState.mockImplementation(async (callback) => {
      wake = callback
      return () => unsubscribe()
    })

    const view = render(<DesktopAdmission />)
    expect(await screen.findByText('Waiting for the owned backend to become ready.')).toBeInTheDocument()
    await waitFor(() => expect(platformMocks.subscribeBackendState).toHaveBeenCalledOnce())
    await waitFor(() => expect(platformMocks.getBackendStatus).toHaveBeenCalledOnce())
    await act(async () => { initialStatus.resolve(state('starting', { revision: 4 })) })
    await act(async () => { wake() })
    expect(screen.queryByTestId('workspace-app')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()

    view.unmount()
    await waitFor(() => expect(unsubscribe).toHaveBeenCalledTimes(1))
  })

  it('shows port conflicts and requires explicit confirmation before retrying', async () => {
    useStatus(state('failed', { error_code: 'port_in_use' }), state('starting', { revision: 2, generation: 2 }))
    platformMocks.subscribeBackendState.mockResolvedValue(vi.fn())
    platformMocks.retryBackend.mockResolvedValue(state('starting', { revision: 2, generation: 2 }))

    render(<DesktopAdmission />)
    expect(await screen.findByText('Another service is using the APEX port')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry backend' }))
    expect(screen.getByText(/discard unsent text/)).toBeInTheDocument()
    expect(platformMocks.retryBackend).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Restart backend' }))
    await waitFor(() => expect(platformMocks.retryBackend).toHaveBeenCalledTimes(1))
    expect(screen.getByText('Waiting for the owned backend to become ready.')).toBeInTheDocument()
  })

  it('unmounts workspaces after a backend crash and ignores runtime identities from another process', async () => {
    useStatus(state('ready'), state('failed', { revision: 2, error_code: 'backend_crashed' }))
    platformMocks.subscribeBackendState.mockImplementation(async (callback) => {
      queueMicrotask(callback)
      return () => undefined
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...identity, instance_id: '9a68ecda-9b93-451d-b50a-e7d2ee77abc1' }), { status: 200 })))

    render(<DesktopAdmission />)
    expect(await screen.findByText('The APEX backend stopped unexpectedly')).toBeInTheDocument()
    expect(screen.queryByTestId('workspace-app')).not.toBeInTheDocument()
  })

  it('reports origin rejection and shuts down through the allowlisted command', async () => {
    useStatus(state('ready'))
    platformMocks.subscribeBackendState.mockResolvedValue(vi.fn())
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    render(<DesktopAdmission />)
    expect(await screen.findByText('The desktop connection was rejected')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Check the desktop origin')
    fireEvent.click(screen.getByRole('button', { name: 'Quit APEX' }))
    await waitFor(() => expect(platformMocks.quit).toHaveBeenCalledTimes(1))
  })

  it('fails closed when the supervisor returns a malformed status', async () => {
    platformMocks.getBackendStatus.mockResolvedValue({ phase: 'ready' } as DesktopBackendState)
    platformMocks.subscribeBackendState.mockResolvedValue(() => undefined)

    render(<DesktopAdmission />)
    expect(await screen.findByText('The desktop backend status could not be read')).toBeInTheDocument()
    expect(screen.queryByTestId('workspace-app')).not.toBeInTheDocument()
  })

  it('deduplicates same-generation identity checks and aborts a pending check on unmount', async () => {
    vi.useFakeTimers()
    useStatus(state('ready'))
    platformMocks.subscribeBackendState.mockResolvedValue(() => undefined)
    const request = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn(() => request.promise))

    const view = render(<DesktopAdmission />)
    await act(async () => {
      for (let step = 0; step < 8; step += 1) await Promise.resolve()
    })
    expect(fetch).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(2_500) })
    expect(platformMocks.getBackendStatus).toHaveBeenCalledTimes(2)
    expect(fetch).toHaveBeenCalledTimes(1)

    const signal = vi.mocked(fetch).mock.calls[0][1]?.signal as AbortSignal
    view.unmount()
    expect(signal.aborted).toBe(true)
    vi.useRealTimers()
  })

  it('does not let a stale HTTP failure replace a newer crashed-backend snapshot', async () => {
    useStatus(state('ready'), state('failed', { revision: 2, error_code: 'backend_crashed' }))
    let wake!: () => void
    platformMocks.subscribeBackendState.mockImplementation(async (callback) => { wake = callback; return () => undefined })
    const request = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn(() => request.promise))

    render(<DesktopAdmission />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    await act(async () => { wake() })
    await waitFor(() => expect(platformMocks.getBackendStatus).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('The APEX backend stopped unexpectedly')).toBeInTheDocument()
    await act(async () => { request.resolve(new Response('{}', { status: 403 })) })
    expect(screen.queryByText('The desktop connection was rejected')).not.toBeInTheDocument()
    expect(screen.queryByTestId('workspace-app')).not.toBeInTheDocument()
  })
})
