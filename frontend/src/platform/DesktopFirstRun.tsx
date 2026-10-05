import { useState, type ReactElement } from 'react'

import type { DesktopSetupState, ImportItem } from './contracts'

type DesktopFirstRunProps = {
  setup: DesktopSetupState
  busy: boolean
  actionError: string | null
  onFreshStart: () => void
  onChooseImport: () => void
  onImport: () => void
  onRecover: () => void
  onQuit: () => Promise<void>
}

const buttonClass = 'rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400 disabled:cursor-wait disabled:opacity-60'

export default function DesktopFirstRun({ setup, busy, actionError, onFreshStart, onChooseImport, onImport, onRecover, onQuit }: DesktopFirstRunProps): ReactElement {
  const [quitPending, setQuitPending] = useState(false)
  const [quitError, setQuitError] = useState(false)
  const preview = setup.preview
  const importing = setup.phase === 'importing'
  const checking = setup.phase === 'checking'
  const recovery = setup.phase === 'recovery_required'
  const heading = checking ? 'Checking APEX data' : importing ? 'Importing APEX data' : recovery ? 'Import recovery is required' : setup.phase === 'failed' ? 'APEX setup needs attention' : preview ? 'Review imported data' : 'Choose how to set up APEX'

  const quit = async (): Promise<void> => {
    if (quitPending) return
    setQuitPending(true)
    setQuitError(false)
    try {
      await onQuit()
    } catch {
      setQuitError(true)
    } finally {
      setQuitPending(false)
    }
  }

  return <main className="flex min-h-dvh w-full items-center justify-center overflow-auto bg-black px-5 py-8 text-slate-200">
    <section className="w-full max-w-3xl rounded-2xl border border-white/10 bg-white/[0.04] p-6 shadow-2xl sm:p-8" aria-labelledby="desktop-setup-title">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-300">APEX Desktop</p>
      <h1 id="desktop-setup-title" className="mt-3 text-xl font-semibold text-white">{heading}</h1>
      {checking ? <p className="mt-3 text-sm text-zinc-300" role="status" aria-live="polite">Checking the selected APEX data profile.</p> : null}
      {checking && setup.progress ? <div className="mt-5" role="status" aria-live="polite">
        <p className="text-sm text-zinc-300">{progressStageLabel(setup.progress.stage)}: {formatBytes(setup.progress.completed_bytes)} of {formatBytes(setup.progress.total_bytes)}</p>
        {setup.progress.total_bytes > 0 ? <progress className="mt-3 h-2 w-full accent-emerald-400" max={setup.progress.total_bytes} value={Math.min(setup.progress.completed_bytes, setup.progress.total_bytes)} aria-label="Setup progress" /> : null}
      </div> : null}

      {setup.phase === 'choice_required' && !preview ? <>
        <p className="mt-3 text-sm leading-relaxed text-zinc-300">Choose Fresh Start for an empty APEX profile, or import data from a stopped APEX checkout. A source checkout stores data in that checkout by default; if it used <code className="text-zinc-100">APEX_DATA_DIR</code>, choose that data folder. APEX will preview managed files before copying anything.</p>
        <div className="mt-6 flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={onFreshStart} className={buttonClass}>Fresh Start</button>
          <button type="button" disabled={busy} onClick={onChooseImport} className={buttonClass}>Import from a checkout</button>
        </div>
      </> : null}

      {preview ? <>
        <p className="mt-3 text-sm leading-relaxed text-zinc-300">Review the managed files APEX found. Import copies compatible files into this data folder and keeps the source intact.</p>
        <div className="mt-5 overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <thead className="bg-white/[0.04] text-xs uppercase tracking-wide text-zinc-400">
              <tr><th scope="col" className="px-3 py-2">Managed item</th><th scope="col" className="px-3 py-2">Action</th><th scope="col" className="px-3 py-2 text-right">Files</th><th scope="col" className="px-3 py-2 text-right">Size</th></tr>
            </thead>
            <tbody className="divide-y divide-white/[0.08]">
              {preview.items.map((item) => <PreviewRow key={`${item.category}:${item.path}`} item={item} />)}
              {preview.items.length === 0 ? <tr><td className="px-3 py-3 text-zinc-400" colSpan={4}>No managed files were found.</td></tr> : null}
            </tbody>
          </table>
        </div>
        {preview.warnings.length > 0 ? <section className="mt-4 rounded-lg border border-amber-400/25 bg-amber-400/5 p-3" aria-label="Import warnings">
          <h2 className="text-sm font-medium text-amber-200">Warnings</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-300">{preview.warnings.map((warning, index) => <li key={`${index}:${warning}`}>{warningMessage(warning)}</li>)}</ul>
        </section> : null}
        {preview.blockers.length > 0 ? <section className="mt-4 rounded-lg border border-red-400/25 bg-red-400/5 p-3" aria-label="Import blockers">
          <h2 className="text-sm font-medium text-red-200">Import cannot continue</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-300">{preview.blockers.map((blocker, index) => <li key={`${index}:${blocker}`}>{blockerMessage(blocker)}</li>)}</ul>
        </section> : null}
        <div className="mt-5 flex flex-wrap gap-2">
          {setup.phase === 'preview_ready' && preview.can_import ? <button type="button" disabled={busy} onClick={onImport} className={buttonClass}>Import these files</button> : null}
          {setup.phase !== 'importing' ? <button type="button" disabled={busy} onClick={onChooseImport} className={buttonClass}>Choose another folder</button> : null}
        </div>
      </> : null}

      {importing ? <div className="mt-5" role="status" aria-live="polite">
        <p className="text-sm text-zinc-300">{setup.progress ? `${progressStageLabel(setup.progress.stage)}: ${formatBytes(setup.progress.completed_bytes)} of ${formatBytes(setup.progress.total_bytes)}` : 'Preparing the data import.'}</p>
        {setup.progress && setup.progress.total_bytes > 0 ? <progress className="mt-3 h-2 w-full accent-emerald-400" max={setup.progress.total_bytes} value={Math.min(setup.progress.completed_bytes, setup.progress.total_bytes)} aria-label="Import progress" /> : null}
      </div> : null}

      {recovery ? <>
        <p className="mt-3 text-sm leading-relaxed text-zinc-300">An interrupted import needs recovery before APEX can open. Recovery checks the import journal and restores the destination to a known state.</p>
        <button type="button" disabled={busy} onClick={onRecover} className={`${buttonClass} mt-5`}>Recover import</button>
      </> : null}

      {setup.phase === 'failed' ? <>
        <p className="mt-3 text-sm text-red-200" role="alert">{setupErrorMessage(setup.error_code)}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={onRecover} className={buttonClass}>Retry setup</button>
        </div>
      </> : null}
      {actionError ? <p className="mt-3 text-sm text-red-200" role="alert">{actionError}</p> : null}
      {quitError ? <p className="mt-3 text-sm text-red-200" role="alert">APEX could not quit cleanly. Try again, or wait for setup to finish and quit once more.</p> : null}
      <div className="mt-6 border-t border-white/10 pt-4">
        <p className="text-xs leading-relaxed text-zinc-400">Fresh Start creates a new profile. It does not remove or reset files from another APEX folder.</p>
        <button type="button" disabled={quitPending} onClick={() => void quit()} className={`${buttonClass} mt-4`}>Quit APEX</button>
      </div>
    </section>
  </main>
}

function PreviewRow({ item }: { item: ImportItem }): ReactElement {
  const action = item.disposition === 'copy' ? 'Copy' : item.disposition === 'missing' ? 'Not present' : item.disposition === 'retain_external' ? 'Keep external' : 'Reuse existing'
  return <tr>
    <th scope="row" className="max-w-[20rem] truncate px-3 py-2 font-medium text-zinc-200" title={item.path}>{item.path}</th>
    <td className="px-3 py-2 text-zinc-300">{action}{item.disposition === 'retain_external' ? <span className="sr-only">; referenced files stay in their current location</span> : null}</td>
    <td className="px-3 py-2 text-right tabular-nums text-zinc-300">{item.file_count.toLocaleString()}</td>
    <td className="px-3 py-2 text-right tabular-nums text-zinc-300">{formatBytes(item.total_bytes)}</td>
  </tr>
}

function formatBytes(value: number): string {
  if (value < 1_000) return `${value} B`
  const units = ['kB', 'MB', 'GB', 'TB']
  let size = value / 1_000
  let index = 0
  while (size >= 1_000 && index < units.length - 1) {
    size /= 1_000
    index += 1
  }
  return `${size < 10 ? size.toFixed(1) : Math.round(size)} ${units[index]}`
}

function progressStageLabel(stage: string): string {
  if (stage === 'inventory') return 'Reviewing managed files'
  if (stage === 'copying') return 'Copying files'
  if (stage === 'database') return 'Checking database'
  if (stage === 'database_preview') return 'Preparing database preview'
  if (stage === 'validating') return 'Validating imported data'
  if (stage === 'recovery_verify') return 'Verifying recovery'
  return 'Working'
}

function setupErrorMessage(code: string | null): string {
  if (code === 'source_busy_or_unreadable') return 'APEX could not read the source folder. Stop APEX there and check that you can access the folder, then choose it again.'
  if (code === 'source_activity_uncertain') return 'APEX could not confirm that the source is stopped. Close all APEX processes before trying again.'
  if (code === 'source_active') return 'Stop the source APEX process before importing its data.'
  if (code === 'destination_database_exists' || code === 'destination_exists') return 'This data folder already contains an APEX database. Existing data was left in place; imports cannot replace it.'
  if (code === 'destination_path_exists') return 'The import destination already contains files. No existing files were replaced; use an empty APEX data folder.'
  if (code === 'preview_stale' || code === 'stale_preview' || code === 'preview-stale') return 'The source changed after preview. Choose it again to review a fresh preview.'
  if (code === 'source_database_missing') return 'The selected folder does not contain an APEX database. Choose the source checkout’s actual data folder.'
  if (code === 'source_database_incompatible') return 'This database uses a core schema that this APEX version cannot import.'
  if (code === 'source_invalid') return 'This is not a usable APEX data folder. Choose the checkout’s data folder or its configured APEX_DATA_DIR.'
  if (code === 'source_reparse_point') return 'The source contains a linked folder that cannot be imported safely. Choose a local data folder without links.'
  if (code === 'source_inventory_too_large') return 'The selected folder contains more files than APEX can safely preview. Choose the specific APEX data folder.'
  if (code === 'source_changed') return 'The source changed during import. Choose it again to review a fresh preview.'
  if (code === 'destination_active') return 'The destination data folder is in use by another APEX process. Close that process and retry setup.'
  if (code === 'import_recovery_required' || code === 'import_recovery_unproven' || code === 'import_journal_invalid') return 'An interrupted import needs recovery before setup can continue.'
  if (code === 'import_blocked') return 'The current import preview has blockers. Choose another source folder and review its contents.'
  if (code === 'protocol_error') return 'APEX could not read the native setup status. Quit and reopen the desktop app.'
  return 'APEX could not complete setup. The data source and destination were left available for recovery or another attempt.'
}

function warningMessage(code: string): string {
  if (code === 'configuration_needs_review') return 'Review the imported configuration before using APEX.'
  if (code === 'microsoft_cache_path_needs_review') return 'Review Microsoft account and cache paths after import.'
  if (code === 'external_path_needs_review') return 'Some files are stored outside the managed data folder and will stay in their current location.'
  if (code === 'relative_credential_path_needs_review') return 'A credential refers to a relative file path that needs review.'
  if (code === 'retrieval_schema_unsupported') return 'The retrieval cache uses an unsupported schema. Its database bytes are kept, retrieval remains disabled, and canonical data remains available.'
  return 'APEX marked part of this source for review. Its contents will not be shown in this preview.'
}

function blockerMessage(code: string): string {
  if (code === 'source_active' || code === 'source_activity_uncertain') return setupErrorMessage(code)
  if (code === 'source_database_missing') return 'The selected folder does not contain the APEX database.'
  if (code === 'source_database_incompatible') return 'The database’s core schema is not compatible with this APEX version.'
  if (code === 'destination_database_exists') return 'The destination already contains an APEX database; import cannot replace it.'
  if (code === 'destination_path_exists') return 'The destination already contains files; import cannot overwrite them.'
  return 'APEX cannot safely import this source item. Choose another data folder or resolve the issue before retrying.'
}
