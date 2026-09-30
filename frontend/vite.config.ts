import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function loadingReport(): Plugin {
  return {
    name: 'apex-loading-report',
    generateBundle(_options, bundle) {
      const chunks = Object.values(bundle)
        .filter((output) => output.type === 'chunk')
        .map((chunk) => ({
          fileName: chunk.fileName,
          imports: chunk.imports,
          dynamicImports: chunk.dynamicImports,
          modules: [...new Set(Object.keys(chunk.modules).map(normalizeModuleId))].sort(),
        }))
        .sort((left, right) => left.fileName.localeCompare(right.fileName))

      this.emitFile({
        type: 'asset',
        fileName: '.vite/loading-report.json',
        source: JSON.stringify({ chunks }, null, 2),
      })
    },
  }
}

function normalizeModuleId(id: string) {
  const normalized = id.replace(/\\/g, '/').split('?')[0]
  const dependencyIndex = normalized.lastIndexOf('/node_modules/')
  if (dependencyIndex >= 0) {
    return normalized.slice(dependencyIndex + 1)
  }
  const sourceRoot = `${path.resolve(__dirname, 'src').replace(/\\/g, '/')}/`
  const sourceIndex = normalized.lastIndexOf(sourceRoot)
  if (sourceIndex >= 0) {
    return `src/${normalized.slice(sourceIndex + sourceRoot.length)}`
  }
  if (normalized.startsWith('\0') || normalized.startsWith('virtual:')) {
    return 'virtual'
  }
  if (/^[a-z]+:/i.test(normalized)) {
    return 'external'
  }
  return 'other'
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), loadingReport()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
  build: {
    outDir: path.resolve(__dirname, '../dist'),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return
          }
          const normalized = id.replace(/\\/g, '/')
          if (
            normalized.includes('/react/') ||
            normalized.includes('/react-dom/') ||
            normalized.includes('/scheduler/')
          ) {
            return 'vendor-react'
          }
          if (normalized.includes('/@assistant-ui/')) {
            return 'vendor-assistant'
          }
          if (
            normalized.includes('/@lobehub/') ||
            normalized.includes('/lucide-react/')
          ) {
            return 'vendor-icons'
          }
          if (
            normalized.includes('/react-markdown/') ||
            normalized.includes('/remark-gfm/') ||
            normalized.includes('/micromark') ||
            normalized.includes('/unist-') ||
            normalized.includes('/vfile')
          ) {
            return 'vendor-markdown'
          }
        },
      },
    },
  },
})
