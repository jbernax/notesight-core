<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchUserProfile } from '../composables/useUserProfile'
import { resolveApiUrl } from '../services/apiClient'

const route = useRoute()
const router = useRouter()
const errorMessage = ref<string | null>(null)
const deepLinkUrl = ref<string | null>(null)

const handleAuthSuccess = async (accessToken: string, refreshToken?: string | null, email?: string | null) => {
  localStorage.setItem('token', accessToken)
  if (refreshToken) localStorage.setItem('refresh_token', refreshToken)
  if (email) localStorage.setItem('user_email', email)
  if (window.history.replaceState) {
    window.history.replaceState(null, '', window.location.pathname)
  }
  await fetchUserProfile().catch(() => {})

  const isAndroid = typeof navigator !== 'undefined' && /android/i.test(navigator.userAgent)
  if (isAndroid) {
    const deepLink = `com.notesight://auth/callback#access_token=${encodeURIComponent(accessToken)}&refresh_token=${encodeURIComponent(refreshToken || '')}&email=${encodeURIComponent(email || '')}`
    deepLinkUrl.value = deepLink
    try {
      window.location.href = deepLink
    } catch {}
    setTimeout(() => {
      if (typeof document !== 'undefined' && !document.hidden) {
        router.push({ name: 'Dashboard' })
      }
    }, 2500)
    return
  }

  router.push({ name: 'Dashboard' })
}

onMounted(async () => {
  // Check if tokens were passed via URL hash fragment (secure: not sent over HTTP) or query params
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const hashAccessToken = hashParams.get('access_token')
  const hashRefreshToken = hashParams.get('refresh_token')
  const hashEmail = hashParams.get('email')
  const hashRequires2fa = hashParams.get('requires_2fa') === '1' || hashParams.get('requires_2fa') === 'true'
  const hashTempToken = hashParams.get('temp_token')

  const effectiveRequires2fa = hashRequires2fa || route.query.requires_2fa === '1' || route.query.requires_2fa === 'true'
  const effectiveTempToken = hashTempToken || (route.query.temp_token as string)
  const effectiveEmail = hashEmail || (route.query.email as string)

  if (effectiveRequires2fa && effectiveTempToken) {
    router.push({
      name: 'Login',
      query: {
        requires_2fa: '1',
        temp_token: effectiveTempToken,
        email: effectiveEmail || '',
      },
    })
    return
  }

  const effectiveAccessToken = hashAccessToken || (route.query.access_token as string)
  const effectiveRefreshToken = hashRefreshToken || (route.query.refresh_token as string)

  if (effectiveAccessToken) {
    await handleAuthSuccess(effectiveAccessToken, effectiveRefreshToken, effectiveEmail)
    return
  }

  // Otherwise check if auth code and state were passed from Google
  const code = route.query.code as string
  const state = route.query.state as string

  if (!code) {
    const error = route.query.error as string
    errorMessage.value = error || 'No authorization code found in Google callback.'
    return
  }

  try {
    const targetUrl = resolveApiUrl('/api/auth/google/callback')
    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ code, state }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Google sign in failed')
    }

    const tokenData = await response.json()
    if (tokenData.requires_2fa) {
      router.push({
        name: 'Login',
        query: {
          requires_2fa: '1',
          temp_token: tokenData.temp_token,
          email: tokenData.email || '',
        },
      })
      return
    }

    // Persist user email to localStorage for topbar and profile awareness
    let userEmail = tokenData.email
    if (!userEmail && tokenData.access_token) {
      try {
        const payloadBase64 = tokenData.access_token.split('.')[1]
        const payloadJson = atob(payloadBase64.replace(/-/g, '+').replace(/_/g, '/'))
        const parsed = JSON.parse(payloadJson)
        if (parsed.sub) userEmail = parsed.sub
      } catch {}
    }

    await handleAuthSuccess(tokenData.access_token, tokenData.refresh_token, userEmail)
  } catch (err: any) {
    const rawMsg = err?.message || ''
    if (rawMsg.includes('Failed to fetch') || rawMsg.includes('NetworkError')) {
      errorMessage.value = 'Unable to reach authentication servers to complete Google Sign In. Please try again.'
    } else {
      errorMessage.value = rawMsg || 'Authentication with Google failed.'
    }
  }
})
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div v-if="!errorMessage" class="status-box">
        <div class="spinner"></div>
        <h3>{{ deepLinkUrl ? 'Opening NoteSight App...' : $t('auth.signingIn') }}</h3>
        <p class="subtext">{{ deepLinkUrl ? 'If the NoteSight app does not open automatically, tap below:' : $t('authFlows.oauthSettingUp') }}</p>
        <div v-if="deepLinkUrl" class="deep-link-action-group">
          <a :href="deepLinkUrl" class="primary-btn">
            Open NoteSight App
          </a>
          <button type="button" class="text-btn" @click="router.push({ name: 'Dashboard' })">
            Continue in browser
          </button>
        </div>
      </div>

      <div v-else class="status-box error">
        <div class="icon-circle error-icon">✕</div>
        <h3>{{ $t('authFlows.oauthFailed') }}</h3>
        <p class="error-desc">{{ errorMessage }}</p>
        <router-link to="/login" class="primary-btn">
          {{ $t('authFlows.backToSignIn') }}
        </router-link>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: calc(100vh - 160px);
  padding: 24px;
}

.auth-card {
  background: var(--bg-card, #ffffff);
  padding: 44px 36px;
  border-radius: 16px;
  box-shadow: var(--shadow-md, 0 10px 25px -5px rgba(0, 0, 0, 0.05));
  width: 100%;
  max-width: 420px;
  border: 1px solid var(--border, #e6e2d8);
  text-align: center;
}

.status-box {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.spinner {
  width: 44px;
  height: 44px;
  border: 4px solid rgba(79, 70, 229, 0.15);
  border-top-color: var(--color-primary, #4f46e5);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 20px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

h3 {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, #121624);
  margin: 0 0 8px 0;
}

.subtext {
  font-size: 0.9rem;
  color: var(--text-secondary, #585d6e);
  margin: 0;
}

.icon-circle {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 16px;
}

.error-icon {
  background: rgba(239, 68, 68, 0.15);
  color: #dc2626;
  border: 2px solid #ef4444;
}

.error-desc {
  font-size: 0.9rem;
  color: var(--text-secondary, #585d6e);
  margin: 0 0 20px 0;
  line-height: 1.45;
}

.primary-btn {
  display: inline-block;
  background: var(--color-primary, #4f46e5);
  color: #ffffff;
  padding: 10px 24px;
  border-radius: 8px;
  text-decoration: none;
  font-size: 0.95rem;
  font-weight: 600;
  transition: all 0.2s;
}

.primary-btn:hover {
  background: var(--color-primary-hover, #4338ca);
}

.deep-link-action-group {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.text-btn {
  background: none;
  border: none;
  color: var(--text-secondary, #585d6e);
  font-size: 0.875rem;
  cursor: pointer;
  text-decoration: underline;
  padding: 4px 8px;
  transition: color 0.2s;
}

.text-btn:hover {
  color: var(--color-primary, #4f46e5);
}
</style>
