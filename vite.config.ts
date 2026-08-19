import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// StormPulse is deployable to GitHub Pages under /StormPulse/.
// Use a relative base so the built assets resolve from any sub-path.
export default defineConfig({
  base: './',
  plugins: [react()],
})
