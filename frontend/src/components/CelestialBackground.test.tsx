import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CelestialBackground } from './CelestialBackground'

describe('CelestialBackground', () => {
  let fillRectMock: ReturnType<typeof vi.fn>
  let mockContext: Record<string, unknown>
  let matchMediaMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fillRectMock = vi.fn()
    mockContext = {
      save: vi.fn(),
      restore: vi.fn(),
      scale: vi.fn(),
      createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
      createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
      fillRect: fillRectMock,
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      fillStyle: '',
      strokeStyle: '',
      lineWidth: 1,
    }

    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
      mockContext as unknown as CanvasRenderingContext2D,
    )

    matchMediaMock = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    window.matchMedia = matchMediaMock as unknown as typeof window.matchMedia
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders canvas with aria-hidden="true" and pointer-events-none styling', () => {
    const { container } = render(<CelestialBackground isLaunch workspace="overview" />)
    const canvas = container.querySelector('canvas')

    expect(canvas).toBeInTheDocument()
    expect(canvas).toHaveAttribute('aria-hidden', 'true')
    expect(canvas).toHaveClass('pointer-events-none', 'absolute', 'inset-0')
  })

  it('adjusts canvas dimensions on resize event', () => {
    const { container } = render(<CelestialBackground />)
    const canvas = container.querySelector('canvas') as HTMLCanvasElement
    expect(canvas).toBeInTheDocument()

    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
      width: 1200,
      height: 800,
      top: 0,
      left: 0,
      bottom: 800,
      right: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    })

    // Trigger window resize event
    window.dispatchEvent(new Event('resize'))

    expect(canvas.width).toBe(1200)
    expect(canvas.height).toBe(800)
  })

  it('pauses and resumes animation loop on visibilitychange', () => {
    let frameCallback: FrameRequestCallback | null = null
    let frameId = 100
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      frameCallback = cb
      return ++frameId
    })
    const cafSpy = vi.spyOn(window, 'cancelAnimationFrame')

    render(<CelestialBackground />)
    expect(rafSpy).toHaveBeenCalled()

    // Document is hidden
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(cafSpy).toHaveBeenCalled()

    // Document becomes visible
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(rafSpy.mock.calls.length).toBeGreaterThan(1)

    // Execute frame callback
    if (frameCallback) {
      ;(frameCallback as FrameRequestCallback)(1000)
    }
  })

  it('renders a static frame without looping when prefers-reduced-motion is active', () => {
    matchMediaMock.mockImplementation((query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    const rafSpy = vi.spyOn(window, 'requestAnimationFrame')

    const { rerender } = render(<CelestialBackground workspace="briefing" />)

    // Should NOT request animation frames
    expect(rafSpy).not.toHaveBeenCalled()
    expect(fillRectMock).toHaveBeenCalled()

    // Updating props under reduced motion immediately re-renders static frame
    fillRectMock.mockClear()
    rerender(<CelestialBackground workspace="cortex" />)
    expect(fillRectMock).toHaveBeenCalled()
    expect(rafSpy).not.toHaveBeenCalled()
  })

  it('cleanly cancels animation frames and removes event listeners on unmount', () => {
    const cafSpy = vi.spyOn(window, 'cancelAnimationFrame')
    const removeWindowSpy = vi.spyOn(window, 'removeEventListener')
    const removeDocSpy = vi.spyOn(document, 'removeEventListener')

    const { unmount } = render(<CelestialBackground />)
    unmount()

    expect(cafSpy).toHaveBeenCalled()
    expect(removeWindowSpy).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(removeWindowSpy).toHaveBeenCalledWith('mousemove', expect.any(Function))
    expect(removeDocSpy).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
  })
})
