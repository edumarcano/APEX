import { useState, type ComponentType } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DeferredPresentation } from './DeferredPresentation'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

type ExampleProps = { label: string }

function StatefulExample({ label }: ExampleProps) {
  const [count, setCount] = useState(0)
  return <button type="button" onClick={() => setCount((value) => value + 1)}>{label}:{count}</button>
}

const failure = (retry: () => void) => <div role="alert"><span>Could not load</span><button type="button" onClick={retry}>Retry</button></div>

describe('DeferredPresentation', () => {
  it('shows the fallback until the selected component loads', async () => {
    const pending = deferred<{ default: ComponentType<ExampleProps> }>()
    const load = vi.fn(() => pending.promise)
    render(<DeferredPresentation load={load} componentProps={{ label: 'Workspace' }} fallback={<p>Loading workspace</p>} renderError={failure} />)

    expect(screen.getByText('Loading workspace')).toBeTruthy()
    expect(load).toHaveBeenCalledOnce()
    pending.resolve({ default: StatefulExample })
    expect(await screen.findByRole('button', { name: 'Workspace:0' })).toBeTruthy()
  })

  it('offers a retry after rejection and starts a new loader attempt', async () => {
    const first = deferred<{ default: ComponentType<ExampleProps> }>()
    const second = deferred<{ default: ComponentType<ExampleProps> }>()
    const load = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const user = userEvent.setup()
    render(<DeferredPresentation load={load} componentProps={{ label: 'Workspace' }} fallback={<p>Loading workspace</p>} renderError={failure} />)

    first.reject(new Error('chunk unavailable'))
    expect(await screen.findByRole('alert')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(load).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Loading workspace')).toBeTruthy()
    second.resolve({ default: StatefulExample })
    expect(await screen.findByRole('button', { name: 'Workspace:0' })).toBeTruthy()
  })

  it('keeps the loaded component mounted when its props change', async () => {
    const load = vi.fn(async () => ({ default: StatefulExample }))
    const renderPresentation = (label: string) => <DeferredPresentation load={load} componentProps={{ label }} fallback={<p>Loading workspace</p>} renderError={failure} />
    const user = userEvent.setup()
    const { rerender } = render(renderPresentation('First'))
    const button = await screen.findByRole('button', { name: 'First:0' })
    await user.click(button)

    rerender(renderPresentation('Updated'))
    expect(screen.getByRole('button', { name: 'Updated:1' })).toBeTruthy()
    expect(load).toHaveBeenCalledOnce()
  })
})
