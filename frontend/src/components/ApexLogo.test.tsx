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
  it('travels a blue wave around the shell during synthesis', () => {
    const { container } = render(
      <ApexLogo
        status="loading"
        activity="synthesizing"
        outerShellActivity="wave"
      />,
    )

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--collection-surge')
    }
  })

  it('keeps the shell steady while investigating and uses the purple core surge', () => {
    const { container } = render(<ApexLogo status="loading" activity="investigating" hasCollectedTelemetry />)

    for (const segment of shellSegments(container)) {
      expect(segment).not.toHaveClass('apex-blue-metal--collection-surge')
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--purple-surge')
  })

  it('keeps a steady green core during evidence selection', () => {
    const { container } = render(<ApexLogo status="loading" activity="selecting" outerShellActivity="wave" />)

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--green-active')
    expect(container.querySelector('#gold-stage-1')).not.toHaveClass('apex-core-metal--purple-surge')
  })

  it('keeps a gold core during spoken playback while the shell stays steady', () => {
    const { container } = render(<ApexLogo status="success" activity="speech_playing" isSpeaking />)

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--gold-active')
    expect(container.querySelector('#gold-stage-1')).not.toHaveClass('apex-core-metal--speaking')
    for (const segment of shellSegments(container)) {
      expect(segment).not.toHaveClass('apex-blue-metal--collection-surge')
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
  })

  it('lets active telemetry refresh override the static completed core and shell', () => {
    const { container } = render(
      <ApexLogo status="success" activity="briefing_ready" isTelemetryCollecting outerShellActivity="wave" />,
    )

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--green-surge')
    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--collection-surge')
    }
  })

  it('keeps the stage core during local model loading while the shell uses its orange wave', () => {
    const { container } = render(
      <ApexLogo status="loading" activity="synthesizing" outerShellActivity="local_loading" />,
    )

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--purple-surge')
    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--rust-surge')
    }
  })

  it('fills the blue shell before usable telemetry has been collected', () => {
    const { container } = render(<ApexLogo status="idle" />)

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--breathing-dormant')
  })

  it('keeps shared shell behavior while showing cyan speech activity', () => {
    const { container } = render(
      <ApexLogo status="idle" isSpeaking />,
    )

    expect(container.querySelector('#gold-stage-1')).toHaveClass('apex-core-metal--speaking')
    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--active')
    }
  })

  it('returns to the collected idle shell after usable telemetry exists', () => {
    const { container } = render(
      <ApexLogo status="idle" hasCollectedTelemetry />,
    )

    for (const segment of shellSegments(container)) {
      expect(segment).toHaveClass('apex-blue-metal--base')
    }
  })
})
