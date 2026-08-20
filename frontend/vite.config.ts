import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
