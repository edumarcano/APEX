import type { ReactElement } from 'react'
import { Info, Volume2 } from 'lucide-react'

import { SettingsCard, SettingsSelect } from '../SettingsControls'
import type { TtsEngine } from '../../types/telemetry'
import type {
  RuntimeSettings,
  SettingsEffectiveTiming,
  VoiceGender,
  VoiceMode,
} from '../../types/settings'

const ENGINE_OPTIONS: readonly { value: TtsEngine; label: string }[] = [
  { value: 'google', label: 'Google' },
  { value: 'pyttsx3', label: 'pyttsx3' },
  { value: 'kokoro', label: 'Kokoro' },
]

const GENDER_OPTIONS: readonly { value: VoiceGender; label: string }[] = [
  { value: 'female', label: 'Female' },
  { value: 'male', label: 'Male' },
]

const VOICE_MODE_OPTIONS: readonly { value: VoiceMode; label: string }[] = [
  { value: 'automatic', label: 'Automatic' },
  { value: 'manual', label: 'Manual' },
  { value: 'off', label: 'Off' },
]

interface VoiceAudioViewProps {
  titleId: string
  draft: RuntimeSettings
  setDraft: (updater: (prev: RuntimeSettings) => RuntimeSettings) => void
  voiceTiming: SettingsEffectiveTiming
}

export default function VoiceAudioView({
  titleId,
  draft,
  setDraft,
  voiceTiming,
}: VoiceAudioViewProps): ReactElement {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Speech Synthesis Card */}
      <SettingsCard
        id={`${titleId}-voice`}
        title="Voice"
        icon={Volume2}
        timing={voiceTiming}
        badgeText="Speech Synthesis"
      >
        <div className="space-y-3">
          <SettingsSelect
            id="settings-voice-mode"
            label="Mode"
            value={draft.voice.mode}
            options={VOICE_MODE_OPTIONS}
            timing={voiceTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                voice: { ...prev.voice, mode: next },
              }))
            }
          />
          <SettingsSelect
            id="settings-voice-engine"
            label="Engine"
            value={draft.voice.engine}
            options={ENGINE_OPTIONS}
            timing={voiceTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                voice: { ...prev.voice, engine: next },
              }))
            }
          />
          <SettingsSelect
            id="settings-voice-gender"
            label="Gender"
            value={draft.voice.gender}
            options={GENDER_OPTIONS}
            timing={voiceTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                voice: { ...prev.voice, gender: next },
              }))
            }
          />
        </div>
      </SettingsCard>

      {/* Operational Notes Card */}
      <SettingsCard
        id={`${titleId}-audio-notes`}
        title="Operational Notes"
        icon={Info}
        badgeText="Voice Architecture"
      >
        <div className="space-y-3 text-[11px] leading-relaxed text-zinc-400">
          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3 space-y-2">
            <h4 className="font-orbitron text-[10px] uppercase tracking-wider text-zinc-300">
              Synthesis Engines
            </h4>
            <ul className="space-y-1.5 list-disc list-inside text-zinc-400">
              <li>
                <span className="text-zinc-200 font-medium">Google:</span> Remote cloud speech service with natural cadence; requires internet connectivity.
              </li>
              <li>
                <span className="text-zinc-200 font-medium">pyttsx3:</span> System-native offline speech synthesizer (SAPI5 on Windows, NSSpeech on macOS, eSpeak on Linux).
              </li>
              <li>
                <span className="text-zinc-200 font-medium">Kokoro:</span> Lightweight neural speech model running locally for high-fidelity audio without cloud calls.
              </li>
            </ul>
          </div>

          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3 space-y-2">
            <h4 className="font-orbitron text-[10px] uppercase tracking-wider text-zinc-300">
              Playback Triggering
            </h4>
            <p>
              In <span className="text-zinc-200">Automatic</span> mode, APEX prepares and speaks executive briefings when generated. In <span className="text-zinc-200">Manual</span> mode, speech starts only on explicit user request. When set to <span className="text-zinc-200">Off</span>, voice synthesis is disabled entirely.
            </p>
          </div>
        </div>
      </SettingsCard>
    </div>
  )
}
