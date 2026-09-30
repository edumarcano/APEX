import type { ReactElement } from 'react'

export function DeferredWorkspaceLoading({ label }: { label: string }): ReactElement {
  return <div className="flex min-h-40 flex-1 items-center justify-center" role="status" aria-label={`Loading ${label}`}>
    <p className="font-orbitron text-xs uppercase tracking-[0.14em] text-zinc-400">Loading {label}…</p>
  </div>
}

export function DeferredWorkspaceError({ label, retry }: { label: string; retry: () => void }): ReactElement {
  return <section className="m-4 rounded-xl border border-red-500/25 bg-red-950/20 p-5" role="alert">
    <h2 className="font-orbitron text-sm font-semibold text-red-200">{label} could not load</h2>
    <p className="mt-2 text-sm text-zinc-300">Retry loading this workspace or reload APEX. Reloading will discard any unsent text.</p>
    <div className="mt-4 flex flex-wrap gap-2">
      <button type="button" onClick={retry} className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400">Retry</button>
      <button type="button" onClick={() => { if (window.confirm('Reload APEX? Any unsent text will be lost.')) window.location.reload() }} className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400">Reload APEX</button>
    </div>
  </section>
}
