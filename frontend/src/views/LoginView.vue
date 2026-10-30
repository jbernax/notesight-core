<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { t } from '../i18n'
import { Capacitor } from '@capacitor/core'
import { Browser } from '@capacitor/browser'
import { resolveApiUrl } from '../services/apiClient'


const router = useRouter()
const route = useRoute()
const email = ref('')
const password = ref('')
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const warningMessage = ref<string | null>(null)
const isLoading = ref(false)
const isGoogleLoading = ref(false)
const isUnverified = ref(false)
const isResendingVerification = ref(false)
const resendCooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | null = null

const startCooldown = (seconds: number) => {
  resendCooldown.value = seconds
  if (cooldownTimer) clearInterval(cooldownTimer)
  cooldownTimer = setInterval(() => {
    if (resendCooldown.value > 0) {
      resendCooldown.value--
    } else if (cooldownTimer) {
      clearInterval(cooldownTimer)
    }
  }, 1000)
}

// 2FA Challenge state
const showTotpChallenge = ref(false)
const tempToken = ref<string | null>(null)
const totpCode = ref('')
const isTotpSubmitting = ref(false)
const useBackupCode = ref(false)

onMounted(() => {
  if (route.query.requires_2fa && route.query.temp_token) {
    tempToken.value = route.query.temp_token as string
    showTotpChallenge.value = true
    if (route.query.email) {
      email.value = route.query.email as string
    }
  } else if (route.query.registered) {
    if (route.query.email) {
      email.value = route.query.email as string
    }
    if (route.query.rate_limited) {
      const waitSec = route.query.retry_after ? ` (${route.query.retry_after}s)` : ''
      warningMessage.value = `Account created! Auto-login was delayed due to rate limiting${waitSec}. Please verify your email before signing in.`
    } else {
      warningMessage.value = t('authFlows.accountCreatedNotice')
    }
  } else if (route.query.verified) {
    successMessage.value = t('authFlows.emailVerifiedNotice')
  } else if (route.query.oauth_error) {
    errorMessage.value = `Google Sign In error: ${route.query.oauth_error}`
  } else if (route.query.oauth_demo) {
    errorMessage.value = 'Google OAuth credentials are not configured in backend .env. Please sign in with email/password.'
  }
})

const resendVerificationFromLogin = async () => {
  if (isResendingVerification.value || resendCooldown.value > 0) return
  const targetEmail = email.value.trim()
  if (!targetEmail) {
    errorMessage.value = t('authFlows.enterEmailToResend')
    isUnverified.value = true
    return
  }

  isResendingVerification.value = true
  try {
    const res = await fetch(resolveApiUrl('/api/auth/request-verification'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: targetEmail }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      if (res.status === 429) {
        const retryAfter = parseInt(res.headers.get('Retry-After') || '60', 10)
        startCooldown(retryAfter)
        throw new Error(data.detail || t('authFlows.tooManyResendRequests', { seconds: retryAfter }))
      }
      throw new Error(data.detail || 'Failed to resend verification email')
    }
    successMessage.value = t('authFlows.verificationSentNotice')
    startCooldown(60)
  } catch (err: any) {
    const raw = err?.message || ''
    errorMessage.value = raw.includes('Failed to fetch') ? 'Unable to reach NoteSight server. Please check your connection.' : raw || 'Failed to resend verification email'
  } finally {
    isResendingVerification.value = false
  }
}

const handleLogin = async () => {
  isLoading.value = true
  errorMessage.value = null
  successMessage.value = null
  warningMessage.value = null
  isUnverified.value = false
  try {
    const formData = new URLSearchParams()
    formData.append('username', email.value.trim())
    formData.append('password', password.value)

    const response = await fetch(resolveApiUrl('/api/token'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData.toString(),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      const detail = data.detail || 'Login failed'
      if (response.status === 403 && typeof detail === 'string' && detail.toLowerCase().includes('verify')) {
        isUnverified.value = true
        errorMessage.value = detail
        return
      }
      throw new Error(detail)
    }

    const data = await response.json()
    if (data.requires_2fa) {
      tempToken.value = data.temp_token
      showTotpChallenge.value = true
      totpCode.value = ''
      return
    }

    localStorage.setItem('token', data.access_token)
    if (data.refresh_token) {
      localStorage.setItem('refresh_token', data.refresh_token)
    }
    localStorage.setItem('user_email', email.value.trim())
    router.push({ name: 'Dashboard' })
  } catch (err: any) {
    const raw = err?.message || ''
    errorMessage.value = raw.includes('Failed to fetch') ? 'Unable to reach NoteSight server. Please check your connection.' : raw || 'Login failed'
  } finally {
    isLoading.value = false
  }
}

const handleTotpLogin = async () => {
  if (!tempToken.value || !totpCode.value.trim()) return
  isTotpSubmitting.value = true
  errorMessage.value = null
  try {
    const response = await fetch(resolveApiUrl('/api/auth/2fa/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        temp_token: tempToken.value,
        code: totpCode.value.trim(),
      }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Invalid authentication code or backup recovery code.')
    }

    const data = await response.json()
    localStorage.setItem('token', data.access_token)
    if (data.refresh_token) {
      localStorage.setItem('refresh_token', data.refresh_token)
    }
    localStorage.setItem('user_email', email.value.trim())
    router.push({ name: 'Dashboard' })
  } catch (err: any) {
    const raw = err?.message || ''
    errorMessage.value = raw.includes('Failed to fetch') ? 'Unable to reach NoteSight server. Please check your connection.' : raw || 'Verification failed.'
  } finally {
    isTotpSubmitting.value = false
  }
}

const cancelTotpChallenge = () => {
  showTotpChallenge.value = false
  tempToken.value = null
  totpCode.value = ''
  errorMessage.value = null
}

const signInWithGoogle = async () => {
  isGoogleLoading.value = true
  errorMessage.value = null
  try {
    const isNative = Capacitor.isNativePlatform()
    const protocol = window.location.protocol || 'http:'
    const callbackUri = `${protocol}//${window.location.host}/auth/google/callback`

    const targetUrl = resolveApiUrl(`/api/auth/google/url?redirect_uri=${encodeURIComponent(callbackUri)}`)
    const res = await fetch(targetUrl)
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Failed to initialize Google authentication')
    }
    const data = await res.json()
    if (data.url.includes('oauth_demo=true')) {
      errorMessage.value = 'Google OAuth is in demo mode (client credentials not set in backend .env). You can use email/password to sign in.'
      return
    }
    if (isNative) {
      await Browser.open({ url: data.url, windowName: '_system' })
    } else {
      window.location.href = data.url
    }
  } catch (err: any) {
    const rawMsg = err?.message || ''
    if (rawMsg.includes('Failed to fetch') || rawMsg.includes('NetworkError') || rawMsg.includes('Load failed')) {
      errorMessage.value = 'Unable to reach NoteSight authentication services. Please check your network connection.'
    } else {
      errorMessage.value = rawMsg || 'Could not connect to Google sign-in services.'
    }
  } finally {
    isGoogleLoading.value = false
  }
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <img src="/favicon.svg" alt="NoteSight" class="auth-logo" width="52" height="52" />
        <h2>{{ t('auth.loginTitle') }}</h2>
        <p class="subtext">{{ t('auth.loginSubtitle') }}</p>
      </div>

      <div v-if="errorMessage" class="alert-box error">
        <div>{{ errorMessage }}</div>
        <div v-if="isUnverified || (errorMessage && errorMessage.toLowerCase().includes('verify'))" class="unverified-action-row">
          <button
            type="button"
            class="resend-unverified-btn"
            :disabled="isResendingVerification || resendCooldown > 0"
            @click="resendVerificationFromLogin"
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
              <polyline points="22,6 12,13 2,6"/>
            </svg>
            <span v-if="isResendingVerification">{{ t('authFlows.sendingVerification') }}</span>
            <span v-else-if="resendCooldown > 0">{{ t('authFlows.resendCooldown', { seconds: resendCooldown }) }}</span>
            <span v-else>{{ t('authFlows.resendVerificationBtn') }}</span>
          </button>
        </div>
      </div>

      <div v-if="warningMessage" class="alert-box warning">
        <div>{{ warningMessage }}</div>
        <div v-if="route.query.registered" class="unverified-action-row warning-action-row">
          <button
            type="button"
            class="resend-unverified-btn"
            :disabled="isResendingVerification || resendCooldown > 0"
            @click="resendVerificationFromLogin"
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
              <polyline points="22,6 12,13 2,6"/>
            </svg>
            <span v-if="isResendingVerification">{{ t('authFlows.sendingVerification') }}</span>
            <span v-else-if="resendCooldown > 0">{{ t('authFlows.resendCooldown', { seconds: resendCooldown }) }}</span>
            <span v-else>{{ t('authFlows.resendVerificationBtn') }}</span>
          </button>
        </div>
      </div>

      <div v-if="successMessage" class="alert-box success">
        {{ successMessage }}
      </div>

      <!-- Two-Factor Authentication Challenge -->
      <div v-if="showTotpChallenge" class="totp-challenge-panel">
        <div class="totp-header">
          <div class="totp-icon-wrap">
            <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <h3>Two-Factor Authentication</h3>
          <p class="subtext">
            {{ useBackupCode ? 'Enter one of your 8-character backup recovery codes.' : 'Enter the 6-digit verification code from your authenticator app.' }}
          </p>
        </div>

        <form @submit.prevent="handleTotpLogin" class="auth-form">
          <div class="form-group">
            <label for="totpCode">{{ useBackupCode ? 'Backup Recovery Code' : '6-Digit Passcode' }}</label>
            <input
              id="totpCode"
              v-model="totpCode"
              type="text"
              autocomplete="one-time-code"
              :placeholder="useBackupCode ? 'e.g. A1B2-C3D4' : '000000'"
              maxlength="16"
              required
              autofocus
              :disabled="isTotpSubmitting"
              class="totp-code-input"
            />
          </div>

          <button type="submit" class="submit-btn" :disabled="isTotpSubmitting || !totpCode.trim()">
            <span v-if="isTotpSubmitting">{{ t('common.loading') }}</span>
            <span v-else>Verify & Sign In</span>
          </button>
        </form>

        <div class="totp-actions">
          <button
            type="button"
            class="text-link-btn"
            @click="useBackupCode = !useBackupCode; totpCode = ''"
          >
            {{ useBackupCode ? 'Use 6-digit authenticator app code instead' : 'Lost device? Use an emergency backup code' }}
          </button>
          <button
            type="button"
            class="text-link-btn cancel-btn"
            @click="cancelTotpChallenge"
          >
            ← Cancel and return to login
          </button>
        </div>
      </div>

      <!-- Standard Login View -->
      <div v-else>
        <!-- Google OAuth Sign In Button -->
        <button
          type="button"
          class="google-btn"
          :disabled="isLoading || isGoogleLoading"
          @click="signInWithGoogle"
        >
          <svg class="google-icon" viewBox="0 0 24 24" width="20" height="20">
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
            />
            <path
              fill="#34A853"
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
            />
            <path
              fill="#EA4335"
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
            />
          </svg>
          <span v-if="isGoogleLoading">{{ t('common.loading') }}</span>
          <span v-else>{{ t('auth.continueWithGoogle') }}</span>
        </button>

        <div class="oauth-divider">
          <span>{{ t('auth.orEmail') }}</span>
        </div>

        <form @submit.prevent="handleLogin" class="auth-form">
          <div class="form-group">
            <label for="email">{{ t('auth.emailLabel') }}</label>
            <input
              id="email"
              v-model="email"
              type="email"
              placeholder="you@example.com"
              required
              :disabled="isLoading || isGoogleLoading"
            />
          </div>

          <div class="form-group">
            <div class="label-row">
              <label for="password">{{ t('auth.passwordLabel') }}</label>
              <router-link to="/forgot-password" class="forgot-link">{{ t('auth.forgotPasswordLink') }}</router-link>
            </div>
            <input
              id="password"
              v-model="password"
              type="password"
              placeholder="••••••••"
              required
              :disabled="isLoading || isGoogleLoading"
            />
          </div>

          <button type="submit" class="submit-btn" :disabled="isLoading || isGoogleLoading">
            <span v-if="isLoading">{{ t('auth.signingIn') }}</span>
            <span v-else>{{ t('auth.signInBtn') }}</span>
          </button>
        </form>

        <div class="auth-footer">
          <p>{{ t('auth.noAccount') }} <router-link to="/register">{{ t('auth.createAccountLink') }}</router-link></p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 32px 24px 8rem 24px;
  box-sizing: border-box;
}

.auth-card {
  background: var(--bg-card, #ffffff);
  padding: 40px;
  border-radius: 16px;
  box-shadow: var(--shadow-md, 0 10px 25px -5px rgba(0, 0, 0, 0.05));
  width: 100%;
  max-width: 420px;
  border: 1px solid var(--border, #e6e2d8);
}

.auth-header {
  text-align: center;
  margin-bottom: 24px;
}

.auth-logo {
  width: 52px;
  height: 52px;
  margin-bottom: 12px;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25);
}

.auth-header h2 {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary, #121624);
  margin-bottom: 6px;
}

.subtext {
  color: var(--text-secondary, #585d6e);
  font-size: 0.9rem;
}

.google-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: #ffffff;
  color: #1f2937;
  border: 1px solid #d1d5db;
  padding: 11px 16px;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.google-btn:hover:not(:disabled) {
  background: #f9fafb;
  border-color: #9ca3af;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.08);
}

.google-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.oauth-divider {
  display: flex;
  align-items: center;
  text-align: center;
  margin: 20px 0;
  color: var(--text-muted, #94a3b8);
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.oauth-divider::before,
.oauth-divider::after {
  content: '';
  flex: 1;
  border-bottom: 1px solid var(--border, #2e3a54);
}

.oauth-divider span {
  padding: 0 12px;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary, #121624);
}

.forgot-link {
  font-size: 0.82rem;
  color: var(--color-primary, #4f46e5);
  text-decoration: none;
  font-weight: 500;
}

.forgot-link:hover {
  text-decoration: underline;
}

.form-group input {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid var(--input-border, var(--border, #cbd5e1));
  background: var(--input-bg, rgba(12, 15, 23, 0.65));
  color: var(--text-primary, #121624);
  font-size: 0.95rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-group input::placeholder {
  color: var(--text-muted, #8b9bb4);
  opacity: 1;
}

.form-group input:focus {
  outline: none;
  border-color: var(--input-border-focus, var(--color-primary, #4f46e5));
  box-shadow: 0 0 0 3px var(--color-primary-light, rgba(79, 70, 229, 0.15));
}

.submit-btn {
  margin-top: 8px;
  background: var(--color-primary, #4f46e5);
  color: #ffffff;
  padding: 12px;
  border-radius: 8px;
  border: none;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.25);
}

.submit-btn:hover:not(:disabled) {
  background: var(--color-primary-hover, #4338ca);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.35);
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.auth-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 0.875rem;
  color: var(--text-secondary, #64748b);
}

.auth-footer a {
  color: var(--color-primary, #4f46e5);
  text-decoration: none;
  font-weight: 500;
}

.auth-footer a:hover {
  text-decoration: underline;
}

.alert-box.error {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.1));
  border: 1px solid var(--color-danger, #ef4444);
  color: var(--color-danger-text, #ef4444);
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 18px;
  font-size: 0.875rem;
}

.alert-box.warning {
  background: var(--color-warning-light, rgba(245, 158, 11, 0.12));
  border: 1px solid var(--color-warning, #f59e0b);
  color: var(--color-warning-text, #f59e0b);
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 18px;
  font-size: 0.875rem;
}

.alert-box.success {
  background: var(--color-success-light, rgba(16, 185, 129, 0.12));
  border: 1px solid var(--color-success, #10b981);
  color: var(--color-success-text, #10b981);
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 18px;
  font-size: 0.875rem;
}

.totp-challenge-panel {
  display: flex;
  flex-direction: column;
}

.totp-header {
  text-align: center;
  margin-bottom: 20px;
}

.totp-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(79, 70, 229, 0.1);
  color: var(--color-primary, #4f46e5);
  margin-bottom: 12px;
}

.totp-header h3 {
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0 0 6px 0;
  color: var(--text-primary, #0f172a);
}

.totp-code-input {
  font-size: 1.25rem;
  font-family: monospace;
  letter-spacing: 0.15em;
  text-align: center;
}

.totp-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
  text-align: center;
}

.text-link-btn {
  background: none;
  border: none;
  color: var(--color-primary, #4f46e5);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  padding: 6px;
  transition: opacity 0.2s;
}

.text-link-btn:hover {
  text-decoration: underline;
}

.text-link-btn.cancel-btn {
  color: var(--text-secondary, #64748b);
}

@media (max-width: 480px) {
  .auth-card {
    padding: 24px 18px;
    border-radius: 12px;
  }
}

.unverified-action-row {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid rgba(239, 68, 68, 0.25);
  display: flex;
  justify-content: flex-start;
}

.warning-action-row {
  border-top-color: rgba(245, 158, 11, 0.3);
}

.resend-unverified-btn {
  background: var(--color-primary, #6366f1);
  color: #ffffff;
  border: none;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 0.84rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.resend-unverified-btn:hover:not(:disabled) {
  background: var(--color-primary-hover, #4f46e5);
}

.resend-unverified-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
</style>
