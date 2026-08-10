import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ApexLogo } from './ApexLogo'

function shellSegments(container: HTMLElement): SVGPathElement[] {
  return [
    'blue-crown-top',
    'blue-upper-left',
    'blue-upper-right',
    'blue-lower-left',
    'blue-lower-right',
    'blue-base-left',
    'blue-base-right',
  ].map((id) => {
    const segment = container.querySelector<SVGPathElement>(`#${id}`)
    if (!segment) throw new Error(`Missing shell segment ${id}`)
    return segment
  })
}

describe('ApexLogo shell behavior', () => {
  it('keeps every shell segment dim while idle', () => {
    const { container } = render(<ApexLogo step={null} status="idle" />)

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--base')
    }
  })

  it('uses the blue collection wave instead of cumulative activation', () => {
    const { container } = render(
      <ApexLogo
        step={2}
        status="loading"
        outerShellActivity="collection"
      />,
    )

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--collection-surge')
    }
  })

  it('fully lights the shell during synthesis', () => {
    const { container } = render(
      <ApexLogo
        step={3}
        status="loading"
        outerShellActivity="synthesis"
      />,
    )

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
  })
})
