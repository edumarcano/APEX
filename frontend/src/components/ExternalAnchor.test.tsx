import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ExternalAnchor } from './ExternalAnchor'
import { safeExternalUrl } from '../lib/externalLinks'

const platform = vi.hoisted(() => ({
  isNativeDesktop: vi.fn(() => false),
  openExternal: vi.fn<(...args: string[]) => Promise<void>>().mockResolvedValue(undefined),
}))

vi.mock('../platform/services', () => platform)

describe('external links', () => {
  it('accepts only absolute HTTP(S) URLs without credentials or control characters', () => {
    expect(safeExternalUrl('https://example.com/path')).toBe('https://example.com/path')
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull()
    expect(safeExternalUrl('https://user:pass@example.com')).toBeNull()
    expect(safeExternalUrl('https://example.com/\npath')).toBeNull()
  })

  it('keeps ordinary browser link behavior', () => {
    platform.isNativeDesktop.mockReturnValue(false)
    render(<ExternalAnchor href="https://example.com" target="_blank">Open</ExternalAnchor>)
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('target', '_blank')
    fireEvent.click(screen.getByRole('link', { name: 'Open' }))
    expect(platform.openExternal).not.toHaveBeenCalled()
  })

  it('routes valid native clicks through the desktop opener', () => {
    platform.isNativeDesktop.mockReturnValue(true)
    render(<ExternalAnchor href="https://example.com">Open</ExternalAnchor>)
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    screen.getByRole('link', { name: 'Open' }).dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(platform.openExternal).toHaveBeenCalledWith('https://example.com/')
  })

  it('does not render invalid destinations as links', () => {
    render(<ExternalAnchor href="file:///private/data">Open</ExternalAnchor>)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('Open').tagName).toBe('SPAN')
  })
})
