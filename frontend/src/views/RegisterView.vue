<script setup lang="ts">
import { ref, computed } from 'vue'
import TermsModal from '../components/TermsModal.vue'
import { t } from '../i18n'
import { Capacitor } from '@capacitor/core'
import { Browser } from '@capacitor/browser'
import { resolveApiUrl } from '../services/apiClient'

const fullName = ref('')
const birthdate = ref('')
const musicalRole = ref('Pianist')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const termsAccepted = ref(false)
const showTermsModal = ref(false)

const errorMessage = ref<string | null>(null)
const isLoading = ref(false)
const isGoogleLoading = ref(false)

const isRegistered = ref(false)
const registeredEmail = ref('')
const isResending = ref(false)
const resendSuccess = ref(false)
const resendCooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | null = null

const handleResendVerification = async () => {
  if (isResending.value || resendCooldown.value > 0 || !registeredEmail.value) return
  isResending.value = true
  resendSuccess.value = false
  errorMessage.value = null

  try {
    const res = await fetch(resolveApiUrl('/api/auth/request-verification'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: registeredEmail.value }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Failed to resend verification email')
    }
    resendSuccess.value = true
    resendCooldown.value = 60
    if (cooldownTimer) clearInterval(cooldownTimer)
    cooldownTimer = setInterval(() => {
      if (resendCooldown.value > 0) {
        resendCooldown.value--
      } else if (cooldownTimer) {
        clearInterval(cooldownTimer)
      }
    }, 1000)
  } catch (err: any) {
    const raw = err?.message || ''
    errorMessage.value = raw.includes('Failed to fetch') ? 'Unable to reach NoteSight server. Please check your connection.' : raw || 'Failed to resend verification email'
  } finally {
    isResending.value = false
  }
}

const signUpWithGoogle = async () => {
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
      errorMessage.value = 'Google OAuth credentials are not configured in backend .env. Please register using email/password.'
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

const roleOptions = [
  'Pianist',
  'Vocalist / Singer',
  'Choral Director',
  'Composer / Arranger',
  'Orchestral Instrumentalist',
  'Music Educator / Teacher',
  'Music Student',
  'Enthusiast / Hobbyist',
]

// Max birthdate is 13 years ago from today
const maxBirthdate = computed(() => {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 13)
  return d.toISOString().split('T')[0]
})

// Min birthdate is 125 years ago from today
const minBirthdate = computed(() => {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 125)
  return d.toISOString().split('T')[0]
})

// Password complexity rules
const hasLength = computed(() => password.value.length >= 8)
const hasUpper = computed(() => /[A-Z]/.test(password.value))
const hasNumber = computed(() => /\d/.test(password.value))
const hasSpecial = computed(() => /[!@#$%^&*(),.?":{}|<>]/.test(password.value))
const isPasswordValid = computed(() => hasLength.value && hasUpper.value && hasNumber.value && hasSpecial.value)
const doPasswordsMatch = computed(() => password.value === confirmPassword.value && password.value.length > 0)

const handleRegister = async () => {
  errorMessage.value = null

  if (!fullName.value.trim() || fullName.value.trim().length < 2) {
    errorMessage.value = 'Please enter your full name (at least 2 characters).'
    return
  }

  if (!birthdate.value) {
    errorMessage.value = 'Please select your birthdate.'
    return
  }

  // Age check
  const bdate = new Date(birthdate.value)
  const today = new Date()
  let age = today.getFullYear() - bdate.getFullYear()
  const m = today.getMonth() - bdate.getMonth()
  if (m < 0 || (m === 0 && today.getDate() < bdate.getDate())) {
    age--
  }
  if (age < 13 || birthdate.value > maxBirthdate.value) {
    errorMessage.value = 'You must be at least 13 years of age to register for NoteSight.'
    return
  }

  if (age > 125 || birthdate.value < minBirthdate.value) {
    errorMessage.value = 'Birthdate cannot be more than 125 years ago.'
    return
  }

  if (!isPasswordValid.value) {
    errorMessage.value = 'Password must meet all complexity requirements.'
    return
  }

  if (!doPasswordsMatch.value) {
    errorMessage.value = 'Passwords do not match.'
    return
  }

  if (!termsAccepted.value) {
    errorMessage.value = t('auth.mustAgreeTerms')
    return
  }

  isLoading.value = true

  try {
    const response = await fetch(resolveApiUrl('/api/register'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email: email.value.trim(),
        password: password.value,
        full_name: fullName.value.trim(),
        birthdate: birthdate.value,
        musical_role: musicalRole.value,
        terms_accepted: termsAccepted.value,
        terms_version: '2026.1-copyright',
      }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      let detailMsg = 'Registration failed'
      if (typeof data.detail === 'string') {
        detailMsg = data.detail
      } else if (Array.isArray(data.detail) && data.detail.length > 0) {
        detailMsg = data.detail[0].msg || 'Validation error'
      }
      throw new Error(detailMsg)
    }

    registeredEmail.value = email.value.trim()
    isRegistered.value = true
  } catch (err: any) {
    const raw = err?.message || ''
    errorMessage.value = raw.includes('Failed to fetch') ? 'Unable to reach NoteSight server. Please check your connection.' : raw || 'Registration failed'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <img src="/favicon.svg" alt="NoteSight" class="auth-logo" width="52" height="52" />
        <h2>{{ isRegistered ? t('authFlows.checkInboxTitle') : t('auth.registerTitle') }}</h2>
        <p class="subtext">{{ isRegistered ? t('authFlows.checkInboxSubtitle') : t('auth.registerSubtitle') }}</p>
      </div>

      <!-- Verification Pending Confirmation -->
      <div v-if="isRegistered" class="verification-pending-box">
        <div class="mail-icon-circle">
          <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
            <polyline points="22,6 12,13 2,6"/>
          </svg>
        </div>

        <div class="registered-email-badge">
          {{ registeredEmail }}
        </div>

        <p class="verification-instruction">
          {{ t('authFlows.checkInboxInstruction') }}
        </p>

        <div v-if="resendSuccess" class="alert-box success">
          {{ t('authFlows.verificationSentNotice') }}
        </div>

        <div v-if="errorMessage" class="alert-box error">
          {{ errorMessage }}
        </div>

        <div class="pending-actions">
          <button
            type="button"
            class="secondary-btn"
            :disabled="isResending || resendCooldown > 0"
            @click="handleResendVerification"
          >
            <span v-if="isResending">{{ t('authFlows.sendingVerification') }}</span>
            <span v-else-if="resendCooldown > 0">Resend in {{ resendCooldown }}s</span>
            <span v-else>{{ t('authFlows.resendVerificationBtn') }}</span>
          </button>

          <router-link
            :to="{ name: 'Login', query: { registered: 'true', email: registeredEmail } }"
            class="submit-btn sign-in-link"
          >
            {{ t('authFlows.continueToLogin') }}
          </router-link>
        </div>
      </div>

      <!-- Standard Registration Form -->
      <div v-else>
        <div class="free-tier-banner">
          <span class="banner-badge">{{ t('auth.freeForever') }}</span>
          <span>{{ t('auth.starterPlanIncluded') }}</span>
        </div>

        <div v-if="errorMessage" class="alert-box error">
          {{ errorMessage }}
        </div>

        <!-- Google OAuth Sign Up Button -->
        <button
          type="button"
          class="google-btn"
          :disabled="isLoading || isGoogleLoading"
          @click="signUpWithGoogle"
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
          <span v-if="isGoogleLoading">{{ t('auth.connectingGoogle') }}</span>
          <span v-else>{{ t('auth.continueWithGoogle') }}</span>
        </button>

        <div class="oauth-divider">
          <span>{{ t('auth.orRegisterEmail') }}</span>
        </div>

        <form @submit.prevent="handleRegister" class="auth-form">
          <!-- Full Name -->
          <div class="form-group">
            <label for="fullName">{{ t('auth.fullName') }} <span class="required-star">*</span></label>
            <input
              id="fullName"
              v-model="fullName"
              type="text"
              placeholder="e.g. Frédéric Chopin"
              required
              :disabled="isLoading"
            />
          </div>

          <div class="form-row">
            <!-- Birthdate -->
            <div class="form-group flex-1">
              <label for="birthdate">{{ t('auth.birthdate') }} <span class="required-star">*</span></label>
              <input
                id="birthdate"
                v-model="birthdate"
                type="date"
                :min="minBirthdate"
                :max="maxBirthdate"
                required
                :disabled="isLoading"
              />
              <small class="field-hint">{{ t('auth.ageRequirement') }}</small>
            </div>

            <!-- Musical Focus -->
            <div class="form-group flex-1">
              <label for="musicalRole">{{ t('auth.musicalFocus') }}</label>
              <select id="musicalRole" v-model="musicalRole" :disabled="isLoading" class="form-select">
                <option v-for="role in roleOptions" :key="role" :value="role">{{ role }}</option>
              </select>
            </div>
          </div>

          <!-- Email -->
          <div class="form-group">
            <label for="email">{{ t('auth.emailLabel') }} <span class="required-star">*</span></label>
            <input
              id="email"
              v-model="email"
              type="email"
              placeholder="you@example.com"
              required
              :disabled="isLoading"
            />
          </div>

          <!-- Password -->
          <div class="form-group">
            <label for="password">{{ t('auth.passwordLabel') }} <span class="required-star">*</span></label>
            <input
              id="password"
              v-model="password"
              type="password"
              placeholder="••••••••"
              required
              :disabled="isLoading"
            />
            <div class="password-checks">
              <span :class="{ 'valid': hasLength }">{{ t('authFlows.minChars') }}</span>
              <span :class="{ 'valid': hasUpper }">{{ t('authFlows.uppercase') }}</span>
              <span :class="{ 'valid': hasNumber }">{{ t('authFlows.number') }}</span>
              <span :class="{ 'valid': hasSpecial }">{{ t('authFlows.specialChar') }}</span>
            </div>
          </div>

          <!-- Confirm Password -->
          <div class="form-group">
            <label for="confirmPassword">{{ t('auth.confirmPasswordLabel') }} <span class="required-star">*</span></label>
            <input
              id="confirmPassword"
              v-model="confirmPassword"
              type="password"
              placeholder="••••••••"
              required
              :disabled="isLoading"
            />
            <small v-if="confirmPassword && !doPasswordsMatch" class="field-error">{{ t('auth.passwordsDoNotMatch') }}</small>
          </div>

          <!-- Legal Compliance & Terms Acceptance -->
          <div class="form-group legal-group">
            <label class="checkbox-container">
              <input
                id="termsAccepted"
                type="checkbox"
                v-model="termsAccepted"
                required
                :disabled="isLoading"
              />
              <span class="checkbox-label">
                {{ t('auth.agreeToTermsPrefix') }}
                <button type="button" class="legal-link-btn" @click="showTermsModal = true">
                  {{ t('auth.termsAndPolicyLink') }}
                </button>
                {{ t('auth.agreeToTermsSuffix') }}
              </span>
            </label>
          </div>

          <button type="submit" class="submit-btn" :disabled="isLoading || !termsAccepted || !isPasswordValid">
            <span v-if="isLoading">{{ t('auth.signingUp') }}</span>
            <span v-else>{{ t('auth.signUpBtn') }}</span>
          </button>
        </form>

        <div class="auth-footer">
          <p>{{ t('auth.alreadyHaveAccount') }} <router-link to="/login">{{ t('nav.signIn') }}</router-link></p>
        </div>
      </div>
    </div>

    <!-- Terms and Copyright Policy Modal -->
    <TermsModal
      :is-open="showTermsModal"
      @close="showTermsModal = false"
    />
  </div>
</template>

<style scoped>
.auth-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 32px 20px 8rem 20px;
  box-sizing: border-box;
}

.auth-card {
  background: var(--bg-card, #ffffff);
  padding: 36px 40px;
  border-radius: 16px;
  box-shadow: var(--shadow-md, 0 10px 25px -5px rgba(0, 0, 0, 0.05));
  width: 100%;
  max-width: 480px;
  border: 1px solid var(--border, #e6e2d8);
}

.auth-header {
  text-align: center;
  margin-bottom: 20px;
}

.auth-logo {
  width: 44px;
  height: 44px;
  margin-bottom: 12px;
}

.auth-header h2 {
  font-size: 1.4rem;
  font-weight: 700;
  margin: 0 0 6px 0;
  color: var(--text-primary, #f8fafc);
}

.subtext {
  font-size: 0.88rem;
  color: var(--text-secondary, #94a3b8);
  margin: 0;
}

.free-tier-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  border: 1px solid var(--color-success, rgba(16, 185, 129, 0.3));
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.84rem;
  color: var(--text-primary, #f8fafc);
  margin-bottom: 20px;
}

.banner-badge {
  background: var(--color-success, #10b981);
  color: white;
  font-weight: 700;
  font-size: 0.72rem;
  padding: 2px 7px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.alert-box {
  padding: 12px 14px;
  border-radius: 8px;
  font-size: 0.86rem;
  margin-bottom: 18px;
}

.alert-box.error {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.15));
  border: 1px solid var(--color-danger, #ef4444);
  color: var(--color-danger-text, #ef4444);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-row {
  display: flex;
  gap: 12px;
}

.flex-1 {
  flex: 1;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-primary, #f8fafc);
}

.required-star {
  color: #ef4444;
}

.form-group input,
.form-select {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--input-border, #384666);
  background: var(--input-bg, rgba(12, 15, 23, 0.65));
  color: var(--text-primary, #f8fafc);
  font-size: 0.9rem;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.form-group input::placeholder {
  color: var(--text-muted, #8b9bb4);
  opacity: 1;
}

.form-group input[type="date"] {
  color-scheme: inherit;
}

.form-group input:focus,
.form-select:focus {
  border-color: var(--input-border-focus, #6366f1);
  box-shadow: 0 0 0 3px var(--color-primary-light, rgba(99, 102, 241, 0.15));
}

.form-select option {
  background: var(--bg-card, #151b28);
  color: var(--text-primary, #f8fafc);
}

.field-hint {
  font-size: 0.74rem;
  color: var(--text-secondary, #94a3b8);
}

.field-error {
  font-size: 0.76rem;
  color: #ef4444;
}

.password-checks {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.password-checks span {
  font-size: 0.72rem;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.05));
  color: var(--text-muted, #8b9bb4);
  border: 1px solid var(--border, transparent);
  transition: all 0.15s ease;
}

.password-checks span.valid {
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  color: var(--color-success, #10b981);
  border-color: var(--color-success, rgba(16, 185, 129, 0.3));
  font-weight: 600;
}

.legal-group {
  margin-top: 4px;
}

.checkbox-container {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
  font-size: 0.82rem;
  line-height: 1.45;
  color: var(--text-secondary, #94a3b8);
}

.checkbox-container input[type="checkbox"] {
  width: 17px;
  height: 17px;
  margin-top: 2px;
  cursor: pointer;
  accent-color: var(--color-primary, #6366f1);
}

.checkbox-label {
  flex: 1;
}

.legal-link-btn {
  background: transparent;
  border: none;
  padding: 0;
  color: var(--color-primary, #6366f1);
  font-weight: 600;
  font-size: inherit;
  text-decoration: underline;
  cursor: pointer;
  display: inline;
}

.legal-link-btn:hover {
  color: var(--color-primary-hover, #818cf8);
}

.submit-btn {
  background: var(--color-primary, #6366f1);
  color: white;
  padding: 12px;
  border-radius: 8px;
  border: none;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, opacity 0.15s ease;
  margin-top: 6px;
}

.submit-btn:hover:not(:disabled) {
  background: var(--color-primary-hover, #818cf8);
}

.submit-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.auth-footer {
  margin-top: 20px;
  text-align: center;
  font-size: 0.86rem;
  color: var(--text-secondary, #94a3b8);
}

.auth-footer a {
  color: var(--color-primary, #6366f1);
  text-decoration: none;
  font-weight: 600;
}

.auth-footer a:hover {
  text-decoration: underline;
  color: var(--color-primary-hover, #818cf8);
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
  margin: 18px 0;
  color: var(--text-muted, #8b9bb4);
  font-size: 0.8rem;
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
  padding: 0 10px;
}

@media (max-width: 480px) {
  .auth-card {
    padding: 24px 18px;
    border-radius: 12px;
  }
  .form-row {
    flex-direction: column;
    gap: 12px;
  }
}

.verification-pending-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 8px 0 4px 0;
}

.mail-icon-circle {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(99, 102, 241, 0.15);
  color: var(--color-primary, #6366f1);
  margin-bottom: 16px;
  border: 2px solid rgba(99, 102, 241, 0.3);
}

.registered-email-badge {
  display: inline-block;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.07));
  border: 1px solid var(--border, #384666);
  color: var(--text-primary, #f8fafc);
  padding: 6px 14px;
  border-radius: 20px;
  font-weight: 600;
  font-size: 0.92rem;
  margin: 10px 0 14px 0;
  word-break: break-all;
}

.verification-instruction {
  font-size: 0.88rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.5;
  margin: 0 0 20px 0;
}

.pending-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.secondary-btn {
  background: transparent;
  color: var(--text-primary, #f8fafc);
  border: 1px solid var(--border, #384666);
  padding: 11px 16px;
  border-radius: 8px;
  font-size: 0.92rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.secondary-btn:hover:not(:disabled) {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.05));
  border-color: var(--color-primary, #6366f1);
}

.secondary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.sign-in-link {
  display: block;
  text-decoration: none;
  text-align: center;
}
</style>
