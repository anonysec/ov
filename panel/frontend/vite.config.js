import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import dotenv from 'dotenv'
import path from 'path'

// Load .env from the project root
dotenv.config({ path: path.resolve(__dirname, '../.env') })

const rawPath = (process.env.URLPATH || '').trim();
const urlPath = rawPath || '';
const base = urlPath ? `/${urlPath}/` : '/';

export default defineConfig({
  plugins: [react()],
  base,
  build: {
    outDir: 'dist',
  },
})