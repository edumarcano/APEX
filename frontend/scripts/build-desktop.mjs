import { cp, lstat, mkdir, readFile, readdir, realpath, rename, rm, stat, writeFile } from 'node:fs/promises'
import { createHash, randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { verifyBundle } from './prepare-desktop.mjs'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(frontendRoot, '..')
const outputRoot = path.join(repoRoot, 'build', 'desktop-shell')
const output = path.join(outputRoot, 'APEX')
const prepareScript = path.join(frontendRoot, 'scripts', 'prepare-desktop.mjs')
const tauriCli = path.join(frontendRoot, 'node_modules', '@tauri-apps', 'cli', 'tauri.js')

function comparePath(value) {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLocaleLowerCase('en-US') : resolved
}

function isWithin(parent, child) {
  const relative = path.relative(comparePath(parent), comparePath(child))
  return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
}

async function canonicalProspectivePath(target) {
  const resolved = path.resolve(target)
  const missing = []
  let existing = resolved
  while (!(await lstat(existing).catch(() => null))) {
    missing.unshift(path.basename(existing))
    const parent = path.dirname(existing)
    if (parent === existing) throw new Error(`Could not resolve the intended output path ${target}.`)
    existing = parent
  }
  const canonicalExisting = await realpath(existing)
  return path.join(canonicalExisting, ...missing)
}

function runNode(args, cwd, extraEnv = {}) {
  const result = spawnSync(process.execPath, args, {
    cwd,
    stdio: 'inherit',
    shell: false,
    env: { ...process.env, ...extraEnv },
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${path.basename(args[0] ?? 'node')} exited with ${result.status ?? 'a signal'}.`)
}

function readGit(args, cwd) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
    windowsHide: true,
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`git ${args.join(' ')} failed: ${result.stderr.trim()}`)
  return result.stdout.trim()
}

export async function verifyPackageSourceIdentity(repositoryRoot, bundle) {
  const commit = readGit(['rev-parse', 'HEAD'], repositoryRoot)
  const status = readGit(['status', '--porcelain', '--untracked-files=all'], repositoryRoot)
  if (status) throw new Error('NSIS packaging requires a clean committed worktree.')

  let backendInfo
  try {
    backendInfo = JSON.parse(await readFile(path.join(bundle, '_internal', 'build-info.json'), 'utf8'))
  } catch {
    throw new Error('NSIS packaging requires valid backend build identity metadata.')
  }
  if (!backendInfo || typeof backendInfo !== 'object' || Array.isArray(backendInfo) ||
    typeof backendInfo.commit !== 'string' || !backendInfo.commit) {
    throw new Error('NSIS packaging requires a backend source commit.')
  }
  if (backendInfo.commit !== commit) {
    throw new Error(`Backend bundle commit ${backendInfo.commit} does not match current desktop source commit ${commit}; rebuild the backend bundle.`)
  }
  return commit
}

export async function assembleDesktopOutput({
  repositoryRoot = repoRoot,
  outputDirectory = output,
  executable,
  stagedBundle,
  expectedVersion,
} = {}) {
  if (!executable || !stagedBundle) throw new Error('A desktop executable and staged backend bundle are required.')
  if (!(await stat(executable).catch(() => null))?.isFile()) throw new Error('Tauri did not produce the target-specific apex-desktop.exe.')
  await verifyBundle(stagedBundle, { expectedVersion })

  const repository = await realpath(repositoryRoot)
  const outputRoot = path.join(repository, 'build', 'desktop-shell')
  const intendedOutputRoot = await canonicalProspectivePath(outputRoot)
  if (!isWithin(repository, intendedOutputRoot)) throw new Error('Refusing to write outside the repository build directory.')
  await mkdir(outputRoot, { recursive: true })

  const outputRootCanonical = await realpath(outputRoot)
  if (!isWithin(repository, outputRootCanonical)) throw new Error('Refusing to write outside the repository build directory.')
  const outputCanonical = await canonicalProspectivePath(outputDirectory)
  if (!isWithin(outputRootCanonical, outputCanonical)) throw new Error('Refusing to write outside the repository build directory.')
  if (comparePath(outputCanonical) !== comparePath(path.join(outputRootCanonical, 'APEX'))) {
    throw new Error('Refusing to replace a path other than build/desktop-shell/APEX.')
  }
  const targetInfo = await lstat(path.resolve(outputDirectory)).catch(() => null)
  if (targetInfo?.isSymbolicLink()) throw new Error('Refusing to replace a symbolic-link desktop output.')

  await rm(path.resolve(outputDirectory), { recursive: true, force: true })
  await mkdir(path.resolve(outputDirectory), { recursive: true })
  await cp(executable, path.join(path.resolve(outputDirectory), 'APEX.exe'))
  await cp(stagedBundle, path.join(path.resolve(outputDirectory), 'backend-bundle'), { recursive: true })
  const stagedOutputBundle = path.join(path.resolve(outputDirectory), 'backend-bundle')
  await verifyBundle(stagedOutputBundle, { expectedVersion })
  return path.resolve(outputDirectory)
}

async function inspectExistingInstallerOutput(outputDirectory) {
  const info = await lstat(outputDirectory).catch(() => null)
  if (!info) return false
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('Refusing to replace a non-directory or symbolic-link installer output.')
  const entries = await readdir(outputDirectory, { withFileTypes: true })
  const manifestPath = path.join(outputDirectory, 'distribution-manifest.json')
  const manifestInfo = await lstat(manifestPath).catch(() => null)
  if (!manifestInfo?.isFile() || manifestInfo.isSymbolicLink()) throw new Error('Existing installer output has no regular distribution manifest.')
  let previous
  try {
    previous = JSON.parse(await readFile(manifestPath, 'utf8'))
  } catch {
    throw new Error('Existing installer distribution manifest is invalid.')
  }
  if (!previous || previous.schema_version !== 1 || typeof previous.installer !== 'string' ||
    previous.product !== 'APEX' || previous.target !== 'x86_64-pc-windows-msvc' ||
    typeof previous.version !== 'string' || typeof previous.source_commit !== 'string' ||
    typeof previous.backend_build_id !== 'string' || !/^APEX_.+_x64-setup\.exe$/i.test(previous.installer) ||
    !/^[0-9a-f]{64}$/.test(previous.installer_sha256)) {
    throw new Error('Existing installer distribution manifest is invalid.')
  }
  const expected = new Set(['distribution-manifest.json', previous.installer, `${previous.installer}.sha256`])
  if (entries.length !== expected.size || entries.some((entry) => !expected.has(entry.name))) {
    throw new Error('Existing installer output contains files not owned by its distribution manifest.')
  }
  for (const name of expected) {
    const entryInfo = await lstat(path.join(outputDirectory, name))
    if (!entryInfo.isFile() || entryInfo.isSymbolicLink()) throw new Error('Existing installer output contains a non-file or symbolic link.')
  }
  const bytes = await readFile(path.join(outputDirectory, previous.installer))
  if (createHash('sha256').update(bytes).digest('hex') !== previous.installer_sha256) {
    throw new Error('Existing installer output failed its recorded SHA-256 check.')
  }
  if (await readFile(path.join(outputDirectory, `${previous.installer}.sha256`), 'utf8') !==
    `${previous.installer_sha256}  ${previous.installer}\n`) {
    throw new Error('Existing installer checksum file differs from its distribution manifest.')
  }
  return true
}

export async function exportInstallerOutput({ repositoryRoot = repoRoot, sourceInstaller, version, sourceCommit, backendBuildId } = {}) {
  if (!sourceInstaller || !version || !sourceCommit || !backendBuildId) throw new Error('Installer source, version, source commit, and backend build identity are required.')
  const sourceInfo = await lstat(sourceInstaller).catch(() => null)
  if (!sourceInfo?.isFile() || sourceInfo.isSymbolicLink()) throw new Error('NSIS installer source must be a regular file.')
  const installerName = path.basename(sourceInstaller)
  if (!/^APEX_.+_x64-setup\.exe$/i.test(installerName)) throw new Error('Tauri produced an unexpected x64 APEX NSIS installer filename.')

  const repository = await realpath(repositoryRoot)
  const buildRoot = path.join(repository, 'build', 'desktop-shell')
  const canonicalBuildRoot = await canonicalProspectivePath(buildRoot)
  if (!isWithin(repository, canonicalBuildRoot)) throw new Error('Refusing to write outside the repository build directory.')
  await mkdir(buildRoot, { recursive: true })
  const buildRootCanonical = await realpath(buildRoot)
  if (!isWithin(repository, buildRootCanonical)) throw new Error('Refusing to write outside the repository build directory.')

  const installerDirectory = path.join(buildRootCanonical, 'installers')
  const intendedOutput = await canonicalProspectivePath(installerDirectory)
  if (!isWithin(buildRootCanonical, intendedOutput)) throw new Error('Refusing to write outside build/desktop-shell/installers.')
  const existingInfo = await lstat(installerDirectory).catch(() => null)
  if (existingInfo?.isSymbolicLink()) throw new Error('Refusing to write through a symbolic-link installer output.')
  const hasPrevious = await inspectExistingInstallerOutput(installerDirectory)

  const installerBytes = await readFile(sourceInstaller)
  const digest = createHash('sha256').update(installerBytes).digest('hex')
  const receipt = {
    schema_version: 1,
    product: 'APEX',
    version,
    target: 'x86_64-pc-windows-msvc',
    installer: installerName,
    installer_sha256: digest,
    source_commit: sourceCommit,
    backend_build_id: backendBuildId,
  }
  const staging = path.join(buildRootCanonical, `.installers-stage-${randomUUID()}`)
  const backup = path.join(buildRootCanonical, `.installers-backup-${randomUUID()}`)
  let hasBackup = false
  let preserveBackup = false
  try {
    await mkdir(staging)
    await writeFile(path.join(staging, installerName), installerBytes)
    await writeFile(path.join(staging, `${installerName}.sha256`), `${digest}  ${installerName}\n`, 'utf8')
    await writeFile(path.join(staging, 'distribution-manifest.json'), `${JSON.stringify(receipt, null, 2)}\n`, 'utf8')
    if (hasPrevious) {
      await rename(installerDirectory, backup)
      hasBackup = true
    }
    try {
      await rename(staging, installerDirectory)
    } catch (error) {
      if (hasBackup) {
        try {
          await rename(backup, installerDirectory)
          hasBackup = false
        } catch {
          preserveBackup = true
          throw new Error(`Could not restore the previous installer output; it remains at ${backup}.`)
        }
      }
      throw error
    }
    if (hasBackup) {
      await rm(backup, { recursive: true, force: true })
      hasBackup = false
    }
    return path.join(installerDirectory, installerName)
  } finally {
    await rm(staging, { recursive: true, force: true })
    if (hasBackup && !preserveBackup) await rm(backup, { recursive: true, force: true })
  }
}

async function main() {
  const packageInstaller = process.argv.includes('--package')
  const bundleIndex = process.argv.indexOf('--bundle')
  const bundleArgument = bundleIndex >= 0 ? process.argv[bundleIndex + 1] : undefined
  if (bundleIndex >= 0 && (!bundleArgument || bundleArgument.startsWith('--') || !path.isAbsolute(bundleArgument))) {
    throw new Error('Pass an absolute bundle directory after --bundle.')
  }
  const distBundle = path.join(repoRoot, 'dist', 'backend-bundle')
  const stagedBundle = path.join(frontendRoot, 'src-tauri', 'resources', 'backend-bundle')
  const defaultBundle = (await stat(distBundle).catch(() => null))?.isDirectory() ? distBundle : stagedBundle
  const bundle = path.resolve(bundleArgument ?? defaultBundle)
  const config = JSON.parse(await readFile(path.join(frontendRoot, 'src-tauri', 'tauri.conf.json'), 'utf8'))
  await verifyBundle(bundle, { expectedVersion: config.version })
  const packageSourceCommit = packageInstaller ? await verifyPackageSourceIdentity(repoRoot, bundle) : undefined

  // Tauri runs beforeBuildCommand in this process environment. Keep that hook
  // on the same verified source, even if Vite removes dist during the build.
  runNode([prepareScript, '--bundle', bundle], repoRoot)
  const tauriArgs = [tauriCli, 'build', '--target', 'x86_64-pc-windows-msvc']
  if (packageInstaller) tauriArgs.push('--bundles', 'nsis')
  else tauriArgs.push('--no-bundle')
  tauriArgs.push('--', '--locked')
  runNode(tauriArgs, frontendRoot, { APEX_DESKTOP_BUILD_BUNDLE: bundle })

  const targetRoot = path.join(frontendRoot, 'src-tauri', 'target', 'x86_64-pc-windows-msvc', 'release')
  const executable = path.join(targetRoot, 'apex-desktop.exe')
  await verifyBundle(stagedBundle, { expectedVersion: config.version })
  const assembled = await assembleDesktopOutput({ executable, stagedBundle, expectedVersion: config.version })
  process.stdout.write(`Desktop shell assembled at ${path.relative(repoRoot, assembled)}\n`)

  if (packageInstaller) {
    const finalSourceCommit = await verifyPackageSourceIdentity(repoRoot, stagedBundle)
    if (finalSourceCommit !== packageSourceCommit) throw new Error('Desktop source commit changed during NSIS packaging.')
    const nsisDirectory = path.join(targetRoot, 'bundle', 'nsis')
    const installers = (await readdir(nsisDirectory, { withFileTypes: true }))
      .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith('-setup.exe') && entry.name.includes(`_${config.version}_`))
    if (installers.length !== 1) throw new Error(`Expected one NSIS installer in ${nsisDirectory}, found ${installers.length}.`)
    const sourceInstaller = path.join(nsisDirectory, installers[0].name)
    const backendInfo = JSON.parse(await readFile(path.join(assembled, 'backend-bundle', '_internal', 'build-info.json'), 'utf8'))
    const installerPath = await exportInstallerOutput({
      sourceInstaller,
      version: config.version,
      sourceCommit: finalSourceCommit,
      backendBuildId: backendInfo.build_id,
    })
    process.stdout.write(`NSIS installer packaged at ${path.relative(repoRoot, installerPath)}\n`)
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`)
    process.exitCode = 1
  })
}
