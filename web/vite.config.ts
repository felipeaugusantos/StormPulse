import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API base URL is provided at build/runtime via VITE_API_URL
// (defaults to http://localhost:8000 for local development).
export default defineConfig({
  base: './',
  plugins: [react()],
})
