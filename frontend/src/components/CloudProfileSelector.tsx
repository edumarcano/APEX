import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

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
  { key: 'acinonyx', label: 'Apex Acinonyx', subtitle: 'Fast' },
  { key: 'neofelis', label: 'Apex Neofelis', subtitle: 'Capable' },
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
  disabled: 'Profile disabled in system settings',
  ollama_unreachable: 'Ollama daemon is unreachable',
  model_not_installed: 'Model is not installed locally',
  insufficient_ram: 'Insufficient RAM for this model',
  cpu_overloaded: 'CPU utilization exceeds threshold',
}

interface ProfileSection {
  title: string
  options: readonly ProfileOption[]
}

const PROFILE_SECTIONS: readonly ProfileSection[] = [
  { title: 'Cloud Models', options: CLOUD_PROFILE_OPTIONS },
  { title: 'Local Models', options: LOCAL_PROFILE_OPTIONS },
]

interface CloudProfileSelectorProps {
  activeProfile: AssistantProfile
  onChange: (profile: AssistantProfile) => void
  profilesStatus: AgentProfileStatus[]
  disabled?: boolean
}

function resolveProfileAvailability(
  key: AssistantProfile,
  profilesStatus: AgentProfileStatus[],
): { status: ProfileAvailabilityStatus; reason: string | null } {
  const entry = profilesStatus.find((profile) => profile.key === key)
  if (!entry) {
    return { status: 'available', reason: null }
  }
  return { status: entry.status, reason: entry.reason }
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

export function CloudProfileSelector({
  activeProfile,
  onChange,
  profilesStatus,
  disabled = false,
}: CloudProfileSelectorProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const closeDropdown = useCallback((): void => {
    setIsOpen(false)
  }, [])

  const toggleDropdown = useCallback((): void => {
    if (disabled) {
      return
    }
    setIsOpen((prev) => !prev)
  }, [disabled])

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

      if (!containerRef.current?.contains(target)) {
        closeDropdown()
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
    }
  }, [closeDropdown, isOpen])

  const renderOption = (option: ProfileOption): ReactElement => {
    const { status, reason } = resolveProfileAvailability(option.key, profilesStatus)
    const isGated = status !== 'available'
    const isActive = option.key === activeProfile
    const tooltipText = resolveTooltipText(status, reason)

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
            'flex w-full flex-col items-start px-3 py-2 text-left transition-colors',
            'focus-visible:outline-none',
            isGated
              ? 'cursor-not-allowed text-zinc-600 opacity-40 pointer-events-none'
              : [
                  'hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15',
                  isActive ? 'bg-[#0F4DB8]/10' : '',
                ].join(' '),
          ].join(' ')}
        >
          <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-100">
            {option.label}
          </span>
          <span className="text-[10px] text-zinc-500">{option.subtitle}</span>
        </button>

        {isGated ? (
          <span
            role="tooltip"
            className={[
              'pointer-events-none absolute right-full top-1/2 z-50 mr-2 -translate-y-1/2',
              'rounded-lg border border-white/10 bg-zinc-950/95 px-2.5 py-1.5',
              'font-mono text-[10px] whitespace-nowrap text-rose-400 shadow-xl',
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
        type="button"
        tabIndex={0}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={`Assistant profile: ${PROFILE_LABELS[activeProfile]}`}
        onClick={toggleDropdown}
        onKeyDown={handleTriggerKeyDown}
        className={[
          'flex items-center gap-1 rounded-lg border bg-black/40 px-2.5 py-1.5',
          'font-mono text-[10px] uppercase tracking-wider text-zinc-200',
          'border-white/10 transition-colors',
          'hover:border-[#0F4DB8]/40 focus-visible:outline focus-visible:outline-2',
          'focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8]',
          disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
        ].join(' ')}
      >
        <span className="whitespace-nowrap">{PROFILE_LABELS[activeProfile]}</span>
        <span className="text-[#0F4DB8]" aria-hidden>
          ▼
        </span>
      </button>

      {isOpen ? (
        <ul
          role="listbox"
          aria-label="Select assistant profile"
          className={[
            'absolute bottom-full right-0 z-50 mb-2 min-w-[12rem] overflow-visible',
            'rounded-lg border border-white/10 bg-zinc-950/95 shadow-2xl backdrop-blur-md',
          ].join(' ')}
        >
          {PROFILE_SECTIONS.map((section, sectionIndex) => (
            <li key={section.title} role="presentation">
              {sectionIndex > 0 ? (
                <div className="mx-2 border-t border-white/10" aria-hidden />
              ) : null}
              <div
                className="px-3 py-1.5 font-mono text-[9px] uppercase tracking-widest text-zinc-500"
                aria-hidden
              >
                {section.title}
              </div>
              <ul role="group" aria-label={section.title}>
                {section.options.map(renderOption)}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
