import { Check, ChevronDown, Cloud, Cpu, Loader2, ShieldCheck } from 'lucide-react'
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
} from 'react'

import type { AgentProfileStatus, AssistantMode, AssistantProfile, ProfileAvailabilityStatus } from '../types/telemetry'

import { ProfileMark } from './ProfileMark'

interface ProfileCardSelectorProps {
  activeProfile: AssistantProfile
  onChange: (profile: AssistantProfile) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  devModeActive: boolean
  isQuerying: boolean
  verifyingProfile: AssistantProfile | null
  onVerify: (profile: Exclude<AssistantProfile, 'mus' | 'sorex'>) => Promise<boolean>
}

const STATUS_LABELS: Record<ProfileAvailabilityStatus, string> = {
  available: 'Available', busy: 'Busy', configured: 'Configured', verifying: 'Verifying access',
  verified: 'Verified', unauthorized: 'Access denied', model_unavailable: 'Model unavailable',
  rate_limited: 'Rate limited', quota_exhausted: 'Quota exhausted', billing_blocked: 'Billing blocked',
  provider_unreachable: 'Provider unreachable', provider_error: 'Provider error', unknown: 'Checking availability',
  disabled: 'Unavailable', ollama_unreachable: 'Ollama unavailable', model_not_installed: 'Not installed',
  insufficient_ram: 'Insufficient memory', cpu_overloaded: 'CPU busy',
}

function profileMode(profile: AssistantProfile): AssistantMode {
  return profile === 'mus' || profile === 'sorex' ? 'local' : 'cloud'
}

function fallbackName(profile: AssistantProfile): string {
  return `APEX ${profile.slice(0, 1).toUpperCase()}${profile.slice(1)}`
}

function formatModel(model: string): string {
  return model
    .replace(/^gpt-(\d+\.\d+)-(.+)$/i, (_, version: string, variant: string) => `GPT-${version} ${variant}`)
    .replace(/^gemini-(\d+\.\d+)-(.+)$/i, (_, version: string, variant: string) => `Gemini ${version} ${variant}`)
    .replace(/^grok-(\d+\.\d+)$/i, (_, version: string) => `Grok ${version}`)
    .replace(/^qwen(\d+):(\d+)b-(.+)$/i, (_, generation: string, size: string, variant: string) => `Qwen${generation} ${size}B ${variant}`)
    .split(/[-\s]/)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(' ')
}

function poweredBy(profile: AgentProfileStatus): string {
  const suffix = profile.provider === 'ollama' ? ' · Runs locally through Ollama' : ''
  return `Powered by ${formatModel(profile.configured_model)}${suffix}`
}

function statusClass(status: ProfileAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') return 'text-emerald-300'
  if (status === 'unknown' || status === 'busy' || status === 'verifying' || status === 'rate_limited') return 'text-amber-200'
  return 'text-red-300'
}

function rate(value: number): string { return `$${value.toFixed(2)}/1M` }

export function ProfileCardSelector({
  activeProfile, onChange, profilesStatus, profilesStatusHydrated, devModeActive,
  isQuerying, verifyingProfile, onVerify,
}: ProfileCardSelectorProps): ReactElement {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [browseMode, setBrowseMode] = useState<AssistantMode>(() => profileMode(activeProfile))
  const activeStatus = profilesStatus.find((profile) => profile.key === activeProfile)

  const profiles = useMemo(() => profilesStatus
    .filter((profile) => profile.mode === browseMode)
    .filter((profile) => profile.key !== 'acinonyx' || devModeActive)
    .sort((left, right) => left.sort_order - right.sort_order), [browseMode, devModeActive, profilesStatus])

  useEffect(() => {
    if (!isOpen) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      const target = event.target as Node
      if (!popoverRef.current?.contains(target) && !triggerRef.current?.contains(target)) setIsOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setIsOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    const focusTimer = window.setTimeout(() => popoverRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus(), 0)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
      window.clearTimeout(focusTimer)
    }
  }, [isOpen])

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
    window.setTimeout(() => popoverRef.current?.querySelector<HTMLButtonElement>(`button[role="tab"][data-mode="${nextMode}"]`)?.focus(), 0)
  }

  const renderCard = (profile: AgentProfileStatus): ReactElement => {
    const selected = profile.key === activeProfile
    const isCloud = profile.mode === 'cloud'
    const selectable = isCloud ? profile.status !== 'disabled' : profile.status === 'available'
    const verifyPending = verifyingProfile === profile.key || profile.status === 'verifying'
    return <article key={profile.key} className={`rounded-xl border p-3 ${selected ? 'border-[#7E22CE]/55 bg-[#7E22CE]/12' : 'border-white/10 bg-white/[0.02]'}`}>
      <button type="button" disabled={!selectable} aria-pressed={selected} aria-label={`Use ${profile.display_name}`} onClick={() => selectProfile(profile.key)} className={`w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${!selectable ? 'cursor-not-allowed opacity-55' : ''}`}>
        <span className="flex items-start gap-3"><ProfileMark profile={profile.key} size="card" /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{profile.display_name}</span>{selected ? <Check className="size-4 shrink-0 text-[#39FF88]" aria-label="Selected" /> : null}</span><span className="mt-1 block text-xs leading-relaxed text-zinc-400">{profile.description}</span></span></span>
        <span className="mt-3 block border-t border-white/10 pt-2 font-mono text-[10px] text-zinc-400">{poweredBy(profile)}</span>
        <span className="mt-2 flex flex-wrap items-center gap-1.5">{profile.capabilities.map((capability) => <span key={capability} className="rounded border border-white/10 bg-black/20 px-1.5 py-0.5 font-mono text-[9px] text-zinc-400">{capability}</span>)}<span className={`ml-auto inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider ${statusClass(profile.status)}`}>{profile.status === 'unknown' || verifyPending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}{STATUS_LABELS[profile.status]}</span></span>
      </button>
      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-white/10 pt-2"><span className="font-mono text-[9px] text-zinc-500">{profile.pricing.billing_basis === 'free_tier' ? 'Free tier' : profile.pricing.billing_basis === 'local' ? 'No provider token charge' : `In ${rate(profile.pricing.input_per_million)} · Out ${rate(profile.pricing.output_per_million)}`}</span>{profile.pricing.long_context_threshold_tokens ? <span className="font-mono text-[9px] text-zinc-600">Higher long-context rates may apply</span> : null}{isCloud ? <button type="button" disabled={!selectable || Boolean(verifyingProfile) || isQuerying} onClick={() => void onVerify(profile.key as Exclude<AssistantProfile, 'mus' | 'sorex'>)} className="ml-auto inline-flex items-center gap-1 rounded border border-white/10 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/55 hover:text-white disabled:cursor-not-allowed disabled:opacity-45"><ShieldCheck className="size-3" aria-hidden />{verifyPending ? 'Verifying' : 'Verify access'}</button> : null}</div>
      {profile.reason ? <p className="mt-2 text-[10px] text-red-200">{profile.reason}</p> : null}
    </article>
  }

  const activeAvailability = activeStatus?.status ?? 'unknown'
  const activeName = activeStatus?.display_name ?? fallbackName(activeProfile)
  if (!profilesStatusHydrated && !activeStatus) {
    return <section aria-label="Profile selector" className="rounded-xl border border-white/10 bg-white/[0.02] p-3 font-mono text-[10px] text-zinc-500">Loading profile catalog…</section>
  }
  return <section aria-label="Profile selector" className="relative">
    <button ref={triggerRef} type="button" aria-expanded={isOpen} aria-haspopup="dialog" aria-controls="cortex-profile-popover" onClick={() => { setBrowseMode(profileMode(activeProfile)); setIsOpen((open) => !open) }} className="w-full rounded-xl border border-[#7E22CE]/45 bg-[#7E22CE]/10 p-3 text-left transition-colors hover:border-[#C084FC]/65 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]"><span className="flex items-center gap-3"><ProfileMark profile={activeProfile} size="card" /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="font-orbitron text-xs font-semibold uppercase tracking-[0.12em] text-white">{activeName}</span><ChevronDown className={`size-4 shrink-0 text-[#D8B4FE] transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden /></span>{activeStatus ? <span className="mt-1 block font-mono text-[10px] text-zinc-400">{poweredBy(activeStatus)}</span> : null}</span></span><span className={`mt-2 block font-mono text-[9px] uppercase tracking-wider ${statusClass(activeAvailability)}`}>{STATUS_LABELS[activeAvailability]}</span></button>
    {isOpen ? <div ref={popoverRef} id="cortex-profile-popover" role="dialog" aria-label="Select profile" className="absolute left-0 right-0 top-full z-40 mt-2 max-h-[min(62vh,38rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-3 shadow-2xl backdrop-blur-xl scrollbar-thin"><div className="grid grid-cols-2 gap-1 rounded-lg border border-white/10 bg-black/30 p-1" role="tablist" aria-label="Profile runtime">{([['cloud', Cloud, 'Cloud profiles'], ['local', Cpu, 'Local profiles']] as const).map(([mode, Icon, label]) => <button key={mode} data-mode={mode} type="button" role="tab" aria-selected={browseMode === mode} onClick={() => setBrowseMode(mode)} onKeyDown={handleTabKeyDown} className={`inline-flex items-center justify-center gap-1.5 rounded-md px-2 py-2 font-mono text-[10px] uppercase tracking-wider ${browseMode === mode ? mode === 'cloud' ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'bg-[#78350F]/25 text-[#FDBA74]' : 'text-zinc-500 hover:text-zinc-300'}`}><Icon className="size-3.5" aria-hidden />{label}</button>)}</div><div className="mt-3 space-y-2">{profiles.map(renderCard)}</div></div> : null}
  </section>
}
