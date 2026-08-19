import { Check, ChevronDown, Cloud, Cpu } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
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
  formatHomeModelSecondaryMetadata,
  providerDisplayName,
  runtimeDisplayName,
} from '../lib/agents'

export interface HomeModelSelectorProps {
  selectedModelId: string
  onModelChange: (modelId: string) => void
  catalog: ModelCatalogEntry[]
  agentsStatus: AgentStatus[]
  disabled?: boolean
  isQuerying?: boolean
}

function statusDotClass(status: AgentAvailabilityStatus): string {
  if (status === 'available' || status === 'configured' || status === 'verified') {
    return 'bg-emerald-300 shadow-[0_0_7px_rgba(110,231,183,0.8)]'
  }
  if (status === 'unknown' || status === 'busy' || status === 'verifying' || status === 'rate_limited') {
    return 'bg-amber-300 shadow-[0_0_7px_rgba(252,211,77,0.7)]'
  }
  if (status === 'disabled') {
    return 'bg-zinc-500 shadow-[0_0_5px_rgba(161,161,170,0.35)]'
  }
  return 'bg-[#DC2626] shadow-[0_0_7px_rgba(220,38,38,0.8)]'
}

function popoverPosition(trigger: HTMLButtonElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(360, window.innerWidth - 24)
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
  agentsStatus,
  disabled = false,
  isQuerying = false,
}: HomeModelSelectorProps): ReactElement {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties | null>(null)

  const pantheraStatus = useMemo(
    () => agentsStatus.find((agent) => agent.key === 'panthera'),
    [agentsStatus],
  )
  const felisStatus = useMemo(
    () => agentsStatus.find((agent) => agent.key === 'felis'),
    [agentsStatus],
  )

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

  const selectedStatus: AgentAvailabilityStatus = useMemo(() => {
    if (!selectedModel) return 'unknown'
    if (selectedModel.runtime === 'cloud') {
      return pantheraStatus?.status ?? 'configured'
    }
    return felisStatus?.status ?? 'available'
  }, [selectedModel, pantheraStatus, felisStatus])

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
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [isOpen])

  const updatePosition = useCallback((): void => {
    if (triggerRef.current) {
      setPosition(popoverPosition(triggerRef.current))
    }
  }, [])

  useLayoutEffect(() => {
    if (!isOpen) return
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, updatePosition])

  const toggleOpen = (): void => {
    if (disabled || isQuerying) return
    if (!isOpen && triggerRef.current) {
      setPosition(popoverPosition(triggerRef.current))
    }
    setIsOpen((prev) => !prev)
  }

  const handleSelect = (modelId: string): void => {
    onModelChange(modelId)
    setIsOpen(false)
    triggerRef.current?.focus()
  }

  const popover = isOpen && position && typeof document !== 'undefined'
    ? createPortal(
        <div
          ref={popoverRef}
          role="listbox"
          id="home-model-selector-popover"
          aria-label="Available models"
          tabIndex={-1}
          style={position}
          className="fixed z-[100] max-h-[22rem] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-2 shadow-2xl backdrop-blur-2xl scrollbar-thin"
        >
          <div className="space-y-3">
            {cloudModels.length > 0 && (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 px-2 py-1 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-400">
                  <Cloud className="size-3 text-cyan-400/80" aria-hidden />
                  <span>Cloud · Panthera</span>
                </div>
                <div className="space-y-0.5">
                  {cloudModels.map((entry) => {
                    const isSelected = selectedModel?.model_id === entry.model_id
                    const provider = providerDisplayName(entry.provider as string)
                    const status = pantheraStatus?.status ?? 'configured'
                    const isModelDisabled = status === 'disabled' || status === 'unauthorized'
                    return (
                      <button
                        key={entry.model_id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        disabled={isModelDisabled}
                        onClick={() => handleSelect(entry.model_id)}
                        className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left transition-colors ${
                          isSelected
                            ? 'border border-cyan-400/30 bg-cyan-400/10 text-cyan-200 shadow-sm'
                            : isModelDisabled
                              ? 'cursor-not-allowed opacity-45 text-zinc-500'
                              : 'text-zinc-300 hover:bg-white/5 hover:text-white'
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span
                              className={`size-1.5 shrink-0 rounded-full ${statusDotClass(status)}`}
                              aria-hidden
                            />
                            <span className="truncate text-xs font-medium">{entry.display_name}</span>
                          </div>
                          <p className="truncate pl-3.5 text-[10px] text-zinc-400">
                            {provider} {entry.pricing?.billing_basis === 'free_tier' ? '· Free tier' : ''}
                          </p>
                        </div>
                        {isSelected && <Check className="size-3.5 shrink-0 text-cyan-300 ml-2" aria-hidden />}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {localModels.length > 0 && (
              <div className="space-y-1 border-t border-white/10 pt-2">
                <div className="flex items-center gap-1.5 px-2 py-1 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-400">
                  <Cpu className="size-3 text-emerald-400/80" aria-hidden />
                  <span>Local · Felis</span>
                </div>
                <div className="space-y-0.5">
                  {localModels.map((entry) => {
                    const isSelected = selectedModel?.model_id === entry.model_id
                    const runtimeName = runtimeDisplayName(entry.provider as LocalRuntime)
                    const status = felisStatus?.status ?? 'available'
                    const isModelDisabled = status === 'disabled' || status === 'model_not_installed' || status === 'ollama_unreachable'
                    return (
                      <button
                        key={entry.model_id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        disabled={isModelDisabled}
                        onClick={() => handleSelect(entry.model_id)}
                        className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left transition-colors ${
                          isSelected
                            ? 'border border-emerald-400/30 bg-emerald-400/10 text-emerald-200 shadow-sm'
                            : isModelDisabled
                              ? 'cursor-not-allowed opacity-45 text-zinc-500'
                              : 'text-zinc-300 hover:bg-white/5 hover:text-white'
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span
                              className={`size-1.5 shrink-0 rounded-full ${statusDotClass(status)}`}
                              aria-hidden
                            />
                            <span className="truncate text-xs font-medium">{entry.display_name}</span>
                          </div>
                          <p className="truncate pl-3.5 text-[10px] text-zinc-400">
                            {runtimeName} · 16K context
                          </p>
                        </div>
                        {isSelected && <Check className="size-3.5 shrink-0 text-emerald-300 ml-2" aria-hidden />}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )
    : null

  const secondaryMetadata = formatHomeModelSecondaryMetadata(selectedModel)

  return (
    <div className="relative min-w-0" data-slot="home-model-selector-container">
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls="home-model-selector-popover"
        aria-label={`Model: ${selectedModel?.display_name ?? 'Select model'}`}
        disabled={disabled || isQuerying}
        onClick={toggleOpen}
        className="group relative flex h-full w-full min-w-0 items-center justify-between gap-2 rounded-xl border border-white/10 bg-zinc-900/60 px-3 py-2 text-left shadow-sm transition hover:border-white/20 hover:bg-zinc-900/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400/50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className={`size-1.5 shrink-0 rounded-full ${statusDotClass(selectedStatus)}`}
              aria-hidden
            />
            <span className="truncate font-sans text-xs font-semibold tracking-wide text-zinc-100">
              {selectedModel?.display_name ?? 'Select Model'}
            </span>
          </div>
          <p className="truncate text-[10px] text-zinc-400 transition group-hover:text-zinc-300">
            {secondaryMetadata}
          </p>
        </div>
        <ChevronDown
          className={`size-3.5 shrink-0 text-zinc-400 transition duration-200 group-hover:text-zinc-200 ${
            isOpen ? 'rotate-180 text-zinc-100' : ''
          }`}
          aria-hidden
        />
      </button>
      {popover}
    </div>
  )
}
