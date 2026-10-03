import { cp, lstat, mkdir, realpath, rm, stat } from 'node:fs/promises'
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

export async function assembleDesktopOutput({
  repositoryRoot = repoRoot,
  outputDirectory = output,
  executable,
  stagedBundle,
} = {}) {
  if (!executable || !stagedBundle) throw new Error('A desktop executable and staged backend bundle are required.')
  if (!(await stat(executable).catch(() => null))?.isFile()) throw new Error('Tauri did not produce src-tauri/target/release/apex-desktop.exe.')
  await verifyBundle(stagedBundle)

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
  await verifyBundle(stagedOutputBundle)
  return path.resolve(outputDirectory)
}

async function main() {
  const bundleIndex = process.argv.indexOf('--bundle')
  const bundleArgument = bundleIndex >= 0 ? process.argv[bundleIndex + 1] : undefined
  if (bundleIndex >= 0 && (!bundleArgument || bundleArgument.startsWith('--') || !path.isAbsolute(bundleArgument))) {
    throw new Error('Pass an absolute bundle directory after --bundle.')
  }
  const distBundle = path.join(repoRoot, 'dist', 'backend-bundle')
  const stagedBundle = path.join(frontendRoot, 'src-tauri', 'resources', 'backend-bundle')
  const defaultBundle = (await stat(distBundle).catch(() => null))?.isDirectory() ? distBundle : stagedBundle
  const bundle = path.resolve(bundleArgument ?? defaultBundle)
  await verifyBundle(bundle)

  // Tauri runs beforeBuildCommand in this process environment. Keep that hook
  // on the same verified source, even if Vite removes dist during the build.
  runNode([prepareScript, '--bundle', bundle], repoRoot)
  runNode([tauriCli, 'build', '--no-bundle'], frontendRoot, { APEX_DESKTOP_BUILD_BUNDLE: bundle })

  const executable = path.join(frontendRoot, 'src-tauri', 'target', 'release', 'apex-desktop.exe')
  await verifyBundle(stagedBundle)
  const assembled = await assembleDesktopOutput({ executable, stagedBundle })
  process.stdout.write(`Desktop shell assembled at ${path.relative(repoRoot, assembled)}\n`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`)
    process.exitCode = 1
  })
}
