import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { UseBriefingSpeechResult } from '../../hooks/useBriefingSpeech'
import type { BriefingSpeechState } from '../../types/briefings'
import { BriefingSpeechControl } from './BriefingSpeechControl'

function speech(
  status: BriefingSpeechState['status'],
  errorCode: string | null = status === 'unavailable' ? 'tts_unavailable' : null,
): BriefingSpeechState {
  return {
    session_id: 'session-1',
    artifact_sha256: 'artifact-digest',
    status,
    error_code: errorCode,
    engine: 'kokoro',
  }
}

function props(overrides: Partial<UseBriefingSpeechResult> & { voiceMode?: 'off' | 'manual' | 'automatic' } = {}) {
  return {
    speech: speech('not_requested'),
    isLoading: false,
    pendingAction: null,
    error: null,
    playbackCompleted: false,
    voiceEnabled: true,
    refresh: vi.fn(async () => undefined),
    prepare: vi.fn(async () => undefined),
    recreateAudio: vi.fn(async () => undefined),
    play: vi.fn(async () => undefined),
    stop: vi.fn(async () => undefined),
    voiceMode: 'manual' as const,
    ...overrides,
  }
}

describe('BriefingSpeechControl', () => {
  it('offers explicit preparation and describes speech accessibly', async () => {
    const user = userEvent.setup()
    const prepare = vi.fn(async () => undefined)
    render(<BriefingSpeechControl {...props({ prepare })} />)

    expect(screen.getByRole('region', { name: 'Spoken highlights' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('No spoken highlights are prepared.')
    await user.click(screen.getByRole('button', { name: 'Prepare highlights' }))
    expect(prepare).toHaveBeenCalledTimes(1)
  })

  it('identifies Google TTS without implying synthesis is local', () => {
    const googleSpeech = { ...speech('ready'), engine: 'google' as const }
    render(<BriefingSpeechControl {...props({ speech: googleSpeech })} />)

    expect(screen.getByText('Voice engine · Google TTS')).toBeInTheDocument()
    expect(screen.queryByText(/Local playback/)).not.toBeInTheDocument()
  })

  it('shows a preparation retry when speech is unavailable', async () => {
    const user = userEvent.setup()
    const prepare = vi.fn(async () => undefined)
    render(<BriefingSpeechControl {...props({ speech: speech('unavailable', 'tts_unavailable'), prepare })} />)

    expect(screen.getByRole('status')).toHaveTextContent('Spoken highlights are unavailable (tts_unavailable).')
    await user.click(screen.getByRole('button', { name: 'Retry preparation' }))
    expect(prepare).toHaveBeenCalledTimes(1)
  })

  it('keeps Play available after a playback failure and offers explicit audio recreation', async () => {
    const user = userEvent.setup()
    const play = vi.fn(async () => undefined)
    const recreateAudio = vi.fn(async () => undefined)
    render(<BriefingSpeechControl {...props({ speech: speech('ready', 'speaker_busy'), play, recreateAudio })} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Voice output is busy. Try playing again.')
    const playButton = screen.getByRole('button', { name: 'Play highlights' })
    expect(playButton).toBeEnabled()
    await user.click(playButton)
    await user.click(screen.getByRole('button', { name: 'Recreate audio' }))

    expect(play).toHaveBeenCalledTimes(1)
    expect(recreateAudio).toHaveBeenCalledTimes(1)
  })

  it('allows stopping existing playback while voice mode is off', async () => {
    const user = userEvent.setup()
    const stop = vi.fn(async () => undefined)
    render(<BriefingSpeechControl {...props({ speech: speech('playing'), voiceMode: 'off', voiceEnabled: false, stop })} />)

    expect(screen.getByRole('status')).toHaveTextContent('Voice mode is off. Spoken highlights are disabled.')
    await user.click(screen.getByRole('button', { name: 'Stop playback' }))
    expect(stop).toHaveBeenCalledTimes(1)
  })
})
