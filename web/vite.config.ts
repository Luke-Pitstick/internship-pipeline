import { defineConfig } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';

export default defineConfig({
  build: { license: { fileName: 'third-party-licenses.md' } },
  plugins: [sveltekit({ adapter: adapter({ precompress: true }) })]
});
