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

  it('fills the blue shell before usable telemetry has been collected', () => {
    const { container } = render(<ApexLogo step={null} status="idle" />)

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--breathing-dormant')
  })

  it('keeps shared shell behavior while showing cyan speech activity', () => {
    const { container } = render(
      <ApexLogo step={null} status="idle" isSpeaking />,
    )

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--speaking')
    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
  })

  it('returns to the collected idle shell after usable telemetry exists', () => {
    const { container } = render(
      <ApexLogo step={null} status="idle" hasCollectedTelemetry />,
    )

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--base')
    }
  })
})
