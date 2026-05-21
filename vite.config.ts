import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())
  const moduleName = env.VITE_MODULE_NAME || 'mailer'
  const portalUrl = env.VITE_PORTAL_URL || 'http://localhost:5000'

  return {
    plugins: [vue()],
    base: `/remotes/${moduleName}/`,
    build: {
      target: 'esnext',
    },
    server: {
      port: 5080,
      proxy: {
        '/api': { target: portalUrl, changeOrigin: true, secure: false },
        '/companies': { target: portalUrl, changeOrigin: true, secure: false },
        '/employees': { target: portalUrl, changeOrigin: true, secure: false },
        '/auth': { target: portalUrl, changeOrigin: true, secure: false },
      },
    },
  }
})
