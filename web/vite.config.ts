import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API base URL is provided at build/runtime via VITE_API_URL
// (defaults to http://localhost:8000 for local development).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    // Explicit, not just relying on Vite's default: never ship sourcemaps
    // in the production build (hardening ADR-0035) — this app talks to the
    // real backend (unlike the root demo app), so its source is a more
    // useful target to keep opaque to casual inspection.
    sourcemap: false,
  },
})
