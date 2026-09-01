import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { VoiceSignalGlyph } from './VoiceSignalGlyph'

describe('VoiceSignalGlyph', () => {
  it('renders model display name when local model is loading', () => {
    render(
      <VoiceSignalGlyph
        step={null}
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
        step={null}
        status="idle"
        isSpeaking={false}
        isLocalModelLoading={true}
        loadingDisplayName={null}
      />,
    )
    expect(screen.getByText('Loading local model')).toBeVisible()
  })

  it('renders standby state when idle', () => {
    render(
      <VoiceSignalGlyph
        step={null}
        status="idle"
        isSpeaking={false}
      />,
    )
    expect(screen.getByText('Standby')).toBeVisible()
  })

  it('renders working state when querying Cortex', () => {
    render(
      <VoiceSignalGlyph
        step={null}
        status="idle"
        isSpeaking={false}
        isCortexQuerying={true}
      />,
    )
    expect(screen.getByText('Working')).toBeVisible()
  })
})
