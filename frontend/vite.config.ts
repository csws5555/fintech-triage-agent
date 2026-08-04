import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { configDefaults, defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    exclude: [...configDefaults.exclude, 'tests/e2e/**'],
    setupFiles: './src/test/setup.ts',
  },
})
