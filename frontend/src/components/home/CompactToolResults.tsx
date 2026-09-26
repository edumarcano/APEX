import { useState, type ReactElement } from 'react'

import { requiresFullToolResult } from '../../lib/toolOutputs'
import type { ToolOutputItem } from '../../types/telemetry'
import { CortexToolCards } from '../CortexToolCards'

function toolLabel(name: string): string {
  return name.replace(/^get_/, '').replace(/_/g, ' ')
}

/**
 * Home presentation of the same tool outputs Cortex renders as cards. Routine
 * results collapse into chips that expand into the Cortex card; failures,
 * pending approvals, and trust-labelled results always render in full.
 */
export function CompactToolResults({ toolOutputs }: { toolOutputs: ToolOutputItem[] }): ReactElement | null {
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set())
  if (toolOutputs.length === 0) return null
  const full = toolOutputs.filter(requiresFullToolResult)
  const compact = toolOutputs
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => !requiresFullToolResult(item))
  const toggle = (index: number): void => setExpanded((current) => {
    const next = new Set(current)
    if (next.has(index)) next.delete(index)
    else next.add(index)
    return next
  })
  return <div className="mt-3 space-y-2" data-slot="compact-tool-results">
    {full.length > 0 ? <CortexToolCards toolOutputs={full} /> : null}
    {compact.length > 0 ? <ul className="flex flex-wrap gap-1.5" aria-label="Tool results">
      {compact.map(({ item, index }) => <li key={`${item.name}-${index}`}>
        <button
          type="button"
          aria-expanded={expanded.has(index)}
          onClick={() => toggle(index)}
          className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 font-mono text-[10px] capitalize text-zinc-300 hover:border-[#0F4DB8]/50 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF]"
        >
          {toolLabel(item.name)}
        </button>
      </li>)}
    </ul> : null}
    {compact.filter(({ index }) => expanded.has(index)).map(({ item, index }) => <CortexToolCards key={`${item.name}-${index}-card`} toolOutputs={[item]} />)}
  </div>
}
