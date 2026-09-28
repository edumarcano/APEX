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

  it('keeps the shell and warm core visibly on for a resting identity', () => {
    const { container } = render(
      <ApexLogo step={null} status="idle" isRestingIdentity />,
    )

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--resting')
    }
    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--resting')
  })

  it('shows cyan speech activity over the resting core', () => {
    const { container } = render(
      <ApexLogo step={null} status="idle" isRestingIdentity isSpeaking />,
    )

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--speaking')
    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--resting')
    }
  })
})
