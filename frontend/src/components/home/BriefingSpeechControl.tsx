import { LoaderCircle, Play, RotateCw, Square, Volume2 } from 'lucide-react'
import type { ReactElement } from 'react'

import type { UseBriefingSpeechResult } from '../../hooks/useBriefingSpeech'
import type { BriefingSpeechEngine } from '../../types/briefings'
import type { VoiceMode } from '../../types/settings'

type BriefingSpeechControlProps = Pick<UseBriefingSpeechResult,
  'speech' | 'isLoading' | 'pendingAction' | 'error' | 'playbackCompleted' | 'refresh' | 'prepare' | 'recreateAudio' | 'play' | 'stop'
> & {
  voiceMode: VoiceMode
}

function engineLabel(engine: BriefingSpeechEngine): string {
  switch (engine) {
    case 'google': return 'Google TTS'
    case 'kokoro': return 'Kokoro'
    case 'pyttsx3': return 'pyttsx3'
  }
}

function statusText(props: BriefingSpeechControlProps): string {
  if (props.voiceMode === 'off') return 'Voice mode is off. Spoken highlights are disabled.'
  if (props.isLoading && !props.speech) return 'Checking saved spoken highlights…'
  if (!props.speech) return 'Spoken highlights are unavailable.'
  switch (props.speech.status) {
    case 'not_requested': return 'No spoken highlights are prepared.'
    case 'preparing': return 'Preparing spoken highlights…'
    case 'ready':
      if (props.speech.error_code === 'speaker_busy') return 'Voice output is busy. Try playing again.'
      if (props.speech.error_code) return 'Playback failed. Play again to retry.'
      return props.playbackCompleted ? 'Playback complete.' : 'Spoken highlights are ready.'
    case 'unavailable': return `Spoken highlights are unavailable${props.speech.error_code ? ` (${props.speech.error_code})` : ''}.`
    case 'cancelled': return 'Speech preparation was cancelled.'
    case 'playing': return 'Playing spoken highlights…'
    case 'stopping': return 'Stopping spoken highlights…'
  }
}

function controlLabel(props: BriefingSpeechControlProps): string | null {
  if (props.pendingAction === 'prepare') return 'Preparing…'
  if (props.pendingAction === 'play') return 'Starting playback…'
  if (props.pendingAction === 'stop') return 'Stopping…'
  if (!props.speech) return props.error ? 'Retry status check' : null
  switch (props.speech.status) {
    case 'not_requested': return 'Prepare highlights'
    case 'preparing': return 'Cancel preparation'
    case 'ready': return 'Play highlights'
    case 'unavailable': return 'Retry preparation'
    case 'cancelled': return 'Prepare again'
    case 'playing': return 'Stop playback'
    case 'stopping': return null
  }
}

export function BriefingSpeechControl(props: BriefingSpeechControlProps): ReactElement {
  const label = controlLabel(props)
  const isStop = props.speech?.status === 'playing' || props.speech?.status === 'preparing'
  const actionBusy = props.pendingAction !== null
  const disabled = actionBusy || props.isLoading || (props.voiceMode === 'off' && !isStop)
  const playbackFailed = props.speech?.status === 'ready' && props.speech.error_code !== null
  const buttonAction = props.pendingAction === 'prepare' || props.pendingAction === 'play' || props.pendingAction === 'stop'
    ? null
    : isStop
      ? props.stop
      : props.speech?.status === 'ready'
        ? props.play
        : props.speech?.status === 'unavailable' || props.speech?.status === 'cancelled' || props.speech?.status === 'not_requested'
          ? props.prepare
          : props.error && !props.speech
            ? props.refresh
            : null
  return <section aria-label="Spoken highlights" className="flex w-full min-w-0 flex-wrap items-center gap-2 rounded-lg border border-cyan-300/15 bg-zinc-950/35 px-2.5 py-2">
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <Volume2 className={`size-3.5 shrink-0 ${props.speech?.status === 'playing' ? 'text-cyan-200' : 'text-zinc-400'}`} aria-hidden />
      <div className="min-w-0">
        <p className="font-orbitron text-[9px] uppercase tracking-[0.13em] text-zinc-300">Spoken highlights</p>
        <p className={`text-[10px] ${props.speech?.status === 'unavailable' || playbackFailed ? 'text-red-200' : 'text-zinc-400'}`} role={playbackFailed ? 'alert' : 'status'}>
          {props.pendingAction === 'prepare' ? 'Preparing spoken highlights…' : statusText(props)}
        </p>
        {props.error ? <p className="text-[10px] text-red-200" role="alert">{props.error}</p> : null}
        {(props.speech?.status === 'ready' || props.speech?.status === 'playing') && props.speech.engine ? <p className="truncate font-mono text-[9px] text-zinc-500">Voice engine · {engineLabel(props.speech.engine)}</p> : null}
      </div>
    </div>
    {label && buttonAction ? <button
      type="button"
      onClick={() => { void buttonAction() }}
      disabled={disabled}
      className="hud-command-surface inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-cyan-300/20 bg-cyan-950/20 px-2.5 py-1.5 font-orbitron text-[9px] uppercase tracking-[0.1em] text-cyan-100 hover:border-cyan-200/50 hover:bg-cyan-950/35 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#A5F3FC] disabled:cursor-not-allowed disabled:opacity-45"
    >
      {props.pendingAction ? <LoaderCircle className="size-3 animate-spin motion-reduce:animate-none" aria-hidden /> : isStop ? <Square className="size-3" aria-hidden /> : props.speech?.status === 'ready' ? <Play className="size-3" aria-hidden /> : props.error && !props.speech ? <RotateCw className="size-3" aria-hidden /> : <Volume2 className="size-3" aria-hidden />}
      {label}
    </button> : null}
    {props.speech?.status === 'ready' && props.pendingAction === null ? <button
      type="button"
      onClick={() => { void props.recreateAudio() }}
      disabled={props.isLoading || props.voiceMode === 'off'}
      className="min-h-9 shrink-0 rounded-md border border-white/10 px-2.5 py-1.5 font-orbitron text-[9px] uppercase tracking-[0.1em] text-zinc-300 hover:border-cyan-200/40 hover:text-cyan-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#A5F3FC] disabled:cursor-not-allowed disabled:opacity-45"
    >Recreate audio</button> : null}
  </section>
}
