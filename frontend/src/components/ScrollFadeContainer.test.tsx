import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ScrollFadeContainer } from './ScrollFadeContainer'

describe('ScrollFadeContainer', () => {
  it('does not apply list-fade-mask when content does not overflow', () => {
    render(
      <ScrollFadeContainer as="ul" data-testid="scroll-container" className="h-40 overflow-y-auto">
        <li>Short item 1</li>
        <li>Short item 2</li>
      </ScrollFadeContainer>,
    )

    const element = screen.getByTestId('scroll-container')
    // By default in jsdom clientHeight and scrollHeight are 0 (no overflow)
    expect(element.className).not.toContain('list-fade-mask')
  })

  it('applies list-fade-mask when content overflows and user can scroll down', () => {
    render(
      <ScrollFadeContainer as="ul" data-testid="scroll-container" className="h-40 overflow-y-auto">
        <li>Item 1</li>
      </ScrollFadeContainer>,
    )

    const element = screen.getByTestId('scroll-container')

    // Simulate content overflow: scrollHeight (400) > clientHeight (100)
    Object.defineProperty(element, 'clientHeight', { configurable: true, value: 100 })
    Object.defineProperty(element, 'scrollHeight', { configurable: true, value: 400 })
    Object.defineProperty(element, 'scrollTop', { configurable: true, writable: true, value: 0 })

    act(() => {
      fireEvent.scroll(element)
    })

    expect(element.className).toContain('list-fade-mask')
  })

  it('removes list-fade-mask when user scrolls to the bottom of the container', () => {
    render(
      <ScrollFadeContainer as="div" data-testid="scroll-container" className="h-40 overflow-y-auto">
        <p>Paragraph content</p>
      </ScrollFadeContainer>,
    )

    const element = screen.getByTestId('scroll-container')

    Object.defineProperty(element, 'clientHeight', { configurable: true, value: 100 })
    Object.defineProperty(element, 'scrollHeight', { configurable: true, value: 400 })
    Object.defineProperty(element, 'scrollTop', { configurable: true, writable: true, value: 0 })

    act(() => {
      fireEvent.scroll(element)
    })
    expect(element.className).toContain('list-fade-mask')

    // Scroll to bottom (scrollTop = 300, scrollTop + clientHeight = 400 >= 398)
    element.scrollTop = 300
    act(() => {
      fireEvent.scroll(element)
    })
    expect(element.className).not.toContain('list-fade-mask')

    // Scroll back up slightly (scrollTop = 280, scrollTop + clientHeight = 380 < 398)
    element.scrollTop = 280
    act(() => {
      fireEvent.scroll(element)
    })
    expect(element.className).toContain('list-fade-mask')
  })
})
