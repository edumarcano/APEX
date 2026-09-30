import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import AssistantMarkdown from './AssistantMarkdown'

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
})
