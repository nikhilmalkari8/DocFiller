import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: 'jsdom',
    // tests/ is the separate node:test-based design-token harness (npm run
    // test:tokens) — keep Vitest scoped to src/ so the two runners don't collide.
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
