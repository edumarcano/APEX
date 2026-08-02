import { Check, ChevronDown, Cloud, Cpu, Loader2 } from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
} from 'react'

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
  { key: 'acinonyx', description: 'Development-only privacy sandbox for testing Apex with masked personal context.', poweredBy: 'Gemini 3.5 Flash Lite', capabilities: ['Masked context', 'Apex Brave Search'] },
  { key: 'panthera', description: 'Default generalist for thoughtful answers, planning, and complex everyday work.', poweredBy: 'GPT-5.6 Luna', capabilities: ['Planning', 'Apex Brave Search'] },
  { key: 'neofelis', description: 'Fast research specialist with optional Google Search and Maps grounding.', poweredBy: 'Gemini 3.6 Flash', capabilities: ['Apex Brave Search', 'Google Search', 'Google Maps'] },
  { key: 'delphinus', description: 'Balanced live-information profile with optional X Search for current conversations and trends.', poweredBy: 'Grok 4.3', capabilities: ['X Search', 'Apex Brave Search'] },
  { key: 'orcinus', description: 'Deep-reasoning profile for difficult analysis, synthesis, and extended investigations.', poweredBy: 'Grok 4.5', capabilities: ['Apex Brave Search', 'X Search', 'Extended analysis'] },
]

const LOCAL_PROFILES: readonly ProfileDefinition[] = [
  { key: 'mus', description: 'Private on-device generalist for capable offline work without cloud processing.', poweredBy: 'Qwen3 4B Instruct · Runs locally through Ollama', capabilities: ['Private', 'Offline capable'] },
  { key: 'sorex', description: 'Lightweight on-device fallback for quick tasks on constrained systems.', poweredBy: 'Qwen3 1.7B · Runs locally through Ollama', capabilities: ['Low resource', 'Offline capable'] },
]

const STATUS_LABELS: Record<ProfileAvailabilityStatus, string> = {
  available: 'Available', busy: 'Busy', unknown: 'Checking availability', disabled: 'Unavailable',
  ollama_unreachable: 'Ollama unavailable', model_not_installed: 'Not installed',
  insufficient_ram: 'Insufficient memory', cpu_overloaded: 'CPU busy',
}

interface ProfileCardSelectorProps {
  activeProfile: AssistantProfile
  onChange: (profile: AssistantProfile) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  devModeActive: boolean
}

function profileMode(profile: AssistantProfile): AssistantMode {
  return profile === 'mus' || profile === 'sorex' ? 'local' : 'cloud'
}

function profileTitle(profile: AssistantProfile): string {
  return `APEX ${PROFILE_DISPLAY_NAMES[profile]}`
}

function statusClass(status: ProfileAvailabilityStatus): string {
  if (status === 'available') return 'text-emerald-300'
  if (status === 'unknown' || status === 'busy') return 'text-amber-200'
  return 'text-red-300'
}

export function ProfileCardSelector({
  activeProfile,
  onChange,
  profilesStatus,
  profilesStatusHydrated,
  devModeActive,
}: ProfileCardSelectorProps): ReactElement {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [browseMode, setBrowseMode] = useState<AssistantMode>(() => profileMode(activeProfile))
  const activeDefinition = [...CLOUD_PROFILES, ...LOCAL_PROFILES].find((profile) => profile.key === activeProfile)

  useEffect(() => {
    if (!isOpen) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      const target = event.target as Node
      if (!popoverRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setIsOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setIsOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    const focusTimer = window.setTimeout(() => {
      popoverRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
    }, 0)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
      window.clearTimeout(focusTimer)
    }
  }, [isOpen])

  const profiles = (browseMode === 'cloud' ? CLOUD_PROFILES : LOCAL_PROFILES).filter((profile) =>
    profile.key !== 'acinonyx' || (devModeActive && (!profilesStatusHydrated || profilesStatus.some((status) => status.key === 'acinonyx'))),
  )
  const activeStatus = profilesStatus.find((profile) => profile.key === activeProfile)
  const activeAvailability = profilesStatusHydrated ? activeStatus?.status ?? 'unknown' : 'unknown'

  const selectProfile = (profile: AssistantProfile): void => {
    onChange(profile)
    setIsOpen(false)
    window.setTimeout(() => triggerRef.current?.focus(), 0)
  }

  const handleTabKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>): void => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const nextMode: AssistantMode = browseMode === 'cloud' ? 'local' : 'cloud'
    setBrowseMode(nextMode)
    window.setTimeout(() => {
      popoverRef.current?.querySelector<HTMLButtonElement>(`button[role="tab"][data-mode="${nextMode}"]`)?.focus()
    }, 0)
  }

  const renderCard = (profile: ProfileDefinition, compact = false): ReactElement => {
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
        aria-label={`Use ${profileTitle(profile.key)}`}
        onClick={() => selectProfile(profile.key)}
        className={`w-full rounded-xl border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${selected ? 'border-[#7E22CE]/55 bg-[#7E22CE]/12' : 'border-white/10 bg-white/[0.02] hover:border-white/25 hover:bg-white/[0.04]'} ${!selectable ? 'cursor-not-allowed opacity-55' : ''}`}
      >
        <span className="flex items-start gap-3">
          <ProfileMark profile={profile.key} size={compact ? 'compact' : 'card'} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center justify-between gap-2">
              <span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{profileTitle(profile.key)}</span>
              {selected ? <Check className="size-4 shrink-0 text-[#39FF88]" aria-label="Selected" /> : null}
            </span>
            {!compact ? <span className="mt-1 block text-xs leading-relaxed text-zinc-400">{profile.description}</span> : null}
          </span>
        </span>
        <span className="mt-3 block border-t border-white/10 pt-2 font-mono text-[10px] text-zinc-400">Powered by {profile.poweredBy}</span>
        {!compact ? <span className="mt-2 flex flex-wrap items-center gap-1.5">
          {profile.capabilities.map((capability) => <span key={capability} className="rounded border border-white/10 bg-black/20 px-1.5 py-0.5 font-mono text-[9px] text-zinc-400">{capability}</span>)}
          <span className={`ml-auto inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider ${statusClass(availability)}`}>
            {availability === 'unknown' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}{STATUS_LABELS[availability]}
          </span>
        </span> : null}
        {!compact && !selectable && status?.reason ? <span className="mt-1 block text-[10px] text-red-200">{status.reason}</span> : null}
      </button>
    )
  }

  if (!activeDefinition) return <section aria-label="Profile selector" />

  return (
    <section aria-label="Profile selector" className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-controls="cortex-profile-popover"
        onClick={() => {
          setBrowseMode(profileMode(activeProfile))
          setIsOpen((open) => !open)
        }}
        className="w-full rounded-xl border border-[#7E22CE]/45 bg-[#7E22CE]/10 p-3 text-left transition-colors hover:border-[#C084FC]/65 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]"
      >
        <span className="flex items-center gap-3"><ProfileMark profile={activeProfile} size="card" /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{profileTitle(activeProfile)}</span><ChevronDown className={`size-4 shrink-0 text-[#D8B4FE] transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden /></span><span className="mt-1 block font-mono text-[10px] text-zinc-400">Powered by {activeDefinition.poweredBy}</span></span></span>
        <span className={`mt-2 block font-mono text-[9px] uppercase tracking-wider ${statusClass(activeAvailability)}`}>{STATUS_LABELS[activeAvailability]}</span>
      </button>

      {isOpen ? <div ref={popoverRef} id="cortex-profile-popover" role="dialog" aria-label="Select profile" className="absolute left-0 right-0 top-full z-40 mt-2 max-h-[min(62vh,38rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-3 shadow-2xl backdrop-blur-xl scrollbar-thin">
        <div className="grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-black/30 p-1" role="tablist" aria-label="Profile runtime">
          {([['cloud', Cloud, 'Cloud profiles'], ['local', Cpu, 'Local profiles']] as const).map(([mode, Icon, label]) => <button key={mode} data-mode={mode} type="button" role="tab" aria-selected={browseMode === mode} onClick={() => setBrowseMode(mode)} onKeyDown={handleTabKeyDown} className={`inline-flex items-center justify-center gap-1.5 rounded-md px-2 py-2 font-mono text-[10px] uppercase tracking-wider ${browseMode === mode ? mode === 'cloud' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'bg-[#78350F]/25 text-[#FDBA74]' : 'text-zinc-500 hover:text-zinc-300'}`}><Icon className="size-3.5" aria-hidden />{label}</button>)}
        </div>
        <div className="mt-3 space-y-2">{profiles.map((profile) => renderCard(profile))}</div>
      </div> : null}
    </section>
  )
}
