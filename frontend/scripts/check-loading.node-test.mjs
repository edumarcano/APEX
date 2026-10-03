import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const script = fileURLToPath(new URL('./check-loading.mjs', import.meta.url))
const sourceBoundaries = [
  'src/components/SettingsPanel.tsx',
  'src/components/CortexWorkspace.tsx',
  'src/components/ActivityReportsWorkspace.tsx',
  'src/components/briefing/BriefingView.tsx',
  'src/components/briefing/BriefingSpeechControl.tsx',
]

test('counts preloaded static imports once and resolves baseline manifest import keys', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const current = path.join(root, 'current')
    const baseline = path.join(root, 'baseline')
    await createDist(current, { report: reportFixture() })
    await createDist(baseline, { report: null })

    const result = run(['--dist', current, '--baseline', baseline])
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /Current build:[\s\S]*initial: .*\(2 JS files\)/)
    assert.match(result.stdout, /Current build:[\s\S]*deferred: .*\(1 JS files\)/)
    assert.match(result.stdout, /Baseline build:[\s\S]*initial: .*\(2 JS files\)/)
    assert.match(result.stdout, /Baseline build:[\s\S]*deferred: .*\(1 JS files\)/)
    assert.match(result.stdout, /Current minus baseline:/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects deferred modules pulled into the HTML preload closure', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const report = reportFixture()
    report.chunks.find((chunk) => chunk.fileName === 'assets/shared.js').modules.push(sourceBoundaries[0])
    const dist = path.join(root, 'dist')
    await createDist(dist, { report })

    const result = run(['--dist', dist])
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /deferred source module is in the initial HTML\/static import closure: src\/components\/SettingsPanel\.tsx/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects Tauri desktop code pulled into the browser startup graph', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const report = reportFixture()
    report.chunks.find((chunk) => chunk.fileName === 'assets/shared.js').modules.push('node_modules/@tauri-apps/api/core.js')
    const dist = path.join(root, 'dist')
    await createDist(dist, { report })

    const result = run(['--dist', dist])
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /Tauri API dependency is in the browser HTML\/static import closure/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects a missing production graph report', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const dist = path.join(root, 'dist')
    await createDist(dist, { report: null })

    const result = run(['--dist', dist])
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /missing or invalid production graph report/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects malformed production graph metadata', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const dist = path.join(root, 'dist')
    await createDist(dist, { report: 'malformed' })

    const result = run(['--dist', dist])
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /missing or invalid production graph report/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects a missing Vite manifest even when the graph report exists', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const dist = path.join(root, 'dist')
    await createDist(dist, { report: reportFixture() })
    await rm(path.join(dist, '.vite/manifest.json'))

    const result = run(['--dist', dist])
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /missing or invalid Vite build manifest/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('rejects unresolved imports in the baseline Vite manifest', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-loading-'))
  try {
    const current = path.join(root, 'current')
    const baseline = path.join(root, 'baseline')
    await createDist(current, { report: reportFixture() })
    await createDist(baseline, { report: null })
    const manifestPath = path.join(baseline, '.vite/manifest.json')
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
    manifest['src/main.ts'].imports = ['missing/import.ts']
    await writeFile(manifestPath, JSON.stringify(manifest))

    const result = run(['--dist', current, '--baseline', baseline])
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /baseline manifest entry assets\/main\.js references missing import key missing\/import\.ts/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

function run(args) {
  return spawnSync(process.execPath, [script, ...args], { encoding: 'utf8' })
}

async function createDist(root, { report }) {
  await mkdir(path.join(root, '.vite'), { recursive: true })
  await mkdir(path.join(root, 'assets'), { recursive: true })
  await writeFile(path.join(root, 'index.html'), '<link rel="modulepreload" href="/assets/shared.js"><script type="module" src="/assets/main.js"></script>')
  await writeFile(path.join(root, 'assets/main.js'), 'main')
  await writeFile(path.join(root, 'assets/shared.js'), 'shared')
  await writeFile(path.join(root, 'assets/deferred.js'), 'deferred')
  await writeFile(path.join(root, '.vite/manifest.json'), JSON.stringify({
    'src/main.ts': { file: 'assets/main.js', imports: ['src/shared.ts'], dynamicImports: ['src/deferred.ts'], isEntry: true },
    'src/shared.ts': { file: 'assets/shared.js', imports: [] },
    'src/deferred.ts': { file: 'assets/deferred.js', imports: [] },
  }))
  if (report) await writeFile(path.join(root, '.vite/loading-report.json'), typeof report === 'string' ? report : JSON.stringify(report))
}

function reportFixture() {
  return {
    chunks: [
      { fileName: 'assets/main.js', imports: ['assets/shared.js'], dynamicImports: ['assets/deferred.js'], modules: ['src/App.tsx'] },
      { fileName: 'assets/shared.js', imports: [], dynamicImports: [], modules: [] },
      { fileName: 'assets/deferred.js', imports: [], dynamicImports: [], modules: [
        'src/platform/DesktopAdmission.tsx',
        'src/platform/tauri.ts',
        'node_modules/@tauri-apps/api/core.js',
        ...sourceBoundaries,
        'node_modules/react-markdown/index.js',
        'node_modules/remark-gfm/index.js',
      ] },
    ],
  }
}
