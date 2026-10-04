import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ExternalAnchor } from './ExternalAnchor'
import { safeExternalUrl } from '../lib/externalLinks'

const platform = vi.hoisted(() => ({
  isNativeDesktop: vi.fn(() => false),
  openExternal: vi.fn<(...args: string[]) => Promise<void>>().mockResolvedValue(undefined),
}))

vi.mock('../platform/services', () => platform)

beforeEach(() => {
  platform.openExternal.mockClear()
  platform.isNativeDesktop.mockReturnValue(false)
})

describe('external links', () => {
  it('accepts only absolute HTTP(S) URLs without credentials or control characters', () => {
    expect(safeExternalUrl('https://example.com/path')).toBe('https://example.com/path')
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull()
    expect(safeExternalUrl('https://user:pass@example.com')).toBeNull()
    expect(safeExternalUrl('https://example.com/\npath')).toBeNull()
    expect(safeExternalUrl('//example.com/path')).toBeNull()
  })

  it('keeps ordinary browser link behavior', () => {
    platform.isNativeDesktop.mockReturnValue(false)
    render(<ExternalAnchor href="https://example.com" target="_blank">Open</ExternalAnchor>)
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('target', '_blank')
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

  it('opens native middle clicks and reports opener failures accessibly', async () => {
    platform.isNativeDesktop.mockReturnValue(true)
    platform.openExternal.mockRejectedValueOnce(new Error('native failure'))
    render(<ExternalAnchor href="https://example.com">Open</ExternalAnchor>)
    const link = screen.getByRole('link', { name: 'Open' })
    const event = new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 })
    link.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not open link.')
  })

  it('preserves browser modifier clicks and download attributes', () => {
    platform.isNativeDesktop.mockReturnValue(false)
    let receivedModifier = false
    let wasAlreadyPrevented = true
    const { rerender } = render(<ExternalAnchor href="https://example.com" onClick={(event) => { receivedModifier = event.ctrlKey; wasAlreadyPrevented = event.defaultPrevented; event.preventDefault() }}>Open</ExternalAnchor>)
    const modifierEvent = new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true })
    screen.getByRole('link', { name: 'Open' }).dispatchEvent(modifierEvent)
    expect(receivedModifier).toBe(true)
    expect(wasAlreadyPrevented).toBe(false)
    expect(platform.openExternal).not.toHaveBeenCalled()

    platform.isNativeDesktop.mockReturnValue(true)
    rerender(<ExternalAnchor href="https://example.com/file" download="file">Download</ExternalAnchor>)
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('download', 'file')
    expect(platform.openExternal).not.toHaveBeenCalled()
  })

  it('does not render invalid destinations as links', () => {
    render(<ExternalAnchor href="file:///private/data">Open</ExternalAnchor>)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('Open').tagName).toBe('SPAN')
  })
})
