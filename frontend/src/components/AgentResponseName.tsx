import type { ReactElement } from 'react'

export function AgentResponseName({ name }: { name: string }): ReactElement {
  return <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.15em] text-[#C084FC]">{name}</p>
}
