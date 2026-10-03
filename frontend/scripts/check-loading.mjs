import { gzipSync } from 'node:zlib'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const defaultDist = path.resolve(frontendRoot, '../dist')
const distArg = process.argv.indexOf('--dist')
const dist = distArg < 0 ? defaultDist : process.argv[distArg + 1]
if (distArg >= 0 && (!dist || !path.isAbsolute(dist))) fail('--dist requires an absolute dist directory path')
const baselineArg = process.argv.indexOf('--baseline')
const baselineDist = baselineArg < 0 ? null : process.argv[baselineArg + 1]

if (baselineArg >= 0 && (!baselineDist || !path.isAbsolute(baselineDist))) {
  fail('--baseline requires an absolute dist directory path')
}

const current = await inspectDist(dist, { requireReport: true })
printMetrics('Current build', current.metrics)

if (baselineDist) {
  const baseline = await inspectDist(baselineDist, { requireReport: false })
  printMetrics('Baseline build', baseline.metrics)
  printDelta(current.metrics, baseline.metrics)
}

assertLoadingBoundaries(current)

function fail(message) {
  console.error(`Loading graph check failed: ${message}`)
  process.exit(1)
}

async function inspectDist(distRoot, { requireReport }) {
  const htmlPath = path.join(distRoot, 'index.html')
  let html
  try {
    html = await readFile(htmlPath, 'utf8')
  } catch {
    fail(`missing build HTML at ${htmlPath}`)
  }

  const entryFiles = [...new Set(attributesFor(html, 'script', 'type', 'module', 'src').map(normalizeHtmlFile))]
  const preloadFiles = [...new Set(attributesFor(html, 'link', 'rel', 'modulepreload', 'href').map(normalizeHtmlFile))]
  if (entryFiles.length === 0) fail('index.html has no module entry script')

  const reportPath = path.join(distRoot, '.vite', 'loading-report.json')
  let report
  try {
    report = JSON.parse(await readFile(reportPath, 'utf8'))
  } catch {
    if (requireReport) fail(`missing or invalid production graph report at ${reportPath}`)
  }

  const buildManifestPath = path.join(distRoot, '.vite', 'manifest.json')
  let buildManifest
  try {
    buildManifest = JSON.parse(await readFile(buildManifestPath, 'utf8'))
  } catch {
    if (requireReport || !report) fail(`missing or invalid Vite build manifest at ${buildManifestPath}`)
  }

  const chunks = new Map()
  if (report) {
    for (const chunk of report.chunks ?? []) chunks.set(chunk.fileName, chunk)
  } else {
    const manifestFile = new Map(Object.entries(buildManifest)
      .filter(([, item]) => item.file?.endsWith('.js'))
      .map(([key, item]) => [item.file, { ...item, key }]))
    for (const [file, item] of manifestFile) {
      if (item.file?.endsWith('.js')) {
        const imports = (item.imports ?? []).map((key) => {
          const importedFile = buildManifest[key]?.file
          if (!importedFile) fail(`baseline manifest entry ${file} references missing import key ${key}`)
          return importedFile
        })
        chunks.set(file, { fileName: file, imports, dynamicImports: [], modules: [] })
      }
    }
  }

  // Vite's HTML preloads participate in startup even when source imports are lazy.
  const initialFiles = new Set([...entryFiles, ...preloadFiles])
  const queue = [...initialFiles]
  while (queue.length > 0) {
    const file = queue.pop()
    const chunk = chunks.get(file)
    if (!chunk) fail(`HTML references ${file}, which is absent from the production chunk report`)
    for (const imported of chunk.imports) {
      if (!initialFiles.has(imported)) {
        initialFiles.add(imported)
        queue.push(imported)
      }
    }
  }

  const allJsFiles = await listJsFiles(distRoot)
  const metrics = {
    entry: await measureFiles(distRoot, entryFiles),
    initial: await measureFiles(distRoot, [...initialFiles]),
    deferred: await measureFiles(distRoot, allJsFiles.filter((file) => !initialFiles.has(file))),
    total: await measureFiles(distRoot, allJsFiles),
  }
  return { report, chunks, initialFiles, metrics }
}

function normalizeHtmlFile(value) {
  return value.replace(/^\/+/, '').split(/[?#]/, 1)[0]
}

function attributesFor(html, tag, matchName, matchValue, valueName) {
  const tags = html.match(new RegExp(`<${tag}\\b[^>]*>`, 'gi')) ?? []
  return tags.flatMap((element) => {
    const attributes = Object.fromEntries(
      [...element.matchAll(/([\w-]+)\s*=\s*["']([^"']*)["']/g)].map((match) => [match[1].toLowerCase(), match[2]]),
    )
    if (attributes[matchName] !== matchValue) return []
    return attributes[valueName] ? [attributes[valueName].replaceAll('&amp;', '&')] : []
  })
}

async function listJsFiles(root, prefix = '') {
  const result = []
  for (const entry of await readdir(path.join(root, prefix), { withFileTypes: true })) {
    const relative = path.posix.join(prefix.replace(/\\/g, '/'), entry.name)
    if (entry.isDirectory()) result.push(...await listJsFiles(root, relative))
    else if (entry.isFile() && entry.name.endsWith('.js')) result.push(relative)
  }
  return result
}

async function measureFiles(root, files) {
  const unique = [...new Set(files)]
  const rootPath = path.resolve(root)
  const buffers = await Promise.all(unique.map(async (file) => {
    const absolute = path.resolve(root, file)
    if (!absolute.startsWith(`${rootPath}${path.sep}`)) fail(`invalid build file path ${file}`)
    try {
      return await readFile(absolute)
    } catch {
      fail(`missing referenced build file ${file}`)
    }
  }))
  const bytes = buffers.reduce((total, buffer) => total + buffer.byteLength, 0)
  const gzip = buffers.reduce((total, buffer) => total + gzipSync(buffer).byteLength, 0)
  return { bytes, gzip, files: unique.length }
}

function assertLoadingBoundaries(build) {
  if (!build.report) fail('production graph report is required for loading-boundary verification')
  const allModules = [...build.chunks.values()].flatMap((chunk) => chunk.modules)
  const initialModules = [...build.initialFiles].flatMap((file) => build.chunks.get(file)?.modules ?? [])
  const sourceBoundaries = [
    'src/components/SettingsPanel.tsx',
    'src/components/CortexWorkspace.tsx',
    'src/components/ActivityReportsWorkspace.tsx',
    'src/components/briefing/BriefingView.tsx',
    'src/components/briefing/BriefingSpeechControl.tsx',
  ]

  for (const target of sourceBoundaries) {
    if (!allModules.includes(target)) fail(`expected source module is absent from production build: ${target}`)
    if (initialModules.includes(target)) fail(`deferred source module is in the initial HTML/static import closure: ${target}`)
  }

  for (const target of ['react-markdown', 'remark-gfm']) {
    const predicate = (moduleId) => moduleId.startsWith(`node_modules/${target}/`)
    if (!allModules.some(predicate)) fail(`expected Markdown dependency is absent from production build: ${target}`)
    if (initialModules.some(predicate)) fail(`${target} is in the initial HTML/static import closure`)
  }

  for (const target of ['src/platform/DesktopAdmission.tsx', 'src/platform/tauri.ts']) {
    if (!allModules.includes(target)) fail(`expected desktop module is absent from production build: ${target}`)
    if (initialModules.includes(target)) fail(`desktop module is in the browser HTML/static import closure: ${target}`)
  }
  const tauriApiModule = (moduleId) => moduleId.startsWith('node_modules/@tauri-apps/api/')
  if (!allModules.some(tauriApiModule)) fail('expected Tauri API dependency is absent from production build')
  if (initialModules.some(tauriApiModule)) fail('Tauri API dependency is in the browser HTML/static import closure')
}

function printMetrics(label, metrics) {
  console.log(`${label}:`)
  for (const [name, measured] of Object.entries(metrics)) {
    console.log(`  ${name}: ${formatBytes(measured.bytes)} raw / ${formatBytes(measured.gzip)} gzip (${measured.files} JS files)`)
  }
}

function printDelta(currentMetrics, baselineMetrics) {
  console.log('Current minus baseline:')
  for (const name of Object.keys(currentMetrics)) {
    console.log(`  ${name}: ${formatDelta(currentMetrics[name].bytes - baselineMetrics[name].bytes)} raw / ${formatDelta(currentMetrics[name].gzip - baselineMetrics[name].gzip)} gzip`)
  }
}

function formatBytes(value) {
  return `${(value / 1024).toFixed(2)} KiB`
}

function formatDelta(value) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value / 1024).toFixed(2)} KiB`
}
