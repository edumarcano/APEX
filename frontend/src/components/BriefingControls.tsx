import {
  Check,
  ChevronDown,
  FileText,
  Orbit,
  RefreshCw,
  Sparkles,
  Zap,
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
  AgentAvailabilityStatus,
  BriefingTargetStatus,
} from '../types/telemetry'
import {
  resolveBriefingModeAvailability,
  type BriefingModeAvailability as ModeAvailability,
} from '../lib/agents'

interface BriefingOption {
  key: BriefingMode
  label: string
  description: string
}

const ALL_OPTIONS: readonly BriefingOption[] = [
  { key: 'focused', label: 'Focused', description: 'Panthera · DeepSeek V4 Flash' },
  { key: 'flash', label: 'Flash', description: 'Felis · Gemma 4 E2B' },
  { key: 'structured', label: 'Structured', description: 'Deterministic · no model' },
]

const MODE_LABELS: Record<string, string> = {
  flash: 'Flash',
  focused: 'Focused',
  structured: 'Structured',
}

const STATUS_REASONS: Record<AgentAvailabilityStatus, string> = {
  available: '',
  busy: 'Local inference is currently busy',
  configured: 'Provider credentials are configured but not yet verified',
  verifying: 'Provider access is being verified',
  verified: '',
  unauthorized: 'Provider denied access to this agent',
  model_unavailable: 'Configured model is unavailable to this provider account',
  rate_limited: 'Provider rate limit is currently active',
  quota_exhausted: 'Provider quota or credits are exhausted',
  billing_blocked: 'Provider billing or account prerequisite is blocking requests',
  provider_unreachable: 'Provider is temporarily unreachable',
  provider_error: 'Provider verification failed',
  unknown: 'Checking mode availability…',
  disabled: 'Mode disabled in system settings',
  ollama_unreachable: 'Ollama daemon is unreachable',
  model_not_installed: 'Model is not installed locally',
  insufficient_ram: 'Current memory pressure exceeds threshold',
  cpu_overloaded: 'Current CPU utilization exceeds threshold',
}

function statusLedClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') return 'hud-led--live'
  if (status === 'busy' || status === 'verifying' || status === 'rate_limited') return 'hud-led--loading'
  if (status === 'unknown') return 'hud-led--stale'
  return 'hud-led--error'
}

function statusReason(availability: ModeAvailability): string {
  return availability.reason?.trim() || STATUS_REASONS[availability.status] || availability.status
}

function modeDescription(mode: BriefingMode, targets?: BriefingTargetStatus[]): string {
  const target = targets?.find((option) => option.mode === mode)
  if (target?.description) return target.description
  return ALL_OPTIONS.find((option) => option.key === mode)?.description ?? 'Briefing synthesis'
}

function compactRate(value: number): string {
  return `$${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2)}`
}

function modeCost(mode: BriefingMode, targets?: BriefingTargetStatus[]): string {
  if (mode === 'structured') return 'No model cost'
  const target = targets?.find((entry) => entry.mode === mode)
  if (target?.pricing) {
    if (target.pricing.billing_basis === 'local') return 'No provider token charge'
    if (target.pricing.billing_basis === 'free_tier') return 'Free tier'
    return `In ${compactRate(target.pricing.input_per_million)} · Out ${compactRate(target.pricing.output_per_million)} / 1M`
  }
  return 'Pricing unavailable'
}

function BriefingModeMark({ mode }: { mode: BriefingMode }): ReactElement {
  if (mode === 'focused') {
    return (
      <span
        aria-label="Focused Briefing mark"
        className="inline-flex size-6 shrink-0 items-center justify-center rounded-lg border border-purple-300/25 bg-purple-400/10 text-purple-200"
      >
        <Orbit className="size-3.5" aria-hidden />
      </span>
    )
  }
  if (mode === 'flash') {
    return (
      <span
        aria-label="Flash Briefing mark"
        className="inline-flex size-6 shrink-0 items-center justify-center rounded-lg border border-amber-300/25 bg-amber-400/10 text-amber-200"
      >
        <Zap className="size-3.5" aria-hidden />
      </span>
    )
  }
  return (
    <span
      aria-label="Structured Briefing mark"
      className="inline-flex size-6 shrink-0 items-center justify-center rounded-lg border border-slate-300/20 bg-slate-400/10 text-slate-200"
    >
      <FileText className="size-3.5" aria-hidden />
    </span>
  )
}

function dropdownPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(288, window.innerWidth - 24)
  return {
    bottom: window.innerHeight - rect.top + 8,
    left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    width,
  }
}

export interface BriefingModeSelectorProps {
  value: BriefingMode
  onChange: (mode: BriefingMode) => void
  targets?: BriefingTargetStatus[]
  disabled: boolean
  className?: string
}

export function BriefingModeSelector({
  value,
  onChange,
  targets,
  disabled,
  className = '',
}: BriefingModeSelectorProps): ReactElement {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])
  const activeAvailability = resolveBriefingModeAvailability(value, targets)

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
    <div className={`relative min-w-0 ${className}`}>
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
        className="flex h-10 w-full min-w-0 items-center gap-2 rounded-lg border border-white/10 bg-black/25 px-3 font-mono text-[10px] text-zinc-200 transition-colors hover:border-[#0F4DB8]/55 hover:bg-[#0F4DB8]/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <BriefingModeMark mode={value} />
        <span className={`hud-led size-1.5 shrink-0 ${statusLedClass(activeAvailability.status)}`} aria-hidden />
        <span className="min-w-0 flex-1 text-left">
          <span className="block truncate uppercase tracking-wider">{MODE_LABELS[value]}</span>
          <span className="block truncate text-[8px] normal-case tracking-normal text-zinc-500">{modeDescription(value, targets)}</span>
        </span>
        <ChevronDown className={`ml-auto size-3.5 shrink-0 text-[#6EA8FF] transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
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
              Briefing Mode
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Select a briefing type for the next briefing.
            </p>
          </div>
          <ul role="listbox" aria-label="Select briefing mode">
            {ALL_OPTIONS.map((option, index) => {
              const availability = resolveBriefingModeAvailability(option.key, targets)
              const unavailable = !['available', 'configured', 'verified'].includes(availability.status)
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
                      'flex min-h-16 w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors focus-visible:outline-none',
                      unavailable
                        ? 'pointer-events-none cursor-not-allowed text-zinc-600 opacity-45'
                        : `hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15 ${selected ? 'bg-[#0F4DB8]/12 ring-1 ring-[#0F4DB8]/25' : ''}`,
                    ].join(' ')}
                  >
                    <BriefingModeMark mode={option.key} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">{option.label}</span>
                      <span className="mt-0.5 block truncate text-[10px] text-zinc-500">{modeDescription(option.key, targets)}</span>
                      <span className="mt-1 block font-mono text-[9px] text-zinc-400">{modeCost(option.key, targets)}</span>
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
        </div>,
        document.body,
      ) : null}
    </div>
  )
}

export interface BriefingGenerateControlProps {
  mainDisabled: boolean
  refreshDisabled: boolean
  busy: boolean
  onGenerate: () => void
  onRefreshAll: () => void
  onRefreshAndGenerate: () => void
  className?: string
}

export function BriefingGenerateControl({
  mainDisabled,
  refreshDisabled,
  busy,
  onGenerate,
  onRefreshAll,
  onRefreshAndGenerate,
  className = '',
}: BriefingGenerateControlProps): ReactElement {
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
    <div className={`hud-command-surface inline-flex min-w-0 rounded-lg border border-amber-400/25 bg-amber-950/20 text-amber-200 shadow-[inset_0_1px_0_rgba(251,191,36,0.1)] transition-[border-color,background-color,box-shadow,color] duration-300 hover:border-amber-400/40 hover:bg-amber-400/15 hover:text-amber-100 hover:shadow-[0_0_12px_rgba(251,191,36,0.18)] active:bg-amber-400/25 ${className}`}>
      <button
        type="button"
        disabled={mainDisabled}
        onClick={onGenerate}
        className="group inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-l-lg px-3 py-1.5 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-200 transition-colors hover:text-amber-100 focus-visible:z-10 focus-visible:text-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F59E0B] disabled:cursor-not-allowed disabled:opacity-40 sm:text-[11px]"
        aria-label="Generate briefing from current telemetry"
      >
        <Sparkles className="size-3.5 shrink-0 text-amber-300 transition-transform group-hover:scale-110" aria-hidden />
        {busy ? (
          <span className="whitespace-nowrap">Working…</span>
        ) : (
          <>
            <span className="whitespace-nowrap group-hover:hidden group-focus-visible:hidden">Generate Briefing</span>
            <span className="hidden whitespace-nowrap group-hover:inline group-focus-visible:inline">&gt; Generate Briefing</span>
          </>
        )}
      </button>
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
        className="inline-flex w-8 shrink-0 items-center justify-center rounded-r-lg border-l border-amber-400/20 text-amber-300 transition-colors hover:bg-amber-400/10 hover:text-amber-100 focus-visible:z-10 focus-visible:text-amber-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F59E0B] disabled:cursor-not-allowed disabled:opacity-40 sm:w-9"
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
              onRefreshAll()
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                close(true)
              }
            }}
            className="flex w-full items-start gap-3 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-amber-400/10 focus-visible:bg-amber-400/10 focus-visible:outline-none"
          >
            <RefreshCw className="mt-0.5 size-4 shrink-0 text-emerald-300" strokeWidth={2} aria-hidden />
            <span>
              <span className="block font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-100">Refresh All</span>
              <span className="mt-1 block text-[10px] leading-relaxed text-zinc-500">Recollect every enabled connector without generating a briefing.</span>
            </span>
          </button>
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
            className="flex w-full items-start gap-3 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-amber-400/10 focus-visible:bg-amber-400/10 focus-visible:outline-none"
          >
            <RefreshCw className="mt-0.5 size-4 shrink-0 text-emerald-300" strokeWidth={2} aria-hidden />
            <span>
              <span className="block font-mono text-[10px] uppercase tracking-[0.14em] text-zinc-100">Refresh All &amp; Generate Briefing</span>
              <span className="mt-1 block text-[10px] leading-relaxed text-zinc-500">Recollect every enabled connector before briefing generation.</span>
            </span>
          </button>
        </div>,
        document.body,
      ) : null}
    </div>
  )
}
