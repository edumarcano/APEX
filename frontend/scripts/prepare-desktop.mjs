import { createHash, randomUUID } from 'node:crypto'
import { cp, lstat, mkdir, readFile, readdir, realpath, rename, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(frontendRoot, '..')
const source = path.join(repoRoot, 'dist', 'backend-bundle')
const destination = path.join(frontendRoot, 'src-tauri', 'resources', 'backend-bundle')
const allowedDestinationRoot = path.join(frontendRoot, 'src-tauri', 'resources')

function fail(message) {
  throw new Error(`Desktop backend bundle ${message}`)
}

function comparePath(value) {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLocaleLowerCase('en-US') : resolved
}

function isSamePath(left, right) {
  return comparePath(left) === comparePath(right)
}

function isWithin(parent, child) {
  const relative = path.relative(comparePath(parent), comparePath(child))
  return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
}

function pathsOverlap(left, right) {
  return isSamePath(left, right) || isWithin(left, right) || isWithin(right, left)
}

async function canonicalProspectivePath(target) {
  const resolved = path.resolve(target)
  const parent = await realpath(path.dirname(resolved))
  return path.join(parent, path.basename(resolved))
}

async function walkFiles(root, relative = '') {
  const files = []
  for (const entry of await readdir(path.join(root, relative), { withFileTypes: true })) {
    const child = path.join(relative, entry.name)
    const info = await lstat(path.join(root, child))
    if (info.isSymbolicLink()) fail(`contains a symbolic link: ${child}`)
    if (entry.isDirectory()) files.push(...await walkFiles(root, child))
    else if (entry.isFile()) files.push(child.split(path.sep).join('/'))
    else fail(`contains a non-file entry: ${child}`)
  }
  return files
}

function isCanonicalBundlePath(value) {
  if (typeof value !== 'string' || !value || /[\\:\0-\x1f\x7f]/.test(value) || value.startsWith('/')) return false
  const segments = value.split('/')
  return segments.every((segment) => segment !== '' && segment !== '.' && segment !== '..') &&
    path.posix.normalize(value) === value && !path.posix.isAbsolute(value)
}

export async function verifyBundle(root) {
  const rootInfo = await lstat(root).catch(() => null)
  if (!rootInfo?.isDirectory() || rootInfo.isSymbolicLink()) fail('root must be a real directory.')

  const manifestPath = path.join(root, 'bundle-manifest.json')
  let manifest
  try {
    manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  } catch {
    fail('manifest is missing or invalid.')
  }
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest) || manifest.schema_version !== 1 ||
    typeof manifest.build_id !== 'string' || !manifest.build_id || !Array.isArray(manifest.files)) {
    fail('manifest is invalid.')
  }

  const actual = await walkFiles(root)
  const manifestIndex = actual.indexOf('bundle-manifest.json')
  if (manifestIndex < 0) fail('manifest is missing from the bundle.')
  actual.splice(manifestIndex, 1)

  const expected = new Set()
  for (const record of manifest.files) {
    if (!record || !isCanonicalBundlePath(record.path) || expected.has(record.path) ||
      !Number.isSafeInteger(record.size) || record.size < 0 ||
      typeof record.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(record.sha256)) {
      fail('manifest contains an invalid file entry.')
    }
    expected.add(record.path)
    const bytes = await readFile(path.join(root, ...record.path.split('/')))
    const digest = createHash('sha256').update(bytes).digest('hex')
    if (bytes.length !== record.size || digest !== record.sha256) fail(`file failed integrity validation: ${record.path}`)
  }
  if (actual.length !== expected.size || actual.some((file) => !expected.has(file))) fail('contains files absent from its manifest.')

  const buildInfoPath = path.join(root, '_internal', 'build-info.json')
  let buildInfo
  try {
    buildInfo = JSON.parse(await readFile(buildInfoPath, 'utf8'))
  } catch {
    fail('build identity is missing or invalid.')
  }
  if (!buildInfo || typeof buildInfo !== 'object' || Array.isArray(buildInfo) || typeof buildInfo.build_id !== 'string') {
    fail('build identity is missing or invalid.')
  }
  if (buildInfo.build_id !== manifest.build_id) fail('manifest and build-info identifiers differ.')

  const requiredFiles = ['apex-backend.exe', 'apex.exe', 'LICENSE', 'THIRD_PARTY_NOTICES.md', '_internal/build-info.json']
  if (requiredFiles.some((file) => !expected.has(file)) || ![...expected].some((file) => file.startsWith('licenses/'))) {
    fail('is missing the backend, CLI, build identity, or license material.')
  }
  return manifest.build_id
}

async function assertStagePaths(sourceRoot, targetRoot, allowedRoot) {
  const sourceInfo = await lstat(sourceRoot).catch(() => null)
  if (!sourceInfo?.isDirectory() || sourceInfo.isSymbolicLink()) fail('source must be a real directory.')
  const sourceCanonical = await realpath(sourceRoot)
  const allowedCanonical = await realpath(allowedRoot)
  const targetInfo = await lstat(targetRoot).catch(() => null)
  if (targetInfo?.isSymbolicLink()) fail('staging destination must not be a symbolic link.')
  const targetCanonical = targetInfo ? await realpath(targetRoot) : await canonicalProspectivePath(targetRoot)
  if (!isWithin(allowedCanonical, targetCanonical)) fail('staging destination must stay inside src-tauri/resources.')
  if (pathsOverlap(sourceCanonical, targetCanonical) && !isSamePath(sourceCanonical, targetCanonical)) {
    fail('source and staging destination must not contain one another.')
  }
  return { sourceCanonical, targetCanonical, allowedCanonical }
}

export async function stageBundle(from = source, to = destination, allowedRoot = allowedDestinationRoot) {
  if (!(await lstat(from).catch(() => null))?.isDirectory()) fail(`was not found at ${path.relative(repoRoot, from)}; build it first.`)
  const paths = await assertStagePaths(from, to, allowedRoot)
  const buildId = await verifyBundle(paths.sourceCanonical)
  if (isSamePath(paths.sourceCanonical, paths.targetCanonical)) return buildId

  await mkdir(paths.allowedCanonical, { recursive: true })
  const parent = await realpath(path.dirname(paths.targetCanonical))
  const temporary = path.join(parent, `.backend-bundle-stage-${randomUUID()}`)
  const backup = path.join(parent, `.backend-bundle-backup-${randomUUID()}`)
  let hasBackup = false
  let preserveBackup = false
  try {
    await cp(paths.sourceCanonical, temporary, { recursive: true, dereference: false, errorOnExist: true })
    const stagedBuildId = await verifyBundle(temporary)
    if (stagedBuildId !== buildId) fail('changed while staging.')

    const existing = await lstat(paths.targetCanonical).catch(() => null)
    if (existing?.isSymbolicLink()) fail('staging destination must not be a symbolic link.')
    if (existing) {
      await rename(paths.targetCanonical, backup)
      hasBackup = true
    }
    try {
      await rename(temporary, paths.targetCanonical)
    } catch (error) {
      if (hasBackup) {
        try {
          await rename(backup, paths.targetCanonical)
          hasBackup = false
        } catch {
          preserveBackup = true
          fail(`could not restore the previous staged bundle; it remains at ${backup}.`)
        }
      }
      throw error
    }
    if (hasBackup) {
      await rm(backup, { recursive: true, force: true })
      hasBackup = false
    }
    return buildId
  } finally {
    await rm(temporary, { recursive: true, force: true })
    if (hasBackup && !preserveBackup) await rm(backup, { recursive: true, force: true })
  }
}

async function main() {
  const bundleIndex = process.argv.indexOf('--bundle')
  const configuredSource = bundleIndex >= 0 ? process.argv[bundleIndex + 1] : process.env.APEX_DESKTOP_BUILD_BUNDLE
  if (bundleIndex >= 0 && (!configuredSource || configuredSource.startsWith('--') || !path.isAbsolute(configuredSource))) {
    fail('requires an absolute directory after --bundle.')
  }
  const primaryExists = await lstat(source).catch(() => null)
  const selectedSource = configuredSource ? path.resolve(configuredSource) : primaryExists?.isDirectory() ? source : destination
  const buildId = await stageBundle(selectedSource, destination)
  process.stdout.write(`Verified and staged backend bundle ${buildId}\n`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`)
    process.exitCode = 1
  })
}
