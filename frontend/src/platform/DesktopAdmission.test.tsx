import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DesktopAdmission from './DesktopAdmission'
import type { DesktopBackendState, RuntimeIdentity } from './contracts'

const platformMocks = vi.hoisted(() => ({
  getBackendStatus: vi.fn<() => Promise<DesktopBackendState>>(),
  retryBackend: vi.fn<() => Promise<DesktopBackendState>>(),
  quit: vi.fn<() => Promise<void>>(),
  subscribeBackendState: vi.fn<(onWakeup: () => void) => Promise<() => void>>(),
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

describe('desktop backend admission', () => {
  it('keeps App unmounted until the bounded runtime endpoint matches every supervisor identity field', async () => {
    useStatus(state('ready'))
    platformMocks.subscribeBackendState.mockResolvedValue(vi.fn())
    let resolveRuntime!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveRuntime = resolve })))

    render(<DesktopAdmission />)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/runtime', expect.objectContaining({ signal: expect.any(AbortSignal) })))
    expect(screen.queryByTestId('workspace-app')).not.toBeInTheDocument()

    await act(async () => {
      resolveRuntime(new Response(JSON.stringify(identity), { status: 200, headers: { 'content-type': 'application/json' } }))
    })
    expect(await screen.findByTestId('workspace-app')).toBeInTheDocument()
  })

  it('does not admit from event data and ignores an older status snapshot', async () => {
    useStatus(
      state('starting', { revision: 4 }),
      state('ready', { revision: 3 }),
    )
    let wake!: () => void
    const unsubscribe = vi.fn<() => void>()
    vi.stubGlobal('fetch', vi.fn())
    platformMocks.subscribeBackendState.mockImplementation(async (callback) => { wake = callback; return () => unsubscribe() })

    const view = render(<DesktopAdmission />)
    expect(await screen.findByText('Waiting for the owned backend to become ready.')).toBeInTheDocument()
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
