import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'
import {
  Check,
  ChevronDown,
  Cloud,
  Cpu,
  type LucideIcon,
} from 'lucide-react'

import type {
  AgentProfileStatus,
  AssistantProfile,
  ProfileAvailabilityStatus,
} from '../types/telemetry'

interface ProfileOption {
  key: AssistantProfile
  label: string
  subtitle: string
}

const CLOUD_PROFILE_OPTIONS: readonly ProfileOption[] = [
  { key: 'comet', label: 'Apex Comet', subtitle: 'Fast' },
  { key: 'nova', label: 'Apex Nova', subtitle: 'Balanced' },
  { key: 'pulsar', label: 'Apex Pulsar', subtitle: 'Advanced' },
]

const LOCAL_PROFILE_OPTIONS: readonly ProfileOption[] = [
  { key: 'lynx', label: 'Apex Lynx', subtitle: 'Lightweight' },
  { key: 'acinonyx', label: 'Apex Acinonyx', subtitle: 'Balanced' },
  { key: 'neofelis', label: 'Apex Neofelis', subtitle: 'Heavy' },
]

const PROFILE_LABELS: Record<AssistantProfile, string> = {
  comet: 'Apex Comet',
  nova: 'Apex Nova',
  pulsar: 'Apex Pulsar',
  lynx: 'Apex Lynx',
  acinonyx: 'Apex Acinonyx',
  neofelis: 'Apex Neofelis',
}

const STATUS_FALLBACK_REASONS: Record<ProfileAvailabilityStatus, string> = {
  available: '',
  unknown: 'Checking profile availability…',
  disabled: 'Profile disabled in system settings',
  ollama_unreachable: 'Ollama daemon is unreachable',
  model_not_installed: 'Model is not installed locally',
  insufficient_ram: 'Insufficient RAM for this model',
  cpu_overloaded: 'CPU utilization exceeds threshold',
}

interface ProfileSection {
  title: string
  icon: LucideIcon
  options: readonly ProfileOption[]
}

const PROFILE_SECTIONS: readonly ProfileSection[] = [
  { title: 'Cloud Models', icon: Cloud, options: CLOUD_PROFILE_OPTIONS },
  { title: 'Local Models', icon: Cpu, options: LOCAL_PROFILE_OPTIONS },
]

interface CloudProfileSelectorProps {
  activeProfile: AssistantProfile
  onChange: (profile: AssistantProfile) => void
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  disabled?: boolean
}

function resolveProfileAvailability(
  key: AssistantProfile,
  profilesStatus: AgentProfileStatus[],
  profilesStatusHydrated: boolean,
): { status: ProfileAvailabilityStatus; reason: string | null } {
  if (!profilesStatusHydrated) {
    return { status: 'unknown', reason: 'Checking profile availability…' }
  }

  const entry = profilesStatus.find((profile) => profile.key === key)
  if (!entry) {
    return { status: 'unknown', reason: 'Profile status unavailable' }
  }
  return { status: entry.status, reason: entry.reason }
}

function resolveProfileMetadata(
  key: AssistantProfile,
  profilesStatus: AgentProfileStatus[],
): AgentProfileStatus | null {
  return profilesStatus.find((profile) => profile.key === key) ?? null
}

function resolveTooltipText(
  status: ProfileAvailabilityStatus,
  reason: string | null,
): string {
  if (reason && reason.trim().length > 0) {
    return reason
  }
  return STATUS_FALLBACK_REASONS[status] || status
}

function resolveStatusLedClass(status: ProfileAvailabilityStatus): string {
  if (status === 'available') return 'hud-led--live'
  if (status === 'unknown') return 'hud-led--loading'
  return 'hud-led--error'
}

function resolveCompactProfileLabel(profile: AssistantProfile): string {
  return PROFILE_LABELS[profile].replace(/^Apex\s+/, '')
}

function resolveProfileInitial(profile: AssistantProfile): string {
  return resolveCompactProfileLabel(profile).slice(0, 1).toUpperCase()
}

function resolveProfileProviderLabel(
  profile: AssistantProfile,
  profilesStatus: AgentProfileStatus[],
): string {
  const metadata = resolveProfileMetadata(profile, profilesStatus)
  if (metadata?.provider === 'ollama') return 'Local'
  if (metadata?.provider === 'gemini') return 'Cloud'
  return LOCAL_PROFILE_OPTIONS.some((option) => option.key === profile)
    ? 'Local'
    : 'Cloud'
}

function resolveProfileDescription(
  option: ProfileOption,
  metadata: AgentProfileStatus | null,
): string {
  const subtitle = option.subtitle.trim()
  const tier = metadata?.tier?.trim()
  if (!tier || tier.toLowerCase() === subtitle.toLowerCase()) {
    return subtitle
  }
  return `${subtitle} / ${tier}`
}

export function CloudProfileSelector({
  activeProfile,
  onChange,
  profilesStatus,
  profilesStatusHydrated,
  disabled = false,
}: CloudProfileSelectorProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false)
  const [dropdownStyle, setDropdownStyle] = useState<CSSProperties | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const closeDropdown = useCallback((): void => {
    setIsOpen(false)
  }, [])

  const updateDropdownPosition = useCallback((): void => {
    const trigger = triggerRef.current
    if (!trigger) {
      return
    }

    const rect = trigger.getBoundingClientRect()
    setDropdownStyle({
      bottom: window.innerHeight - rect.top + 8,
      maxWidth: 'calc(100vw - 24px)',
      right: Math.max(12, window.innerWidth - rect.right),
      width: '18rem',
    })
  }, [])

  const toggleDropdown = useCallback((): void => {
    if (disabled || !profilesStatusHydrated) {
      return
    }
    setIsOpen((prev) => !prev)
  }, [disabled, profilesStatusHydrated])

  const handleSelect = useCallback(
    (profile: AssistantProfile, isGated: boolean): void => {
      if (isGated) {
        return
      }
      onChange(profile)
      closeDropdown()
    },
    [closeDropdown, onChange],
  )

  const handleTriggerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDropdown()
        return
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        toggleDropdown()
      }
    },
    [closeDropdown, toggleDropdown],
  )

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const handlePointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }

      if (
        !containerRef.current?.contains(target) &&
        !dropdownRef.current?.contains(target)
      ) {
        closeDropdown()
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
    }
  }, [closeDropdown, isOpen])

  useLayoutEffect(() => {
    if (!isOpen) {
      return
    }

    updateDropdownPosition()

    window.addEventListener('resize', updateDropdownPosition)
    window.addEventListener('scroll', updateDropdownPosition, true)
    return () => {
      window.removeEventListener('resize', updateDropdownPosition)
      window.removeEventListener('scroll', updateDropdownPosition, true)
    }
  }, [isOpen, updateDropdownPosition])

  const selectorDisabled = disabled || !profilesStatusHydrated
  const activeProfileMetadata = resolveProfileMetadata(activeProfile, profilesStatus)
  const isActiveProfilePreview = activeProfileMetadata?.stability === 'preview'
  const { status: activeProfileStatus } = resolveProfileAvailability(
    activeProfile,
    profilesStatus,
    profilesStatusHydrated,
  )
  const activeProviderLabel = resolveProfileProviderLabel(activeProfile, profilesStatus)

  const renderOption = (option: ProfileOption): ReactElement => {
    const metadata = resolveProfileMetadata(option.key, profilesStatus)
    const { status, reason } = resolveProfileAvailability(
      option.key,
      profilesStatus,
      profilesStatusHydrated,
    )
    const isGated = status !== 'available'
    const isLoading = status === 'unknown'
    const isActive = option.key === activeProfile
    const tooltipText = resolveTooltipText(status, reason)
    const description = resolveProfileDescription(option, metadata)

    return (
      <li key={option.key} role="presentation" className="group/tooltip relative">
        <button
          type="button"
          role="option"
          aria-selected={isActive}
          aria-disabled={isGated}
          tabIndex={isGated ? -1 : 0}
          disabled={isGated}
          onClick={() => {
            handleSelect(option.key, isGated)
          }}
          onKeyDown={(event) => {
            if (isGated) {
              return
            }
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              handleSelect(option.key, isGated)
            }
            if (event.key === 'Escape') {
              event.preventDefault()
              closeDropdown()
            }
          }}
          className={[
            'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors',
            'focus-visible:outline-none',
            isGated
              ? 'cursor-not-allowed text-zinc-600 opacity-45 pointer-events-none'
              : [
                  'hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15',
                  isActive ? 'bg-[#0F4DB8]/12 ring-1 ring-[#0F4DB8]/25' : '',
                ].join(' '),
          ].join(' ')}
        >
          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] font-mono text-[10px] font-bold text-[#7EB3FF]">
            {resolveProfileInitial(option.key)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 items-center gap-2">
              <span className={`hud-led size-1.5 shrink-0 ${resolveStatusLedClass(status)}`} aria-hidden />
              <span className="truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">
                {option.label}
              </span>
            </span>
            <span className="mt-0.5 block truncate pl-3.5 text-[10px] text-zinc-500">
              {description}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-1.5">
            {metadata?.stability === 'preview' ? (
              <span className="shrink-0 rounded border border-amber-400/30 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-widest text-amber-300">
                Preview
              </span>
            ) : null}
            {isActive ? (
              <Check className="size-3.5 text-[#39FF88]" strokeWidth={2.25} aria-hidden />
            ) : null}
          </span>
        </button>

        {isGated ? (
          <span
            role="tooltip"
            className={[
              'pointer-events-none absolute right-full top-1/2 z-50 mr-2 -translate-y-1/2',
              'rounded-lg border border-white/10 bg-zinc-950/95 px-2.5 py-1.5',
              'font-mono text-[10px] whitespace-nowrap shadow-xl',
              isLoading ? 'text-zinc-400' : 'text-rose-400',
              'opacity-0 transition-opacity group-hover/tooltip:opacity-100',
            ].join(' ')}
          >
            {tooltipText}
          </span>
        ) : null}
      </li>
    )
  }

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        tabIndex={0}
        disabled={selectorDisabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-busy={!profilesStatusHydrated}
        aria-label={`Assistant profile: ${PROFILE_LABELS[activeProfile]}`}
        onClick={toggleDropdown}
        onKeyDown={handleTriggerKeyDown}
        className={[
          'hud-interactive-shell hud-glass flex items-center gap-2 rounded-full px-2.5 py-1.5',
          'font-mono text-[10px] uppercase tracking-wider text-zinc-200',
          'transition-colors hover-blue-subtle',
          'focus-visible:outline focus-visible:outline-2',
          'focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8]',
          selectorDisabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
        ].join(' ')}
      >
        <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-white/10 bg-[#0F4DB8]/15 text-[9px] font-bold text-[#7EB3FF]">
          {resolveProfileInitial(activeProfile)}
        </span>
        <span className={`hud-led size-1.5 shrink-0 ${resolveStatusLedClass(activeProfileStatus)}`} aria-hidden />
        <span className="whitespace-nowrap">{resolveCompactProfileLabel(activeProfile)}</span>
        <span className="hidden rounded-full border border-white/[0.06] bg-white/[0.04] px-1.5 py-0.5 text-[8px] tracking-[0.14em] text-zinc-500 sm:inline">
          {activeProviderLabel}
        </span>
        {isActiveProfilePreview ? (
          <span className="rounded border border-amber-400/30 bg-amber-500/10 px-1 py-0.5 text-[8px] text-amber-300">
            Preview
          </span>
        ) : null}
        <ChevronDown
          className={`size-3.5 shrink-0 text-[#0F4DB8] transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`}
          strokeWidth={2.25}
          aria-hidden
        />
      </button>

      {isOpen && dropdownStyle ? createPortal(
        <div
          ref={dropdownRef}
          style={dropdownStyle}
          className={[
            'hud-corner-brackets hud-glass hud-glass-solid fixed z-[100] overflow-visible',
            'rounded-xl border border-white/10 p-2 shadow-2xl',
          ].join(' ')}
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <ul role="listbox" aria-label="Select assistant profile">
            {PROFILE_SECTIONS.map((section, sectionIndex) => (
              <li key={section.title} role="presentation">
                {sectionIndex > 0 ? (
                  <div className="mx-2 border-t border-white/10" aria-hidden />
                ) : null}
                <div
                  className="flex items-center gap-2 px-2 py-1.5 font-mono text-[9px] uppercase tracking-widest text-zinc-500"
                  aria-hidden
                >
                  <section.icon className="size-3.5 text-zinc-600" aria-hidden />
                  {section.title}
                </div>
                <ul role="group" aria-label={section.title} className="space-y-1">
                  {section.options.map(renderOption)}
                </ul>
              </li>
            ))}
          </ul>
        </div>,
        document.body,
      ) : null}
    </div>
  )
}
