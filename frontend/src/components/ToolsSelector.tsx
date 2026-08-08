import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Pencil,
  RotateCcw,
  Save,
  Search,
  Star,
  Trash2,
  X,
} from 'lucide-react'
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
} from 'react'

import type {
  ToolCatalog,
  ToolCatalogGroup,
  ToolPreflightEstimate,
} from '../types/telemetry'

interface ToolsSelectorProps {
  compact?: boolean
  catalog: ToolCatalog | null
  selectedToolNames: string[]
  activeToolProfileId: string | null
  onSelectionChange: (names: string[]) => void
  onProfileChange: (profileId: string) => void
  preflight?: ToolPreflightEstimate | null
  preflightLoading?: boolean
  catalogError?: string | null
  preflightError?: string | null
  profileFeedback?: string | null
  profileError?: string | null
  disabled?: boolean
  onSaveProfile?: (name: string) => void
  onDuplicateProfile?: (profileId: string, name: string) => void
  onRenameProfile?: (profileId: string, name: string) => void
  onDeleteProfile?: (profileId: string) => void
  onRestoreProfile?: (profileId: string) => void
  onSetDefaultProfile?: (profileId: string) => void
}
function formatTokens(value: number): string {
  return `~${Math.max(0, Math.round(value)).toLocaleString()}`
}
function formatHostedToolName(name: string): string {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}
function selectedTokenTotal(
  catalog: ToolCatalog | null,
  selectedToolNames: string[],
): number {
  if (!catalog) return 0
  const selected = new Set(selectedToolNames)
  return catalog.tools
    .filter((tool) => selected.has(tool.name))
    .reduce((total, tool) => total + tool.estimated_schema_tokens, 0)
}

function groupSelection(
  group: ToolCatalogGroup,
  selected: Set<string>,
): { available: string[]; allNames: string[]; all: boolean; some: boolean } {
  const allNames = group.tools.map((tool) => tool.name)
  const available = group.tools
    .filter((tool) => tool.available && tool.allowed_for_agent)
    .map((tool) => tool.name)
  const selectedCount = available.filter((name) => selected.has(name)).length
  return {
    available,
    allNames,
    all: available.length > 0 && selectedCount === available.length,
    some: selectedCount > 0 && selectedCount < available.length,
  }
}

function Utilization({
  estimate,
}: {
  estimate: ToolPreflightEstimate
}): ReactElement | null {
  const context = estimate.breakdown.configured_context_window
  const remaining = estimate.breakdown.remaining_estimated_capacity
  if (context == null || remaining == null) return null
  const used = Math.max(0, context - remaining)
  const percentage = Math.min(100, Math.round((used / context) * 100))
  return (
    <div className="mt-2 rounded-lg border border-white/10 bg-black/20 p-2.5">
      <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-zinc-400">
        <span>Context utilization · estimate</span>
        <span className={percentage >= 80 ? 'text-amber-300' : 'text-zinc-300'}>
          {percentage}% · {used.toLocaleString()}/{context.toLocaleString()}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/10">
        <span
          className={`block h-full rounded-full ${percentage >= 90 ? 'bg-red-400' : percentage >= 80 ? 'bg-amber-300' : 'bg-[#A855F7]'}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  )
}

export function ToolsSelector({
  compact = false,
  catalog,
  selectedToolNames,
  activeToolProfileId,
  onSelectionChange,
  onProfileChange,
  preflight = null,
  preflightLoading = false,
  catalogError = null,
  preflightError = null,
  profileFeedback = null,
  profileError = null,
  disabled = false,
  onSaveProfile,
  onDuplicateProfile,
  onRenameProfile,
  onDeleteProfile,
  onRestoreProfile,
  onSetDefaultProfile,
}: ToolsSelectorProps): ReactElement {
  const selectorRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const [profileMenuIndex, setProfileMenuIndex] = useState(0)
  const [search, setSearch] = useState('')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(),
  )
  const selected = useMemo(() => new Set(selectedToolNames), [selectedToolNames])
  const selectedTokens = selectedTokenTotal(catalog, selectedToolNames)
  const activeProfile = catalog?.profiles.find(
    (profile) => profile.id === activeToolProfileId,
  )
  const profileOptions = [
    {
      id: 'custom',
      name: 'Custom',
      description: 'Manual tool selection',
    },
    ...(catalog?.profiles.map((profile) => ({
      id: profile.id,
      name: profile.name,
      description: profile.description,
    })) ?? []),
  ]
  const activeProfileOptionIndex = Math.max(
    0,
    profileOptions.findIndex((profile) => profile.id === (activeToolProfileId ?? 'custom')),
  )

  useEffect(() => {
    if (!open) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      const target = event.target as Node
      if (selectorRef.current?.contains(target)) return
      setProfileMenuOpen(false)
      setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer)
  }, [open])

  const selectedUnavailableNames = selectedToolNames.filter((name) => {
    const tool = catalog?.tools.find((item) => item.name === name)
    return !tool || !tool.available || !tool.allowed_for_agent
  })
  const visibleGroups = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!catalog) return []
    return catalog.groups
      .map((group) => ({
        ...group,
        tools: group.tools.filter(
          (tool) =>
            !needle ||
            tool.name.toLowerCase().includes(needle) ||
            tool.label.toLowerCase().includes(needle) ||
            tool.description.toLowerCase().includes(needle),
        ),
      }))
      .filter((group) => group.tools.length > 0)
  }, [catalog, search])

  const toggleTool = (name: string): void => {
    onSelectionChange(
      selected.has(name)
        ? selectedToolNames.filter((item) => item !== name)
        : [...selectedToolNames, name],
    )
  }

  const toggleGroup = (group: ToolCatalogGroup): void => {
    const state = groupSelection(group, selected)
    if (state.all) {
      onSelectionChange(
        selectedToolNames.filter((name) => !state.allNames.includes(name)),
      )
    } else {
      onSelectionChange([
        ...selectedToolNames,
        ...state.available.filter((name) => !selected.has(name)),
      ])
    }
  }

  const saveProfile = (): void => {
    const name = globalThis.prompt?.('Name this tool profile', 'Custom profile')
    if (name?.trim()) onSaveProfile?.(name.trim())
  }

  const duplicateProfile = (): void => {
    if (!activeToolProfileId) return
    const name = globalThis.prompt?.(
      'Name the duplicate profile',
      `${activeProfile?.name ?? 'Profile'} copy`,
    )
    if (name?.trim()) onDuplicateProfile?.(activeToolProfileId, name.trim())
  }

  const renameProfile = (): void => {
    if (!activeToolProfileId) return
    const name = globalThis.prompt?.(
      'Rename this tool profile',
      activeProfile?.name ?? 'Custom profile',
    )
    if (name?.trim()) onRenameProfile?.(activeToolProfileId, name.trim())
  }

  const selectProfile = (profileId: string): void => {
    setProfileMenuOpen(false)
    if (profileId !== 'custom') {
      onProfileChange(profileId)
    } else {
      onSelectionChange([...selectedToolNames])
    }
  }

  const handleProfileKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>): void => {
    const currentIndex = Math.min(profileMenuIndex, profileOptions.length - 1)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const direction = event.key === 'ArrowDown' ? 1 : -1
      const baseIndex = profileMenuOpen ? currentIndex : activeProfileOptionIndex
      setProfileMenuIndex(
        Math.max(0, Math.min(profileOptions.length - 1, baseIndex + direction)),
      )
      setProfileMenuOpen(true)
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      setProfileMenuIndex(event.key === 'Home' ? 0 : profileOptions.length - 1)
      setProfileMenuOpen(true)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!profileMenuOpen) {
        setProfileMenuIndex(activeProfileOptionIndex)
        setProfileMenuOpen(true)
      } else {
        selectProfile(profileOptions[currentIndex]?.id ?? 'custom')
      }
    } else if (event.key === 'Escape' && profileMenuOpen) {
      event.preventDefault()
      setProfileMenuOpen(false)
    }
  }

  return (
    <div ref={selectorRef} className="relative shrink-0">
      <button
        type="button"
        className={compact
          ? 'inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-[#7E22CE]/45 bg-[#7E22CE]/10 p-1.5 text-purple-100 transition-colors hover:border-[#C084FC] hover:bg-[#7E22CE]/20 disabled:cursor-not-allowed disabled:opacity-45'
          : 'inline-flex min-h-8 items-center gap-1.5 rounded-md border border-[#7E22CE]/45 bg-[#7E22CE]/10 px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-purple-100 transition-colors hover:border-[#C084FC] hover:bg-[#7E22CE]/20 disabled:cursor-not-allowed disabled:opacity-45'}
        aria-expanded={open}
        aria-controls="apex-tools-selector-panel"
        aria-label={`Tools: ${activeProfile?.name ?? 'Custom'}, ${selectedToolNames.length} selected, ${formatTokens(selectedTokens)} schema tokens`}
        disabled={disabled}
        onClick={() => {
          setProfileMenuOpen(false)
          setOpen((current) => !current)
        }}
      >
        {!compact ? (
          <>
            <span>Tools</span>
            <span className="normal-case tracking-normal text-zinc-300">
              {activeProfile?.name ?? 'Custom'} · {selectedToolNames.length} · {formatTokens(selectedTokens)}
            </span>
          </>
        ) : null}
        {open ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronRight className="size-3.5" aria-hidden />}
      </button>
      {open ? (
        <div
          id="apex-tools-selector-panel"
          role="dialog"
          aria-label="Tools selector"
          className="absolute bottom-full right-0 z-50 mb-2 max-h-[min(75vh,38rem)] w-[min(92vw,34rem)] overflow-y-auto rounded-xl border border-white/15 bg-zinc-950/95 p-3 text-left shadow-2xl backdrop-blur-xl scrollbar-thin"
        >
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-300">
                Prompt tools
              </p>
              <p className="mt-1 font-mono text-[10px] text-zinc-500">
                Selection narrows Agent policy; it never changes MCP settings.
              </p>
              {catalog?.provider_hosted_tools.length ? (
                <p className="mt-1 font-mono text-[10px] text-cyan-200/80">
                  Provider-hosted grounding active separately:{' '}
                  {catalog.provider_hosted_tools.map(formatHostedToolName).join(', ')}
                </p>
              ) : (
                <p className="mt-1 font-mono text-[10px] text-zinc-600">
                  Provider-hosted grounding is controlled separately from these APEX/MCP schemas.
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                setProfileMenuOpen(false)
                setOpen(false)
              }}
              className="rounded-md p-1.5 text-zinc-500 hover:bg-white/10 hover:text-white"
              aria-label="Close tools selector"
            >
              <X className="size-4" aria-hidden />
            </button>
          </div>

          <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <label className="sr-only" htmlFor="apex-tool-profile">
              Tool profile
            </label>
            <div className="relative min-w-0">
              <button
                id="apex-tool-profile"
                type="button"
                role="combobox"
                aria-expanded={profileMenuOpen}
                aria-controls="apex-tool-profile-options"
                aria-haspopup="listbox"
                aria-label="Tool profile"
                onClick={() => {
                  setProfileMenuIndex(activeProfileOptionIndex)
                  setProfileMenuOpen((current) => !current)
                }}
                onKeyDown={handleProfileKeyDown}
                className="flex min-h-10 w-full min-w-0 items-center gap-2 rounded-lg border border-white/10 bg-black/25 px-2.5 py-2 text-left font-mono text-[11px] text-zinc-200 transition-colors hover:border-[#7EB3FF]/55 hover:bg-[#0F4DB8]/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-zinc-100">
                    {activeProfile?.name ?? 'Custom'}
                  </span>
                  <span className="mt-0.5 block truncate text-[9px] text-zinc-500">
                    {activeProfile?.description ?? 'Manual tool selection'}
                  </span>
                </span>
                <ChevronDown
                  className={`size-3.5 shrink-0 text-[#6EA8FF] transition-transform ${profileMenuOpen ? 'rotate-180' : ''}`}
                  aria-hidden
                />
              </button>
              {profileMenuOpen ? (
                <div
                  id="apex-tool-profile-options"
                  role="listbox"
                  aria-label="Select tool profile"
                  className="hud-corner-brackets hud-glass hud-glass-solid absolute left-0 right-0 top-[calc(100%+0.5rem)] z-20 rounded-xl border border-white/10 p-2 shadow-2xl"
                >
                  <span className="hud-corner-bl" aria-hidden />
                  <span className="hud-corner-br" aria-hidden />
                  {profileOptions.map((profile, index) => {
                    const selectedProfile = profile.id === (activeToolProfileId ?? 'custom')
                    const highlighted = index === profileMenuIndex
                    return (
                      <button
                        key={profile.id}
                        type="button"
                        role="option"
                        aria-selected={selectedProfile}
                        onClick={() => selectProfile(profile.id)}
                        className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors focus-visible:outline-none ${highlighted ? 'bg-[#0F4DB8]/15' : ''} ${selectedProfile ? 'ring-1 ring-[#0F4DB8]/30' : ''} hover:bg-[#0F4DB8]/15`}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-mono text-[10px] uppercase tracking-[0.12em] text-zinc-100">
                            {profile.name}
                          </span>
                          <span className="mt-0.5 block truncate text-[10px] text-zinc-500">
                            {profile.description}
                          </span>
                        </span>
                        {selectedProfile ? (
                          <Check className="mt-0.5 size-3.5 shrink-0 text-[#39FF88]" aria-hidden />
                        ) : null}
                      </button>
                    )
                  })}
                </div>
              ) : null}
            </div>
            <div className="flex items-center gap-1">
              <button type="button" onClick={saveProfile} disabled={!onSaveProfile} className="rounded-md border border-white/10 p-2 text-zinc-400 hover:border-white/25 hover:text-white disabled:opacity-35" aria-label="Save current tool profile" title="Save current profile"><Save className="size-3.5" aria-hidden /></button>
              <button type="button" onClick={duplicateProfile} disabled={!activeToolProfileId || !onDuplicateProfile} className="rounded-md border border-white/10 p-2 text-zinc-400 hover:border-white/25 hover:text-white disabled:opacity-35" aria-label="Duplicate tool profile" title="Duplicate profile"><Copy className="size-3.5" aria-hidden /></button>
              <button type="button" onClick={renameProfile} disabled={!activeToolProfileId || activeProfile?.built_in || !onRenameProfile} className="rounded-md border border-white/10 p-2 text-zinc-400 hover:border-white/25 hover:text-white disabled:opacity-35" aria-label="Rename tool profile" title="Rename custom profile"><Pencil className="size-3.5" aria-hidden /></button>
              <button type="button" onClick={() => { if (!activeToolProfileId || !onDeleteProfile) return; if (globalThis.confirm && !globalThis.confirm('Delete this custom tool profile?')) return; onDeleteProfile(activeToolProfileId) }} disabled={!activeToolProfileId || activeProfile?.built_in || !onDeleteProfile} className="rounded-md border border-white/10 p-2 text-zinc-400 hover:border-red-300/60 hover:text-red-200 disabled:opacity-35" aria-label="Delete tool profile" title="Delete custom profile"><Trash2 className="size-3.5" aria-hidden /></button>
              <button type="button" onClick={() => activeToolProfileId && onRestoreProfile?.(activeToolProfileId)} disabled={!activeToolProfileId || !onRestoreProfile} className="rounded-md border border-white/10 p-2 text-zinc-400 hover:border-amber-300/60 hover:text-amber-200 disabled:opacity-35" aria-label="Restore tool profile" title="Restore profile"><RotateCcw className="size-3.5" aria-hidden /></button>
              <button type="button" onClick={() => activeToolProfileId && onSetDefaultProfile?.(activeToolProfileId)} disabled={!activeToolProfileId || !onSetDefaultProfile} className="rounded-md border border-white/10 p-2 text-zinc-400 hover:border-[#7EB3FF]/60 hover:text-white disabled:opacity-35" aria-label="Set default tool profile" title="Set default for this Agent"><Star className="size-3.5" aria-hidden /></button>
            </div>
          </div>

          <div className="mt-2 flex items-center gap-2">
            <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-white/10 bg-black/30 px-2.5 py-2">
              <Search className="size-3.5 shrink-0 text-zinc-500" aria-hidden />
              <span className="sr-only">Search tools</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-zinc-200 outline-none placeholder:text-zinc-600"
                placeholder="Filter tools"
                aria-label="Search tools"
              />
            </label>
            <button type="button" onClick={() => onSelectionChange(catalog?.tools.filter((tool) => tool.available && tool.allowed_for_agent).map((tool) => tool.name) ?? [])} className="rounded-md border border-white/10 px-2 py-2 font-mono text-[9px] uppercase tracking-wider text-zinc-400 hover:border-[#7EB3FF]/60 hover:text-white">All</button>
            <button type="button" onClick={() => onSelectionChange([])} className="rounded-md border border-white/10 px-2 py-2 font-mono text-[9px] uppercase tracking-wider text-zinc-400 hover:border-[#7EB3FF]/60 hover:text-white">Clear</button>
          </div>

          <div className="mt-3 space-y-2">
            {visibleGroups.length === 0 ? (
              <p className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-3 text-xs text-zinc-500">
                {catalog ? 'No tools match this filter.' : 'Loading tool catalog…'}
              </p>
            ) : (
              visibleGroups.map((group) => {
                const groupState = groupSelection(group, selected)
                const expanded = expandedGroups.has(group.id) || search.trim().length > 0
                return (
                  <section key={group.id} className="rounded-lg border border-white/10 bg-white/[0.02]">
                    <div className="flex items-center gap-2 px-2.5 py-2">
                      <button type="button" onClick={() => setExpandedGroups((current) => { const next = new Set(current); if (next.has(group.id)) next.delete(group.id); else next.add(group.id); return next })} className="rounded p-0.5 text-zinc-500 hover:text-white" aria-label={`${expanded ? 'Collapse' : 'Expand'} ${group.label}`} aria-expanded={expanded}>{expanded ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronRight className="size-3.5" aria-hidden />}</button>
                      <input type="checkbox" checked={groupState.all} ref={(element) => { if (element) element.indeterminate = groupState.some }} onChange={() => toggleGroup(group)} disabled={groupState.available.length === 0} aria-label={`Select ${group.label}`} className="size-3.5 accent-[#A855F7]" />
                      <span className="min-w-0 flex-1 font-mono text-[10px] uppercase tracking-wider text-zinc-300">{group.label}</span>
                      <span className="font-mono text-[9px] text-zinc-500">{group.tool_count} · {formatTokens(group.schema_token_subtotal)}</span>
                    </div>
                    {expanded ? <div className="space-y-1 border-t border-white/5 px-2.5 py-2">{group.tools.map((tool) => { const checked = selected.has(tool.name); const unavailable = !tool.available || !tool.allowed_for_agent; return <label key={tool.name} title={unavailable ? tool.unavailable_reason ?? 'Unavailable' : tool.description} className={`flex items-start gap-2 rounded-md px-1.5 py-1.5 ${unavailable ? checked ? 'cursor-pointer opacity-70' : 'cursor-not-allowed opacity-45' : 'cursor-pointer hover:bg-white/[0.04]'}`}><input type="checkbox" checked={checked} disabled={unavailable && !checked} onChange={() => toggleTool(tool.name)} className="mt-0.5 size-3.5 accent-[#A855F7]" /><span className="min-w-0 flex-1"><span className="block text-[11px] text-zinc-300">{tool.label}</span><span className="block truncate font-mono text-[9px] text-zinc-600">{tool.name}</span>{unavailable && tool.unavailable_reason ? <span className="mt-0.5 block text-[10px] text-red-200">{tool.unavailable_reason}</span> : null}</span><span className="shrink-0 font-mono text-[9px] text-zinc-500">{formatTokens(tool.estimated_schema_tokens)}</span></label> })}</div> : null}
                  </section>
                )
              })
            )}
          </div>

          {selectedUnavailableNames.length > 0 ? (
            <section className="mt-3 rounded-lg border border-red-300/20 bg-red-950/15 p-2.5" aria-label="Unavailable selected tools">
              <div className="flex items-center justify-between gap-2">
                <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-red-200">
                  Unavailable selections
                </p>
                <button
                  type="button"
                  onClick={() => onSelectionChange(
                    selectedToolNames.filter((name) => !selectedUnavailableNames.includes(name)),
                  )}
                  className="rounded-md border border-red-300/25 px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-red-100 hover:border-red-200/60"
                >
                  Remove unavailable
                </button>
              </div>
              <ul className="mt-2 space-y-1">
                {selectedUnavailableNames.map((name) => {
                  const tool = catalog?.tools.find((item) => item.name === name)
                  return (
                    <li key={name} className="flex items-start gap-2 font-mono text-[10px] text-red-100">
                      <span className="min-w-0 flex-1">
                        <span className="block break-all">{name || '(blank selection)'}</span>
                        <span className="block text-red-200/70">
                          {tool?.unavailable_reason ?? 'This capability is no longer catalogued.'}
                        </span>
                      </span>
                      <button
                        type="button"
                        onClick={() => onSelectionChange(selectedToolNames.filter((item) => item !== name))}
                        className="shrink-0 rounded border border-red-300/20 px-1.5 py-0.5 text-[9px] text-red-100 hover:border-red-200/60"
                        aria-label={`Remove unavailable tool ${name || 'blank selection'}`}
                      >
                        Remove
                      </button>
                    </li>
                  )
                })}
              </ul>
            </section>
          ) : null}

          <div className="mt-3 rounded-lg border border-purple-300/15 bg-purple-950/10 p-2.5">
            <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-zinc-300">
              <span>Selected tools</span>
              <span>{selectedToolNames.length} · {formatTokens(selectedTokens)} schema tokens</span>
            </div>
            {preflightLoading ? <p className="mt-2 font-mono text-[10px] text-zinc-500">Estimating next request…</p> : null}
            {catalogError ? <p className="mt-2 text-[10px] leading-relaxed text-red-200" role="alert">{catalogError}</p> : null}
            {preflightError ? <p className="mt-2 text-[10px] leading-relaxed text-red-200" role="alert">{preflightError}</p> : null}
            {profileError ? <p className="mt-2 text-[10px] leading-relaxed text-red-200" role="alert">{profileError}</p> : null}
            {profileFeedback ? <p className="mt-2 text-[10px] leading-relaxed text-emerald-200" role="status">{profileFeedback}</p> : null}
            {preflight ? <><dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] text-zinc-500"><dt>System</dt><dd className="text-right text-zinc-300">{formatTokens(preflight.breakdown.system_instructions)}</dd><dt>History</dt><dd className="text-right text-zinc-300">{formatTokens(preflight.breakdown.conversation_history)}</dd><dt>HUD context</dt><dd className="text-right text-zinc-300">{formatTokens(preflight.breakdown.hud_context)}</dd><dt>Tool schemas</dt><dd className="text-right text-zinc-300">{formatTokens(preflight.breakdown.selected_tool_schemas)}</dd><dt>Prompt</dt><dd className="text-right text-zinc-300">{formatTokens(preflight.breakdown.current_prompt)}</dd><dt>Total estimate</dt><dd className="text-right text-purple-200">{formatTokens(preflight.breakdown.total)}</dd></dl><Utilization estimate={preflight} />{preflight.warning ? <p className="mt-2 text-[10px] leading-relaxed text-amber-200" role="status">{preflight.warning}</p> : null}{preflight.selection.rejected_tools.length > 0 ? <ul className="mt-2 space-y-1 text-[10px] text-red-200" aria-label="Preflight rejected tools">{preflight.selection.rejected_tools.map((failure) => <li key={`${failure.name}-${failure.code}`}>{failure.name || '(blank selection)'}: {failure.reason}</li>)}</ul> : null}</> : null}
            <p className="mt-2 flex items-center gap-1 font-mono text-[9px] text-zinc-600"><Check className="size-3" aria-hidden /> Estimates use the model-facing schemas.</p>
          </div>
        </div>
      ) : null}
    </div>
  )
}
