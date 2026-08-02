import { Check, Cloud, Cpu, Loader2 } from 'lucide-react'
import { type ReactElement } from 'react'

import type {
  AgentProfileStatus,
  AssistantMode,
  AssistantProfile,
  ProfileAvailabilityStatus,
} from '../types/telemetry'

import { ProfileMark } from './ProfileMark'
import { PROFILE_DISPLAY_NAMES } from './profileIdentity'

interface ProfileDefinition {
  key: AssistantProfile
  description: string
  poweredBy: string
  capabilities: string[]
}

const CLOUD_PROFILES: readonly ProfileDefinition[] = [
  {
    key: 'acinonyx',
    description: 'Development-only privacy sandbox for testing Apex with masked personal context.',
    poweredBy: 'Gemini 3.5 Flash Lite',
    capabilities: ['Masked context', 'Apex Brave Search'],
  },
  {
    key: 'panthera',
    description: 'Default generalist for thoughtful answers, planning, and complex everyday work.',
    poweredBy: 'GPT-5.6 Luna',
    capabilities: ['Planning', 'Apex Brave Search'],
  },
  {
    key: 'neofelis',
    description: 'Fast research specialist with optional Google Search and Maps grounding.',
    poweredBy: 'Gemini 3.6 Flash',
    capabilities: ['Apex Brave Search', 'Google Search', 'Google Maps'],
  },
  {
    key: 'delphinus',
    description: 'Balanced live-information profile with optional X Search for current conversations and trends.',
    poweredBy: 'Grok 4.3',
    capabilities: ['X Search', 'Apex Brave Search'],
  },
  {
    key: 'orcinus',
    description: 'Deep-reasoning profile for difficult analysis, synthesis, and extended investigations.',
    poweredBy: 'Grok 4.5',
    capabilities: ['Apex Brave Search', 'X Search', 'Extended analysis'],
  },
]

const LOCAL_PROFILES: readonly ProfileDefinition[] = [
  {
    key: 'mus',
    description: 'Private on-device generalist for capable offline work without cloud processing.',
    poweredBy: 'Qwen3 4B Instruct · Runs locally through Ollama',
    capabilities: ['Private', 'Offline capable'],
  },
  {
    key: 'sorex',
    description: 'Lightweight on-device fallback for quick tasks on constrained systems.',
    poweredBy: 'Qwen3 1.7B · Runs locally through Ollama',
    capabilities: ['Low resource', 'Offline capable'],
  },
]

const STATUS_LABELS: Record<ProfileAvailabilityStatus, string> = {
  available: 'Available',
  busy: 'Busy',
  unknown: 'Checking availability',
  disabled: 'Unavailable',
  ollama_unreachable: 'Ollama unavailable',
  model_not_installed: 'Not installed',
  insufficient_ram: 'Insufficient memory',
  cpu_overloaded: 'CPU busy',
}

interface ProfileCardSelectorProps {
  activeProfile: AssistantProfile
  onChange: (profile: AssistantProfile) => void
  onModeChange: (mode: AssistantMode) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  devModeActive: boolean
}

function profileMode(profile: AssistantProfile): AssistantMode {
  return profile === 'mus' || profile === 'sorex' ? 'local' : 'cloud'
}

function statusClass(status: ProfileAvailabilityStatus): string {
  if (status === 'available') return 'text-emerald-300'
  if (status === 'unknown' || status === 'busy') return 'text-amber-200'
  return 'text-red-300'
}

export function ProfileCardSelector({
  activeProfile,
  onChange,
  onModeChange,
  profilesStatus,
  profilesStatusHydrated,
  devModeActive,
}: ProfileCardSelectorProps): ReactElement {
  const activeMode = profileMode(activeProfile)
  const profiles = activeMode === 'cloud' ? CLOUD_PROFILES : LOCAL_PROFILES
  const visibleProfiles = profiles.filter((profile) =>
    profile.key !== 'acinonyx' || (devModeActive && (!profilesStatusHydrated || profilesStatus.some((status) => status.key === 'acinonyx'))),
  )

  return (
    <section aria-label="Profile selector" className="space-y-3">
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-black/20 p-1" role="tablist" aria-label="Profile runtime">
        {([
          ['cloud', Cloud, 'Cloud profiles'],
          ['local', Cpu, 'Local profiles'],
        ] as const).map(([nextMode, Icon, label]) => (
          <button
            key={nextMode}
            type="button"
            role="tab"
            aria-selected={activeMode === nextMode}
            onClick={() => {
              onModeChange(nextMode)
            }}
            className={`inline-flex items-center justify-center gap-1.5 rounded-md px-2 py-2 font-mono text-[10px] uppercase tracking-wider ${activeMode === nextMode ? nextMode === 'cloud' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'bg-[#78350F]/25 text-[#FDBA74]' : 'text-zinc-500 hover:text-zinc-300'}`}
          >
            <Icon className="size-3.5" aria-hidden />{label}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {visibleProfiles.map((profile) => {
          const status = profilesStatus.find((item) => item.key === profile.key)
          const availability = profilesStatusHydrated ? status?.status ?? 'unknown' : 'unknown'
          const selected = profile.key === activeProfile
          const selectable = availability === 'available'
          return (
            <button
              key={profile.key}
              type="button"
              disabled={!selectable}
              aria-pressed={selected}
              aria-label={`Use ${PROFILE_DISPLAY_NAMES[profile.key]}`}
              onClick={() => onChange(profile.key)}
              className={`w-full rounded-xl border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${selected ? 'border-[#7E22CE]/55 bg-[#7E22CE]/12' : 'border-white/10 bg-white/[0.02] hover:border-white/25 hover:bg-white/[0.04]'} ${!selectable ? 'cursor-not-allowed opacity-55' : ''}`}
            >
              <span className="flex items-start gap-3">
                <ProfileMark profile={profile.key} size="card" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{PROFILE_DISPLAY_NAMES[profile.key]}</span>
                    {selected ? <Check className="size-4 shrink-0 text-[#39FF88]" aria-label="Selected" /> : null}
                  </span>
                  <span className="mt-1 block text-xs leading-relaxed text-zinc-400">{profile.description}</span>
                </span>
              </span>
              <span className="mt-3 block border-t border-white/10 pt-2 font-mono text-[10px] text-zinc-400">Powered by {profile.poweredBy}</span>
              <span className="mt-2 flex flex-wrap items-center gap-1.5">
                {profile.capabilities.map((capability) => <span key={capability} className="rounded border border-white/10 bg-black/20 px-1.5 py-0.5 font-mono text-[9px] text-zinc-400">{capability}</span>)}
                <span className={`ml-auto inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider ${statusClass(availability)}`}>
                  {availability === 'unknown' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
                  {STATUS_LABELS[availability]}
                </span>
              </span>
              {!selectable && status?.reason ? <span className="mt-1 block text-[10px] text-red-200">{status.reason}</span> : null}
            </button>
          )
        })}
      </div>
    </section>
  )
}
