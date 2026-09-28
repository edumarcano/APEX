import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { VoiceSignalGlyph } from './VoiceSignalGlyph'

describe('VoiceSignalGlyph', () => {
  it('renders model display name when local model is loading', () => {
    render(
      <VoiceSignalGlyph
        status="idle"
        isSpeaking={false}
        isLocalModelLoading={true}
        loadingDisplayName="Gemma 4 E2B"
      />,
    )
    expect(screen.getByText('Loading Gemma 4 E2B')).toBeVisible()
  })

  it('falls back to local model label when loadingDisplayName is not provided', () => {
    render(
      <VoiceSignalGlyph
        status="idle"
        isSpeaking={false}
        isLocalModelLoading={true}
        loadingDisplayName={null}
      />,
    )
    expect(screen.getByText('Loading local model')).toBeVisible()
  })

  it('renders Ready when no work is active', () => {
    render(
      <VoiceSignalGlyph
        status="idle"
        isSpeaking={false}
      />,
    )
    expect(screen.getByText('Ready')).toBeVisible()
  })

  it('renders working state when querying Cortex', () => {
    render(
      <VoiceSignalGlyph
        status="idle"
        isSpeaking={false}
        isCortexQuerying={true}
      />,
    )
    expect(screen.getByText('Working')).toBeVisible()
  })

  it.each([
    ['preparing', 'Preparing briefing', 'emerald'],
    ['collecting', 'Collecting data', 'emerald'],
    ['selecting', 'Selecting evidence', 'emerald'],
    ['investigating', 'Investigating', 'purple'],
    ['synthesizing', 'Synthesizing', 'purple'],
    ['persisting', 'Saving briefing', 'gold'],
    ['briefing_ready', 'Briefing ready', 'gold'],
    ['speech_preparing', 'Preparing spoken highlights', 'purple'],
    ['speech_playing', 'Playing highlights', 'cyan'],
  ] as const)('renders the %s activity label and tone', (activity, label, tone) => {
    const { container } = render(
      <VoiceSignalGlyph status="loading" isSpeaking={activity === 'speech_playing'} activity={activity} />,
    )

    expect(screen.getByText(label)).toBeVisible()
    expect(container.querySelector('[data-signal-tone]')).toHaveAttribute('data-signal-tone', tone)
  })

  it('keeps the stage core label above Cortex activity and keeps model loading above both', () => {
    const { rerender } = render(
      <VoiceSignalGlyph status="loading" isSpeaking={false} isCortexQuerying activity="synthesizing" />,
    )
    expect(screen.getByText('Synthesizing')).toBeVisible()

    rerender(
      <VoiceSignalGlyph status="loading" isSpeaking={false} isCortexQuerying activity="synthesizing" isLocalModelLoading loadingDisplayName="Gemma 4 E2B" />,
    )
    expect(screen.getByText('Loading Gemma 4 E2B')).toBeVisible()
  })

  it('shows telemetry collection while a completed briefing is selected and returns to the ready label afterward', () => {
    const { rerender } = render(
      <VoiceSignalGlyph status="success" isSpeaking={false} activity="briefing_ready" isTelemetryCollecting />,
    )
    expect(screen.getByText('Collecting data')).toBeVisible()

    rerender(<VoiceSignalGlyph status="success" isSpeaking={false} activity="briefing_ready" />)
    expect(screen.getByText('Briefing ready')).toBeVisible()
  })
})
