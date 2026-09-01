import {
  Check,
  ChevronDown,
  Cloud,
  Gpu,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactElement,
} from 'react'
import { createPortal } from 'react-dom'

import type {
  AgentAvailabilityStatus,
  AgentStatus,
  LocalRuntime,
  ModelCatalogEntry,
} from '../types/telemetry'
import {
  formatReasoningLabel,
  providerDisplayName,
  resolveLowestReasoningEffort,
  runtimeDisplayName,
} from '../lib/agents'

import { ModelMark } from './ModelMark'
import { StabilityBadge } from './StabilityBadge'

export interface HomeModelSelectorProps {
  selectedModelId: string
  onModelChange: (modelId: string) => void
  catalog: ModelCatalogEntry[]
  /** @deprecated Ignored while callers migrate to per-model availability. */
  agentsStatus?: AgentStatus[]
  disabled?: boolean
  isQuerying?: boolean
  className?: string
}

function statusLedClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') return 'hud-led--live'
  if (status === 'busy' || status === 'verifying' || status === 'rate_limited') return 'hud-led--loading'
  if (status === 'unknown') return 'hud-led--stale'
  return 'hud-led--error'
}

function compactRate(value: number): string {
  return `$${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2)}`
}

function modelCost(entry: ModelCatalogEntry): string {
  if (entry.runtime === 'local') return 'No provider token charge'
  if (entry.pricing) {
    if (entry.pricing.billing_basis === 'local') return 'No provider token charge'
    return `In ${compactRate(entry.pricing.input_per_million)} · Out ${compactRate(entry.pricing.output_per_million)} / 1M`
  }
  return 'Pricing unavailable'
}

function dropdownPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(320, window.innerWidth - 24)
  return {
    bottom: window.innerHeight - rect.top + 8,
    left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    width,
  }
}

export function HomeModelSelector({
  selectedModelId,
  onModelChange,
  catalog,
  disabled = false,
  isQuerying = false,
  className = '',
}: HomeModelSelectorProps): ReactElement {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([])
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties | null>(null)

  const selectedModel = useMemo(
    () => catalog.find((entry) => entry.model_id === selectedModelId) ?? catalog[0] ?? null,
    [catalog, selectedModelId],
  )

  const cloudModels = useMemo(
    () => catalog.filter((entry) => entry.runtime === 'cloud'),
    [catalog],
  )
  const localModels = useMemo(
    () => catalog.filter((entry) => entry.runtime === 'local'),
    [catalog],
  )

  const allOrderedModels = useMemo(
    () => [...cloudModels, ...localModels],
    [cloudModels, localModels],
  )

  const selectedStatus: AgentAvailabilityStatus = useMemo(() => {
    if (!selectedModel) return 'unknown'
    if (selectedModel.credentials_configured === false) return 'unauthorized'
    return selectedModel.status ?? (selectedModel.runtime === 'local' ? 'available' : 'configured')
  }, [selectedModel])

  const close = useCallback((focusTrigger = false): void => {
    setOpen(false)
    if (focusTrigger) {
      triggerRef.current?.focus()
    }
  }, [])

  const updatePosition = useCallback((): void => {
    if (triggerRef.current) {
      setPosition(dropdownPosition(triggerRef.current))
    }
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
    if (!open || disabled || isQuerying) return
    const timeoutId = window.setTimeout(() => {
      if (disabled || isQuerying) close(true)
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [close, disabled, isQuerying, open])

  useLayoutEffect(() => {
    if (!open) return
    updatePosition()
    const activeIndex = allOrderedModels.findIndex((entry) => entry.model_id === selectedModel?.model_id)
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
  }, [allOrderedModels, focusOption, open, selectedModel, updatePosition])

  return (
    <div className={`relative shrink-0 ${className}`} data-slot="home-model-selector-container">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled || isQuerying}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Model: ${selectedModel?.display_name ?? 'Select model'}`}
        title={`Model: ${selectedModel?.display_name ?? 'Select model'}`}
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
        className="flex h-full min-h-[46px] items-center gap-1.5 rounded-lg border border-white/10 bg-black/35 px-2.5 font-mono text-[10px] text-zinc-200 transition-colors hover:border-[#0F4DB8]/55 hover:bg-[#0F4DB8]/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-md border border-white/10 bg-white/[0.03]">
          <ModelMark modelId={selectedModel?.model_id} provider={selectedModel?.provider} size={14} />
        </span>
        <span className={`hud-led size-1.5 shrink-0 ${statusLedClass(selectedStatus)}`} aria-hidden />
        <ChevronDown
          className={`size-3 shrink-0 text-[#6EA8FF] transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden
        />
      </button>

      {open && position && typeof document !== 'undefined' ? createPortal(
        <div
          ref={dropdownRef}
          style={position}
          className="hud-corner-brackets hud-glass hud-glass-solid fixed z-[100] flex max-h-[26rem] flex-col rounded-xl border border-white/10 p-2 shadow-2xl"
        >
          <span className="hud-corner-bl" aria-hidden />
          <span className="hud-corner-br" aria-hidden />
          <div className="shrink-0 border-b border-white/10 px-2 pb-2 pt-1">
            <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200">
              Model Selection
            </p>
            <p className="mt-1 text-[10px] text-zinc-500">
              Select an operational model for Home queries.
            </p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin pt-1">
            <ul role="listbox" aria-label="Select model">
              {cloudModels.length > 0 && (
                <li role="presentation">
                  <div className="flex items-center gap-2 px-2 py-1.5 font-mono text-[9px] uppercase tracking-widest text-[#6EA8FF]/90" aria-hidden>
                    <Cloud className="size-3.5 text-[#6EA8FF]" />
                    Cloud models
                  </div>
                  <ul role="group" aria-label="Cloud models" className="space-y-1">
                    {cloudModels.map((entry) => {
                      const index = allOrderedModels.findIndex((item) => item.model_id === entry.model_id)
                      const isSelected = selectedModel?.model_id === entry.model_id
                      const provider = providerDisplayName(entry.provider)
                      const isUnauthorized = entry.credentials_configured === false
                      const isModelDisabled = isUnauthorized || entry.status === 'disabled'
                      const lowestEffort = resolveLowestReasoningEffort(entry.reasoning_options)
                      const reasoningLabel = lowestEffort && lowestEffort !== 'none'
                        ? `${formatReasoningLabel(lowestEffort)} reasoning`
                        : 'Reasoning off'
                      return (
                        <li key={entry.model_id} role="presentation" className="group/model-option relative">
                          <button
                            ref={(element) => { optionRefs.current[index] = element }}
                            type="button"
                            role="option"
                            aria-selected={isSelected}
                            aria-disabled={isModelDisabled}
                            disabled={isModelDisabled}
                            onClick={() => {
                              onModelChange(entry.model_id)
                              close(true)
                            }}
                            onKeyDown={(event) => handleOptionKeyDown(event, index)}
                            className={[
                              'flex min-h-14 w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors focus-visible:outline-none',
                              isModelDisabled
                                ? 'pointer-events-none cursor-not-allowed text-zinc-600 opacity-45'
                                : `hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15 ${isSelected ? 'bg-[#0F4DB8]/12 ring-1 ring-[#0F4DB8]/25' : ''}`,
                            ].join(' ')}
                          >
                            <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03]">
                              <ModelMark modelId={entry.model_id} provider={entry.provider} size={14} />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex items-center gap-1.5">
                                <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">
                                  {entry.display_name}
                                </span>
                                <StabilityBadge stability={entry.stability} />
                              </span>
                              <span className="mt-0.5 block truncate text-[10px] text-zinc-500">
                                {provider} · {isUnauthorized ? 'Missing API key' : reasoningLabel}
                              </span>
                              <span className="mt-1 block font-mono text-[9px] text-zinc-400">
                                {modelCost(entry)}
                              </span>
                            </span>
                            {isSelected ? (
                              <Check className="size-3.5 shrink-0 text-[#39FF88]" strokeWidth={2.25} aria-hidden />
                            ) : null}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </li>
              )}

              {localModels.length > 0 && (
                <li role="presentation">
                  {cloudModels.length > 0 ? <div className="mx-2 my-1 border-t border-white/10" aria-hidden /> : null}
                  <div className="flex items-center gap-2 px-2 py-1.5 font-mono text-[9px] uppercase tracking-widest text-amber-400/90" aria-hidden>
                    <Gpu className="size-3.5 text-amber-400" />
                    Local models
                  </div>
                  <ul role="group" aria-label="Local models" className="space-y-1">
                    {localModels.map((entry) => {
                      const index = allOrderedModels.findIndex((item) => item.model_id === entry.model_id)
                      const isSelected = selectedModel?.model_id === entry.model_id
                      const runtimeName = runtimeDisplayName(entry.provider as LocalRuntime)
                      const isModelDisabled = entry.status === 'disabled'
                      return (
                        <li key={entry.model_id} role="presentation" className="group/model-option relative">
                          <button
                            ref={(element) => { optionRefs.current[index] = element }}
                            type="button"
                            role="option"
                            aria-selected={isSelected}
                            aria-disabled={isModelDisabled}
                            disabled={isModelDisabled}
                            onClick={() => {
                              onModelChange(entry.model_id)
                              close(true)
                            }}
                            onKeyDown={(event) => handleOptionKeyDown(event, index)}
                            className={[
                              'flex min-h-14 w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors focus-visible:outline-none',
                              isModelDisabled
                                ? 'pointer-events-none cursor-not-allowed text-zinc-600 opacity-45'
                                : `hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15 ${isSelected ? 'bg-[#0F4DB8]/12 ring-1 ring-[#0F4DB8]/25' : ''}`,
                            ].join(' ')}
                          >
                            <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03]">
                              <ModelMark modelId={entry.model_id} provider={entry.provider} size={14} />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex items-center gap-1.5">
                                <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-100">
                                  {entry.display_name}
                                </span>
                                <StabilityBadge stability={entry.stability} />
                              </span>
                              <span className="mt-0.5 block truncate text-[10px] text-zinc-500">
                                {runtimeName} · {entry.provider === 'ollama' ? '4K context' : '16K context'}
                              </span>
                              <span className="mt-1 block font-mono text-[9px] text-zinc-400">
                                {modelCost(entry)}
                              </span>
                            </span>
                            {isSelected ? (
                              <Check className="size-3.5 shrink-0 text-[#39FF88]" strokeWidth={2.25} aria-hidden />
                            ) : null}
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </li>
              )}
            </ul>
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  )
}
