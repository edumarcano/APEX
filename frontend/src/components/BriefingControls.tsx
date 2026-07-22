import {
  Check,
  ChevronDown,
  Cloud,
  Cpu,
  FileText,
  RefreshCw,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
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

import type { BriefingMode } from '../types/settings'
import type {
  AgentProfileStatus,
  AssistantProfile,
  ProfileAvailabilityStatus,
} from '../types/telemetry'

interface BriefingOption {
  key: BriefingMode
  label: string
  description: string
}

const CLOUD_OPTIONS: readonly BriefingOption[] = [
  { key: 'comet', label: 'Comet', description: 'Full briefing · fast cloud synthesis' },
]

const LOCAL_OPTIONS: readonly BriefingOption[] = [
  { key: 'lynx', label: 'Lynx', description: 'Quick briefing · limited telemetry' },
  { key: 'acinonyx', label: 'Acinonyx', description: 'Full briefing · balanced synthesis' },
  { key: 'neofelis', label: 'Neofelis', description: 'Full briefing · higher capacity, slower' },
  {
    key: 'structured_digest',
    label: 'Structured Digest',
    description: 'Structured facts · no model or synthesis',
  },
]
const ALL_OPTIONS = [...CLOUD_OPTIONS, ...LOCAL_OPTIONS] as const

const SECTIONS: readonly {
  title: string
  icon: LucideIcon
  options: readonly BriefingOption[]
}[] = [
  { title: 'Cloud', icon: Cloud, options: CLOUD_OPTIONS },
  { title: 'Local', icon: Cpu, options: LOCAL_OPTIONS },
]

const MODE_LABELS: Record<BriefingMode, string> = {
  comet: 'Comet',
  lynx: 'Lynx',
  acinonyx: 'Acinonyx',
  neofelis: 'Neofelis',
  structured_digest: 'Structured',
}

const STATUS_REASONS: Record<ProfileAvailabilityStatus, string> = {
  available: '',
  busy: 'Local inference is currently busy',
  unknown: 'Checking mode availability…',
  disabled: 'Mode disabled in system settings',
  ollama_unreachable: 'Ollama daemon is unreachable',
  model_not_installed: 'Model is not installed locally',
  insufficient_ram: 'Current memory pressure exceeds threshold',
  cpu_overloaded: 'Current CPU utilization exceeds threshold',
}

interface ModeAvailability {
  status: ProfileAvailabilityStatus
  reason: string | null
}

function profileForMode(mode: BriefingMode): AssistantProfile | null {
  return mode === 'structured_digest' ? null : mode
}

function resolveBriefingModeAvailability(
  mode: BriefingMode,
  profiles: AgentProfileStatus[],
  hydrated: boolean,
): ModeAvailability {
  if (mode === 'structured_digest') {
    return { status: 'available', reason: null }
  }
  if (!hydrated) {
    return { status: 'unknown', reason: STATUS_REASONS.unknown }
  }
  const profile = profileForMode(mode)
  const match = profiles.find((entry) => entry.key === profile)
  return match
    ? { status: match.status, reason: match.reason }
    : { status: 'unknown', reason: 'Mode status unavailable' }
}

function statusLedClass(status: ProfileAvailabilityStatus): string {
  if (status === 'available') return 'hud-led--live'
  if (status === 'busy') return 'hud-led--loading'
  if (status === 'unknown') return 'hud-led--stale'
  return 'hud-led--error'
}

function statusReason(availability: ModeAvailability): string {
  return availability.reason?.trim() || STATUS_REASONS[availability.status] || availability.status
}

function dropdownPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(288, window.innerWidth - 24)
  return {
    top: rect.bottom + 8,
    left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    width,
  }
}

interface BriefingModeSelectorProps {
  value: BriefingMode
  onChange: (mode: BriefingMode) => void
  profiles: AgentProfileStatus[]
  hydrated: boolean
  disabled: boolean
}

function BriefingModeSelector({
  value,
  onChange,
  profiles,
  hydrated,
  disabled,
}: BriefingModeSelectorProps): ReactElement {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])
  const activeAvailability = resolveBriefingModeAvailability(value, profiles, hydrated)

  const close = useCallback((restoreFocus = false): void => {
    setOpen(false)
    if (restoreFocus) {
      window.requestAnimationFrame(() => triggerRef.current?.focus())
    }
  }, [])

  const updatePosition = useCallback((): void => {
    if (triggerRef.current) setPosition(dropdownPosition(triggerRef.current))
  }, [])

  const focusOption = useCallback((direction: 1 | -1, fromIndex: number): void => {
    const enabled = optionRefs.current
      .map((element, index) => ({ element, index }))
      .filter((entry): entry is { element: HTMLButtonElement; index: number } => Boolean(entry.element && !entry.element.disabled))
    if (enabled.length === 0) return
    const current = enabled.findIndex((entry) => entry.index === fromIndex)
    const next = current < 0
      ? direction === 1 ? 0 : enabled.length - 1
      : (current + direction + enabled.length) % enabled.length
    enabled[next].element.focus()
  }, [])

  const handleOptionKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number): void => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      focusOption(event.key === 'ArrowDown' ? 1 : -1, index)
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      const enabled = optionRefs.current.filter((element): element is HTMLButtonElement => Boolean(element && !element.disabled))
      enabled[event.key === 'Home' ? 0 : enabled.length - 1]?.focus()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      close(true)
    }
  }

  useEffect(() => {
    if (!open) return
    const handlePointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (target instanceof Node && !triggerRef.current?.contains(target) && !dropdownRef.current?.contains(target)) {
        close()
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [close, open])

  useEffect(() => {
    if (!open || !disabled) return
    const timeoutId = window.setTimeout(() => close(true), 0)
    return () => window.clearTimeout(timeoutId)
  }, [close, disabled, open])

  useLayoutEffect(() => {
    if (!open) return
    updatePosition()
    const activeIndex = ALL_OPTIONS.findIndex((option) => option.key === value)
    window.requestAnimationFrame(() => {
      const active = optionRefs.current[activeIndex]
      if (active && !active.disabled) active.focus()
      else focusOption(1, -1)
    })
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [focusOption, open, updatePosition, value])

  return (
    <div className="relative shrink-0">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Briefing mode: ${MODE_LABELS[value]}`}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !open) {
            event.preventDefault()
            setOpen(true)
          } else if (event.key === 'Escape') {
            event.preventDefault()
            close()
          }
        }}
        className="hud-interactive-shell hud-glass flex h-11 items-center gap-2 rounded-full px-3 font-mono text-[10px] uppercase tracking-wider text-zinc-200 transition-colors hover-blue-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Sparkles className="size-3.5 text-[#A855F7]" strokeWidth={2} aria-hidden />
        <span className={`hud-led size-1.5 shrink-0 ${statusLedClass(activeAvailability.status)}`} aria-hidden />
        <span className="whitespace-nowrap">{MODE_LABELS[value]}</span>
        <ChevronDown className={`size-3.5 text-[#6EA8FF] transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
      </button>

      {open && position ? createPortal(
        <div
          ref={dropdownRef}
          style={position}
          className="hud-corner-brackets hud-glass hud-glass-solid fixed z-[100] rounded-xl border border-white/10 p-2 shadow-2xl"
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <div className="border-b border-white/10 px-2 pb-2 pt-1">
            <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200">
              Briefing Synthesis
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Select a mode for the next briefing.
            </p>
          </div>
          <ul role="listbox" aria-label="Select briefing mode">
            {SECTIONS.map((section, sectionIndex) => (
              <li key={section.title} role="presentation">
                {sectionIndex > 0 ? <div className="mx-2 border-t border-white/10" aria-hidden /> : null}
                <div className="flex items-center gap-2 px-2 py-1.5 font-mono text-[9px] uppercase tracking-widest text-zinc-500" aria-hidden>
                  <section.icon className="size-3.5 text-zinc-600" />
                  {section.title}
                </div>
                <ul role="group" aria-label={section.title} className="space-y-1">
                  {section.options.map((option) => {
                    const index = ALL_OPTIONS.findIndex((entry) => entry.key === option.key)
                    const availability = resolveBriefingModeAvailability(option.key, profiles, hydrated)
                    const unavailable = availability.status !== 'available'
                    const selected = option.key === value
                    return (
                      <li key={option.key} role="presentation" className="group/briefing-option relative">
                        <button
                          ref={(element) => { optionRefs.current[index] = element }}
                          type="button"
                          role="option"
                          aria-selected={selected}
                          aria-disabled={unavailable}
                          disabled={unavailable}
                          onClick={() => {
                            onChange(option.key)
                            close(true)
                          }}
                          onKeyDown={(event) => handleOptionKeyDown(event, index)}
                          className={[
                            'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors focus-visible:outline-none',
                            unavailable
                              ? 'pointer-events-none cursor-not-allowed text-zinc-600 opacity-45'
                              : `hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15 ${selected ? 'bg-[#0F4DB8]/12 ring-1 ring-[#0F4DB8]/25' : ''}`,
                          ].join(' ')}
                        >
                          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.04] font-mono text-[10px] font-bold text-[#7EB3FF]">
                            {option.label.slice(0, 1)}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className={`hud-led size-1.5 shrink-0 ${statusLedClass(availability.status)}`} aria-hidden />
                              <span className="truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">{option.label}</span>
                            </span>
                            <span className="mt-0.5 block truncate pl-3.5 text-[10px] text-zinc-500">{option.description}</span>
                          </span>
                          {selected ? <Check className="size-3.5 shrink-0 text-[#39FF88]" strokeWidth={2.25} aria-hidden /> : null}
                        </button>
                        {unavailable ? (
                          <span role="tooltip" className="pointer-events-none absolute left-full top-1/2 z-[110] ml-2 -translate-y-1/2 whitespace-nowrap rounded-lg border border-white/10 bg-zinc-950/95 px-2.5 py-1.5 font-mono text-[10px] text-rose-400 opacity-0 shadow-xl transition-opacity group-hover/briefing-option:opacity-100">
                            {statusReason(availability)}
                          </span>
                        ) : null}
                      </li>
                    )
                  })}
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

interface GenerateControlProps {
  mainDisabled: boolean
  refreshDisabled: boolean
  busy: boolean
  onGenerate: () => void
  onRefreshAndGenerate: () => void
}

function GenerateControl({
  mainDisabled,
  refreshDisabled,
  busy,
  onGenerate,
  onRefreshAndGenerate,
}: GenerateControlProps): ReactElement {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const close = useCallback((restoreFocus = false): void => {
    setOpen(false)
    if (restoreFocus) window.requestAnimationFrame(() => triggerRef.current?.focus())
  }, [])
  const updatePosition = useCallback((): void => {
    if (triggerRef.current) setPosition(dropdownPosition(triggerRef.current))
  }, [])

  useEffect(() => {
    if (!open) return
    const handlePointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (target instanceof Node && !triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) close()
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [close, open])

  useEffect(() => {
    if (!open || !refreshDisabled) return
    const timeoutId = window.setTimeout(() => close(true), 0)
    return () => window.clearTimeout(timeoutId)
  }, [close, open, refreshDisabled])

  useLayoutEffect(() => {
    if (!open) return
    updatePosition()
    window.requestAnimationFrame(() => menuRef.current?.querySelector<HTMLButtonElement>('button')?.focus())
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open, updatePosition])

  return (
    <div className="hud-interactive-shell hud-glass flex h-11 shrink-0 rounded-full text-zinc-300">
      <button
        type="button"
        disabled={mainDisabled}
        onClick={onGenerate}
        className="inline-flex items-center gap-2 rounded-l-full px-3 font-orbitron text-[9px] font-semibold uppercase tracking-[0.14em] text-zinc-300 transition-colors hover:bg-white/5 hover:text-zinc-100 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
        aria-label="Generate briefing from current telemetry"
      >
        <FileText className="size-3.5" strokeWidth={2} aria-hidden />
        <span>{busy ? 'Working…' : 'Generate'}</span>
        <span className="hidden 2xl:inline">Briefing</span>
      </button>
      <span className="my-2 w-px bg-white/10" aria-hidden />
      <button
        ref={triggerRef}
        type="button"
        disabled={refreshDisabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More briefing generation options"
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            close()
          }
        }}
        className="inline-flex w-9 items-center justify-center rounded-r-full text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ChevronDown className={`size-3.5 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
      </button>

      {open && position ? createPortal(
        <div ref={menuRef} style={position} role="menu" aria-label="Briefing generation options" className="hud-corner-brackets hud-glass hud-glass-solid fixed z-[100] rounded-xl border border-white/10 p-2 shadow-2xl">
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              close(true)
              onRefreshAndGenerate()
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                close(true)
              }
            }}
            className="flex w-full items-start gap-3 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-purple-400/10 focus-visible:bg-purple-400/10 focus-visible:outline-none"
          >
            <RefreshCw className="mt-0.5 size-4 shrink-0 text-emerald-300" strokeWidth={2} aria-hidden />
            <span>
              <span className="block font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-100">Refresh All &amp; Generate</span>
              <span className="mt-1 block text-[10px] leading-relaxed text-zinc-500">Recollect every enabled connector before synthesis.</span>
            </span>
          </button>
        </div>,
        document.body,
      ) : null}
    </div>
  )
}

export interface BriefingControlsProps {
  mode: BriefingMode
  onModeChange: (mode: BriefingMode) => void
  profiles: AgentProfileStatus[]
  profilesHydrated: boolean
  activated: boolean
  hasSnapshot: boolean
  busy: boolean
  onGenerate: () => void
  onRefreshAndGenerate: () => void
}

export function BriefingControls({
  mode,
  onModeChange,
  profiles,
  profilesHydrated,
  activated,
  hasSnapshot,
  busy,
  onGenerate,
  onRefreshAndGenerate,
}: BriefingControlsProps): ReactElement {
  const availability = resolveBriefingModeAvailability(mode, profiles, profilesHydrated)
  const modeUnavailable = availability.status !== 'available'
  const baseDisabled = !activated || busy || modeUnavailable

  return (
    <div className="flex shrink-0 items-center gap-2" data-slot="briefing-controls">
      <BriefingModeSelector
        value={mode}
        onChange={onModeChange}
        profiles={profiles}
        hydrated={profilesHydrated}
        disabled={busy}
      />
      {activated ? (
        <GenerateControl
          mainDisabled={baseDisabled || !hasSnapshot}
          refreshDisabled={baseDisabled}
          busy={busy}
          onGenerate={onGenerate}
          onRefreshAndGenerate={onRefreshAndGenerate}
        />
      ) : null}
    </div>
  )
}
