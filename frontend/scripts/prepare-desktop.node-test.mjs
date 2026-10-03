import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { assembleDesktopOutput } from './build-desktop.mjs'
import { stageBundle, verifyBundle } from './prepare-desktop.mjs'

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-bundle-'))
  await fixtureAt(t, root)
  return root
}

test('stages the complete bundle after checking hashes and build identity', async (t) => {
  const source = await fixture(t)
  const parent = await mkdtemp(path.join(os.tmpdir(), 'apex-stage-'))
  t.after(() => rm(parent, { recursive: true, force: true }))
  const resources = path.join(parent, 'resources')
  const destination = path.join(resources, 'backend-bundle')
  await mkdir(resources)
  assert.equal(await stageBundle(source, destination, resources), 'test-build')
  assert.equal(await readFile(path.join(destination, '_internal/licenses/example.txt'), 'utf8'), 'internal license')
  assert.equal(await readFile(path.join(destination, 'licenses/source-material/example.txt'), 'utf8'), 'source')
  assert.equal(await readFile(path.join(destination, 'THIRD_PARTY_NOTICES.md'), 'utf8'), 'notices')
  assert.equal(await verifyBundle(destination), 'test-build')
})

test('rejects a modified packaged file before staging', async (t) => {
  const source = await fixture(t)
  await writeFile(path.join(source, 'apex-backend.exe'), 'modified')
  await assert.rejects(verifyBundle(source), /failed integrity validation/)
})

test('rejects a build-info identifier that differs from the manifest', async (t) => {
  const source = await fixture(t)
  const buildInfo = path.join(source, '_internal', 'build-info.json')
  await writeFile(buildInfo, JSON.stringify({ build_id: 'other-build' }))
  const manifestPath = path.join(source, 'bundle-manifest.json')
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  const bytes = await readFile(buildInfo)
  const entry = manifest.files.find((item) => item.path === '_internal/build-info.json')
  entry.size = bytes.length
  entry.sha256 = createHash('sha256').update(bytes).digest('hex')
  await writeFile(manifestPath, JSON.stringify(manifest))
  await assert.rejects(verifyBundle(source), /identifiers differ/)
})

test('preserves the previous staged bundle when a replacement source is corrupt', async (t) => {
  const source = await fixture(t)
  const parent = await mkdtemp(path.join(os.tmpdir(), 'apex-preserve-'))
  t.after(() => rm(parent, { recursive: true, force: true }))
  const resources = path.join(parent, 'resources')
  const destination = path.join(resources, 'backend-bundle')
  await mkdir(resources)
  await stageBundle(source, destination, resources)
  await writeFile(path.join(source, 'apex-backend.exe'), 'corrupt replacement')

  await assert.rejects(stageBundle(source, destination, resources), /failed integrity validation/)
  assert.equal(await readFile(path.join(destination, 'apex-backend.exe'), 'utf8'), 'backend')
  assert.equal(await verifyBundle(destination), 'test-build')
})

test('reuses a canonically identical source and destination on Windows', { skip: process.platform !== 'win32' }, async (t) => {
  const parent = await mkdtemp(path.join(os.tmpdir(), 'apex-repeat-'))
  t.after(() => rm(parent, { recursive: true, force: true }))
  const resources = path.join(parent, 'resources')
  const source = path.join(resources, 'Backend-Bundle')
  await mkdir(resources)
  await fixtureAt(t, source)

  assert.equal(await stageBundle(source, path.join(resources, 'backend-bundle'), resources), 'test-build')
  assert.equal(await readFile(path.join(source, 'apex-backend.exe'), 'utf8'), 'backend')
  assert.equal(await verifyBundle(source), 'test-build')
})

test('rejects source and destination ancestor overlap in either direction before changing either tree', async (t) => {
  const parent = await mkdtemp(path.join(os.tmpdir(), 'apex-overlap-'))
  t.after(() => rm(parent, { recursive: true, force: true }))
  const source = path.join(parent, 'bundle')
  await fixtureAt(t, source)
  const nestedTarget = path.join(source, 'nested')

  await assert.rejects(stageBundle(source, nestedTarget, source), /must not contain one another/)
  assert.equal(await readFile(path.join(source, 'apex-backend.exe'), 'utf8'), 'backend')
  assert.equal(await verifyBundle(source), 'test-build')

  const reverseRoot = path.join(parent, 'reverse-resources')
  const reverseDestination = path.join(reverseRoot, 'backend-bundle')
  const nestedSource = path.join(reverseDestination, 'source')
  await fixtureAt(t, nestedSource)
  await assert.rejects(stageBundle(nestedSource, reverseDestination, reverseRoot), /must not contain one another/)
  assert.equal(await readFile(path.join(nestedSource, 'apex-backend.exe'), 'utf8'), 'backend')
  assert.equal(await verifyBundle(nestedSource), 'test-build')
})

test('rejects non-canonical manifest paths before reading bundle files', async (t) => {
  const source = await fixture(t)
  const manifestPath = path.join(source, 'bundle-manifest.json')
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  const invalidPaths = ['../outside', 'licenses\\source-material\\example.txt', 'licenses//empty.txt', 'licenses/./file.txt', 'C:secret', 'licenses/\0name']
  for (const invalidPath of invalidPaths) {
    const mutated = structuredClone(manifest)
    mutated.files[0].path = invalidPath
    await writeFile(manifestPath, JSON.stringify(mutated))
    await assert.rejects(verifyBundle(source), /invalid file entry/)
  }
})

test('assembles the executable beside the complete staged bundle', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-assemble-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const source = path.join(root, 'source')
  await fixtureAt(t, source)
  const resources = path.join(root, 'resources')
  await mkdir(resources)
  const staged = path.join(resources, 'backend-bundle')
  await stageBundle(source, staged, resources)
  const executable = path.join(root, 'apex-desktop.exe')
  await writeFile(executable, 'desktop executable')
  const output = path.join(root, 'build', 'desktop-shell', 'APEX')

  assert.equal(await assembleDesktopOutput({ repositoryRoot: root, outputDirectory: output, executable, stagedBundle: staged }), output)
  assert.equal(await readFile(path.join(output, 'APEX.exe'), 'utf8'), 'desktop executable')
  assert.equal(await readFile(path.join(output, 'backend-bundle', 'licenses/source-material/example.txt'), 'utf8'), 'source')
  assert.equal(await verifyBundle(path.join(output, 'backend-bundle')), 'test-build')
})

test('refuses an output directory outside the repository before deleting it', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-output-guard-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const source = path.join(root, 'source')
  await fixtureAt(t, source)
  const resources = path.join(root, 'resources')
  await mkdir(resources)
  const staged = path.join(resources, 'backend-bundle')
  await stageBundle(source, staged, resources)
  const executable = path.join(root, 'apex-desktop.exe')
  await writeFile(executable, 'desktop executable')
  const outside = path.join(os.tmpdir(), `apex-output-outside-${path.basename(root)}`)
  await mkdir(outside, { recursive: true })
  await writeFile(path.join(outside, 'keep.txt'), 'preserve')

  await assert.rejects(assembleDesktopOutput({ repositoryRoot: root, outputDirectory: outside, executable, stagedBundle: staged }), /outside the repository build directory/)
  assert.equal(await readFile(path.join(outside, 'keep.txt'), 'utf8'), 'preserve')
})

test('refuses to replace a path elsewhere inside the repository', async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'apex-output-location-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const source = path.join(root, 'source')
  await fixtureAt(t, source)
  const resources = path.join(root, 'resources')
  await mkdir(resources)
  const staged = path.join(resources, 'backend-bundle')
  await stageBundle(source, staged, resources)
  const executable = path.join(root, 'apex-desktop.exe')
  await writeFile(executable, 'desktop executable')
  const wrongOutput = path.join(root, 'build', 'desktop-shell', 'other')
  await mkdir(wrongOutput, { recursive: true })
  await writeFile(path.join(wrongOutput, 'keep.txt'), 'preserve')

  await assert.rejects(assembleDesktopOutput({ repositoryRoot: root, outputDirectory: wrongOutput, executable, stagedBundle: staged }), /other than build\/desktop-shell\/APEX/)
  assert.equal(await readFile(path.join(wrongOutput, 'keep.txt'), 'utf8'), 'preserve')
})

async function fixtureAt(t, root) {
  t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(path.dirname(root), { recursive: true })
  await mkdir(path.join(root, '_internal', 'licenses'), { recursive: true })
  await mkdir(path.join(root, 'licenses', 'source-material'), { recursive: true })
  const files = {
    'apex-backend.exe': Buffer.from('backend'),
    'apex.exe': Buffer.from('cli'),
    LICENSE: Buffer.from('license'),
    'THIRD_PARTY_NOTICES.md': Buffer.from('notices'),
    '_internal/build-info.json': Buffer.from(JSON.stringify({ build_id: 'test-build' })),
    '_internal/licenses/example.txt': Buffer.from('internal license'),
    'licenses/source-material/example.txt': Buffer.from('source'),
  }
  for (const [name, bytes] of Object.entries(files)) {
    const target = path.join(root, name)
    await mkdir(path.dirname(target), { recursive: true })
    await writeFile(target, bytes)
  }
  const records = Object.entries(files).map(([name, bytes]) => ({
    path: name,
    size: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
  }))
  await writeFile(path.join(root, 'bundle-manifest.json'), JSON.stringify({ schema_version: 1, build_id: 'test-build', files: records }))
}
