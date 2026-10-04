import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AssistantMarkdown from './AssistantMarkdown'

const platform = vi.hoisted(() => ({
  isNativeDesktop: vi.fn(() => true),
  openExternal: vi.fn<(...args: string[]) => Promise<void>>().mockResolvedValue(undefined),
}))
vi.mock('../platform/services', () => platform)

beforeEach(() => {
  platform.openExternal.mockClear()
  platform.isNativeDesktop.mockReturnValue(true)
})

describe('AssistantMarkdown', () => {
  it('renders the default assistant answer with GitHub Flavored Markdown', () => {
    render(<AssistantMarkdown text={'| Task | Status |\n| --- | --- |\n| Review | ~~pending~~ done |\n\n- [x] Verified'} />)

    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('pending').tagName).toBe('DEL')
    expect(screen.getByRole('checkbox')).toBeChecked()
  })

  it('keeps raw HTML inert', () => {
    const { container } = render(<AssistantMarkdown text={'<img src="x" onerror="alert(1)" />'} />)

    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(container.querySelector('[onerror]')).not.toBeInTheDocument()
  })

  it('routes safe assistant external links to the native opener', () => {
    render(<AssistantMarkdown text="[Source](https://example.com/report)" />)
    const link = screen.getByRole('link', { name: 'Source' })
    link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(platform.openExternal).toHaveBeenCalledWith('https://example.com/report')
  })

  it('keeps same-page and relative downloads as normal links', () => {
    const { rerender } = render(<AssistantMarkdown text="[Section](#details)" />)
    const hashLink = screen.getByRole('link', { name: 'Section' })
    expect(hashLink).toHaveAttribute('href', '#details')
    expect(platform.openExternal).not.toHaveBeenCalled()

    rerender(<AssistantMarkdown text="[Local](./report.pdf)" />)
    expect(screen.getByRole('link', { name: 'Local' })).toHaveAttribute('href', './report.pdf')
  })

  it('does not render unsafe or scheme-relative destinations as links', () => {
    const { rerender } = render(<AssistantMarkdown text="[Unsafe](javascript:alert%281%29)" />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    rerender(<AssistantMarkdown text="[Remote](//example.com/path)" />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
