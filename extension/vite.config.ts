import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { crx } from '@crxjs/vite-plugin';
import path from 'path';
import manifest from './public/manifest.json';

export default defineConfig({
  plugins: [
    react(),
    crx({ manifest }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: {
        offscreen: path.resolve(__dirname, 'offscreen.html'),
        'mic-grant': path.resolve(__dirname, 'mic-grant.html'),
        'speech-relay': path.resolve(__dirname, 'speech-relay.html'),
      },
    },
  },
});
