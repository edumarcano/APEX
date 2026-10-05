import { afterEach, describe, expect, it, vi } from 'vitest'

import { createTauriPlatform } from './tauri'

const native = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}))

vi.mock('@tauri-apps/api/core', () => ({ invoke: native.invoke }))
vi.mock('@tauri-apps/api/event', () => ({ listen: native.listen }))

afterEach(() => vi.clearAllMocks())

describe('Tauri setup platform contract', () => {
  it('uses the allowlisted setup commands and sends only the contracted arguments', async () => {
    native.invoke.mockResolvedValue(undefined)
    const platform = createTauriPlatform()

    await platform.getSetupStatus()
    await platform.pickImportSource()
    await platform.previewImport('C:\\APEX-source')
    await platform.importData('preview-token')
    await platform.freshStart()
    await platform.recoverImport()

    expect(native.invoke.mock.calls).toEqual([
      ['desktop_setup_status'],
      ['desktop_import_pick_source'],
      ['desktop_import_preview', { sourceDir: 'C:\\APEX-source' }],
      ['desktop_import_commit', { previewId: 'preview-token' }],
      ['desktop_fresh_start'],
      ['desktop_import_recover'],
    ])
  })

  it('subscribes to setup-state wakeups without interpreting event payloads', async () => {
    const unlisten = vi.fn()
    native.listen.mockResolvedValue(unlisten)
    const platform = createTauriPlatform()
    const wake = vi.fn()

    const unsubscribe = await platform.subscribeSetupState(wake)
    expect(native.listen).toHaveBeenCalledExactlyOnceWith('desktop-setup-state', wake)
    unsubscribe()
    expect(unlisten).toHaveBeenCalledOnce()
  })
})
