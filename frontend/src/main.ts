import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router'
import { t } from './i18n'

import { Capacitor } from '@capacitor/core'

const defaultNativeBase = 'http://localhost:8000'
const nativeApiBase = import.meta.env.VITE_API_BASE_URL
  ? (import.meta.env.VITE_API_BASE_URL as string).replace(/\/+$/, '')
  : defaultNativeBase

import { App as CapApp } from '@capacitor/app'
import { Browser } from '@capacitor/browser'
import { setAuthSession } from './services/apiClient'
import { fetchUserProfile } from './composables/useUserProfile'

// Route relative /api requests to local backend server when running as a native app
if (Capacitor.isNativePlatform()) {
  const originalFetch = window.fetch
  window.fetch = function (input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string') {
      if (input.startsWith('/api/')) {
        input = `${nativeApiBase}${input}`
      }
    } else if (input instanceof URL) {
      if (input.pathname.startsWith('/api/')) {
        input = new URL(input.pathname + input.search, nativeApiBase)
      }
    } else if (typeof Request !== 'undefined' && input instanceof Request) {
      try {
        const parsed = new URL(input.url)
        if (parsed.pathname.startsWith('/api/') && (parsed.origin === window.location.origin || parsed.hostname === 'localhost')) {
          const rewritten = `${nativeApiBase}${parsed.pathname}${parsed.search}`
          input = new Request(rewritten, input)
        }
      } catch {}
    }
    return originalFetch.call(this, input, init)
  }

  // Handle native deep link callbacks (e.g. from Google OAuth)
  CapApp.addListener('appUrlOpen', async (event) => {
    const rawUrl = event.url || ''
    if (rawUrl.includes('auth/callback') || rawUrl.startsWith('com.notesight://')) {
      try {
        await Browser.close().catch(() => {})
      } catch {}

      const hashIndex = rawUrl.indexOf('#')
      const queryIndex = rawUrl.indexOf('?')
      const rawParams = hashIndex !== -1 ? rawUrl.substring(hashIndex + 1) : (queryIndex !== -1 ? rawUrl.substring(queryIndex + 1) : '')
      const params = new URLSearchParams(rawParams)

      const accessToken = params.get('access_token')
      const refreshToken = params.get('refresh_token')
      const email = params.get('email')

      if (accessToken) {
        setAuthSession(accessToken, refreshToken, email)
        await fetchUserProfile().catch(() => {})
        router.push({ name: 'Dashboard' })
      }
    }
  })
}

const app = createApp(App)
app.config.globalProperties.$t = t
app.use(router)

router.isReady().then(() => {
  app.mount('#app')
})


