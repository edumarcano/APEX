import { Check, ChevronDown, Loader2, ShieldAlert, ShieldCheck } from 'lucide-react'
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
} from 'react'

import type {
  AgentAvailabilityStatus,
  AgentKey,
  AgentStability,
  AgentStatus,
  ModelCatalogEntry,
} from '../types/telemetry'
import {
  formatContextWindowLabel,
  providerDisplayName,
  runtimeDisplayName,
} from '../lib/agents'

import { ModelMark } from './ModelMark'

interface ModelSelectorProps {
  activeAgent: AgentKey
  selectedModelId: string
  onModelChange: (modelId: string) => void
  catalog: ModelCatalogEntry[]
  activeStatus: AgentStatus | null
  disabled?: boolean
  isQuerying?: boolean
  verifyingAgent?: AgentKey | null
  onVerify?: (agent: 'panthera') => Promise<boolean>
}

const STATUS_LABELS: Record<AgentAvailabilityStatus, string> = {
  available: 'Ready',
  busy: 'Busy',
  configured: 'Ready',
  verifying: 'Verifying…',
  verified: 'Verified',
  unauthorized: 'Access denied',
  model_unavailable: 'Unavailable',
  rate_limited: 'Rate limited',
  quota_exhausted: 'Quota exhausted',
  billing_blocked: 'Billing blocked',
  provider_unreachable: 'Unreachable',
  provider_error: 'Provider error',
  unknown: 'Checking…',
  disabled: 'Unavailable',
  ollama_unreachable: 'Ollama offline',
  model_not_installed: 'Not installed',
  insufficient_ram: 'Low memory',
  cpu_overloaded: 'CPU busy',
}

function statusClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') return 'text-emerald-300'
  if (status === 'unknown' || status === 'busy' || status === 'verifying' || status === 'rate_limited') return 'text-amber-200'
  return 'text-[#DC2626]'
}

function statusDotClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') {
    return 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]'
  }
  if (status === 'unknown' || status === 'busy' || status === 'verifying' || status === 'rate_limited') {
    return 'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.7)]'
  }
  return 'bg-[#DC2626] shadow-[0_0_6px_rgba(220,38,38,0.8)]'
}

function stabilityBadge(stability: AgentStability | null | undefined, className = ''): ReactElement | null {
  if (!stability || stability === 'stable') return null
  const experimental = stability === 'experimental'
  return (
    <span
      className={`rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider ${
        experimental
          ? 'border-cyan-300/30 bg-cyan-400/10 text-cyan-200'
          : 'border-amber-300/30 bg-amber-400/10 text-amber-200'
      }${className ? ` ${className}` : ''}`}
    >
      {experimental ? 'Experimental' : 'Preview'}
    </span>
  )
}

function formatPricing(entry: ModelCatalogEntry | null | undefined): string {
  if (!entry?.pricing) {
    if (entry?.runtime === 'local') return 'Local · No provider charge'
    return 'Standard pricing'
  }
  const { billing_basis, input_per_million, output_per_million } = entry.pricing
  if (billing_basis === 'free_tier') return 'Free tier'
  if (billing_basis === 'local') return 'Local · No provider charge'
  return `$${input_per_million.toFixed(2)}/M in · $${output_per_million.toFixed(2)}/M out`
}

function capabilityTags(entry: ModelCatalogEntry): string[] {
  const tags: string[] = []
  if (entry.supports_effort || (entry.reasoning_modes && entry.reasoning_modes.length > 1)) {
    tags.push('Reasoning')
  }
  if (entry.runtime === 'local' && (entry.context_options?.length || entry.default_context_window)) {
    tags.push('Selectable context')
  } else if (entry.maximum_context_window) {
    const formatted = formatContextWindowLabel(entry.maximum_context_window)
    if (formatted) tags.push(`${formatted} context`)
  } else if (entry.pricing?.long_context_threshold_tokens) {
    const formatted = formatContextWindowLabel(entry.pricing.long_context_threshold_tokens)
    if (formatted) tags.push(`${formatted}+ context`)
  }
  if (entry.hosted_capabilities.includes('google_search')) tags.push('Search')
  if (entry.hosted_capabilities.includes('google_maps')) tags.push('Maps')
  if (entry.hosted_capabilities.includes('x_search')) tags.push('X Search')
  return tags
}

export function ModelSelector({
  activeAgent,
  selectedModelId,
  onModelChange,
  catalog,
  activeStatus,
  disabled = false,
  isQuerying = false,
  verifyingAgent,
  onVerify,
}: ModelSelectorProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const runtimeTarget = activeAgent === 'panthera' ? 'cloud' : 'local'
  const availableModels = useMemo(
    () => catalog.filter((entry) => entry.runtime === runtimeTarget),
    [catalog, runtimeTarget],
  )

  const selectedModel = useMemo(
    () => availableModels.find((entry) => entry.model_id === selectedModelId) ?? availableModels[0] ?? null,
    [availableModels, selectedModelId],
  )

  useEffect(() => {
    if (!isOpen) return
    const handlePointerDown = (event: PointerEvent): void => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setIsOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const selectModel = (modelId: string): void => {
    onModelChange(modelId)
    setIsOpen(false)
    window.setTimeout(() => triggerRef.current?.focus(), 0)
  }

  const isCloud = activeAgent === 'panthera'
  const isVerifying = verifyingAgent === 'panthera' || activeStatus?.status === 'verifying'
  const canVerify = isCloud && onVerify && activeStatus?.status !== 'disabled'

  // Model-level readiness/residency status label
  const readinessLabel = isCloud
    ? STATUS_LABELS[activeStatus?.status ?? 'configured'] ?? 'Ready'
    : activeStatus?.loading
      ? 'Loading…'
      : activeStatus?.active
        ? 'Loaded'
        : 'Unloaded'

  const readinessClass = isCloud
    ? statusClass(activeStatus?.status ?? 'configured')
    : activeStatus?.loading
      ? 'text-amber-200'
      : activeStatus?.active
        ? 'text-emerald-300'
        : 'text-zinc-400'

  const readinessDot = isCloud
    ? statusDotClass(activeStatus?.status ?? 'configured')
    : activeStatus?.loading
      ? 'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.7)]'
      : activeStatus?.active
        ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]'
        : 'bg-zinc-500'

  const selectedCapabilities = selectedModel ? capabilityTags(selectedModel) : []
  const isFreeTier = selectedModel?.pricing?.billing_basis === 'free_tier'
  const providerLabel = selectedModel
    ? selectedModel.runtime === 'local'
      ? runtimeDisplayName(selectedModel.provider as 'ollama' | 'llama_cpp')
      : providerDisplayName(selectedModel.provider)
    : ''

  return (
    <section className="relative space-y-2" ref={containerRef} aria-label="Model selection">
      <div className="flex items-center justify-between">
        <label
          id="cortex-model-label"
          className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
        >
          Model
        </label>
        <span className="font-mono text-[9px] text-zinc-500">
          {availableModels.length} available
        </span>
      </div>

      {/* Selected Model Card */}
      <div className="group relative w-full rounded-xl border border-white/12 bg-white/[0.03] p-3 text-left transition-all hover:border-[#7EB3FF]/50 hover:bg-white/[0.05]">
        {/* Model Trigger Button */}
        <button
          ref={triggerRef}
          type="button"
          disabled={disabled || isQuerying}
          aria-labelledby="cortex-model-label"
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          onClick={() => setIsOpen((prev) => !prev)}
          className="w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] disabled:cursor-not-allowed disabled:opacity-45"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <ModelMark
                  modelId={selectedModel?.model_id ?? selectedModelId}
                  provider={selectedModel?.provider}
                  size={18}
                />
                <span className="truncate font-orbitron text-xs font-semibold text-white">
                  {selectedModel?.display_name ?? selectedModelId}
                </span>
                {selectedModel ? stabilityBadge(selectedModel.stability) : null}
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] text-zinc-400">
                <span>{providerLabel}</span>
                {selectedModel?.dev_only ? (
                  <span className="rounded border border-purple-400/30 bg-purple-500/10 px-1 py-0 font-mono text-[8px] uppercase tracking-wider text-purple-200">
                    DEV
                  </span>
                ) : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <div className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider">
                {isVerifying ? (
                  <Loader2 className="size-3 animate-spin text-amber-200" aria-hidden />
                ) : (
                  <span className={`size-1.5 rounded-full ${readinessDot}`} aria-hidden />
                )}
                <span className={readinessClass}>{readinessLabel}</span>
              </div>
              <ChevronDown
                className={`size-4 text-zinc-400 transition-transform ${isOpen ? 'rotate-180 text-[#7EB3FF]' : 'group-hover:text-zinc-200'}`}
                aria-hidden
              />
            </div>
          </div>
        </button>

        {/* Pricing line & Capabilities */}
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-t border-white/10 pt-2 font-mono text-[10px]">
          <span className="text-zinc-400">
            {formatPricing(selectedModel)}
          </span>
          {canVerify ? (
            <button
              type="button"
              disabled={isVerifying || isQuerying}
              onClick={() => {
                if (onVerify) void onVerify('panthera')
              }}
              className="inline-flex items-center gap-1 rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-zinc-300 hover:border-[#7EB3FF]/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ShieldCheck className="size-2.5" aria-hidden />
              {isVerifying ? 'Verifying' : 'Verify'}
            </button>
          ) : null}
        </div>

        {isFreeTier ? (
          <div className="mt-2 flex items-center gap-1.5 rounded-md border border-amber-400/20 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300">
            <ShieldAlert className="size-3 shrink-0 text-amber-400" aria-hidden />
            <span>Free tier · Content may be used to improve Google products</span>
          </div>
        ) : null}

        {selectedCapabilities.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {selectedCapabilities.map((cap) => (
              <span
                key={cap}
                className="rounded border border-white/10 bg-black/30 px-1.5 py-0.5 font-mono text-[9px] text-zinc-400"
              >
                {cap}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {/* Model Browser Popover */}
      {isOpen ? (
        <div
          role="listbox"
          aria-label={`Select model for ${activeAgent}`}
          className="absolute left-0 right-0 top-full z-50 mt-2 max-h-[min(62vh,34rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-2.5 shadow-2xl backdrop-blur-xl scrollbar-thin"
        >
          <div className="border-b border-white/10 px-2 pb-2 pt-1">
            <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-200">
              Select Model
            </p>
            <p className="mt-0.5 text-[10px] text-zinc-500">
              Choose the intelligence profile for {activeAgent === 'panthera' ? 'Panthera' : 'Felis'}.
            </p>
          </div>

          <div className="space-y-1.5 py-2">
            {availableModels.map((model) => {
              const selected = model.model_id === selectedModelId
              const provLabel =
                model.runtime === 'local'
                  ? runtimeDisplayName(model.provider as 'ollama' | 'llama_cpp')
                  : providerDisplayName(model.provider)
              const caps = capabilityTags(model)

              return (
                <button
                  key={model.model_id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => selectModel(model.model_id)}
                  className={`w-full rounded-lg border p-2.5 text-left transition-all focus-visible:outline-none ${
                    selected
                      ? 'border-[#7E22CE]/65 bg-[#7E22CE]/15 ring-1 ring-[#7E22CE]/35'
                      : 'border-white/5 bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.04]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <ModelMark
                          modelId={model.model_id}
                          provider={model.provider}
                          size={16}
                        />
                        <span className="font-orbitron text-xs font-semibold text-white">
                          {model.display_name}
                        </span>
                        {stabilityBadge(model.stability)}
                        {model.dev_only ? (
                          <span className="rounded border border-purple-400/30 bg-purple-500/10 px-1 py-0 font-mono text-[8px] uppercase tracking-wider text-purple-200">
                            DEV
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] text-zinc-400">
                        <span>{provLabel}</span>
                      </p>
                    </div>
                    {selected ? (
                      <Check className="size-4 shrink-0 text-[#39FF88]" aria-hidden />
                    ) : null}
                  </div>

                  <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-zinc-400">
                    <span>{formatPricing(model)}</span>
                  </div>

                  {caps.length > 0 ? (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {caps.map((cap) => (
                        <span
                          key={cap}
                          className="rounded border border-white/5 bg-black/20 px-1.5 py-0.5 font-mono text-[9px] text-zinc-500"
                        >
                          {cap}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </section>
  )
}
