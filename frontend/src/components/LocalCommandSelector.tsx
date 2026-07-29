import type { ReactElement } from 'react'

import type {
  LocalCommandStatus,
  LocalContextUsage,
  LocalToolScope,
} from '../types/telemetry'

interface LocalCommandSelectorProps {
  commands: LocalCommandStatus[]
  commandsOpen: boolean
  slashPrefix: string | null
  activeScope: LocalToolScope | null
  contextUsage: LocalContextUsage | null
  onToggle: () => void
  onSelect: (command: LocalCommandStatus) => void
}

export function LocalCommandSelector({
  commands,
  commandsOpen,
  slashPrefix,
  activeScope,
  contextUsage,
  onToggle,
  onSelect,
}: LocalCommandSelectorProps): ReactElement {
  const matchingCommands = slashPrefix
    ? commands.filter((command) => command.command.startsWith(slashPrefix))
    : []
  const visibleCommands = slashPrefix ? matchingCommands : commands
  const displayedPromptTokens = contextUsage
    ? (contextUsage.peak_prompt_tokens ?? contextUsage.estimated_prompt_tokens)
    : null

  return (
    <div className="relative mb-2 font-mono text-[10px]">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggle}
          className="rounded-md border border-white/10 bg-zinc-950/70 px-2 py-1 uppercase tracking-wider text-zinc-300 hover:border-[#0F4DB8]/50"
          aria-expanded={commandsOpen}
        >
          Commands
        </button>
        <span className="text-zinc-500">
          {activeScope ? `/${activeScope} armed · one shot` : 'No tools'}
        </span>
        {contextUsage && displayedPromptTokens !== null ? (
          <span
            className={`ml-auto ${
              displayedPromptTokens / contextUsage.context_window >= 0.8
                ? 'text-amber-400'
                : 'text-zinc-500'
            }`}
            title={`${contextUsage.history_messages_dropped} history messages trimmed`}
          >
            {displayedPromptTokens}/{contextUsage.context_window} tokens
          </span>
        ) : null}
      </div>
      {commandsOpen || matchingCommands.length > 0 ? (
        <div className="absolute bottom-full z-30 mb-2 grid w-full gap-1 rounded-lg border border-white/10 bg-zinc-950/95 p-2 shadow-xl">
          {visibleCommands.map((command) => (
            <button
              key={command.key}
              type="button"
              onClick={() => onSelect(command)}
              disabled={!command.available}
              title={command.unavailable_reason ?? undefined}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-left text-zinc-300 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="w-20 text-[#4B82E3]">{command.command}</span>
              <span className="min-w-0 flex-1 truncate">{command.description}</span>
              <span className="shrink-0 text-zinc-600">
                ~{command.estimated_schema_tokens}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
