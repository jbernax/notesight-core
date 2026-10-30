<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const token = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)

// Password complexity rules
const hasLength = computed(() => newPassword.value.length >= 8)
const hasUpper = computed(() => /[A-Z]/.test(newPassword.value))
const hasNumber = computed(() => /\d/.test(newPassword.value))
const hasSpecial = computed(() => /[!@#$%^&*(),.?":{}|<>]/.test(newPassword.value))
const isPasswordValid = computed(() => hasLength.value && hasUpper.value && hasNumber.value && hasSpecial.value)
const doPasswordsMatch = computed(() => newPassword.value === confirmPassword.value && newPassword.value.length > 0)

onMounted(() => {
  const queryToken = route.query.token as string
  if (queryToken) {
    token.value = queryToken
  } else {
    errorMessage.value = 'No password reset token was provided in the link. Please request a new reset link.'
  }
})

const handleResetPassword = async () => {
  if (!isPasswordValid.value) {
    errorMessage.value = 'Password must meet all complexity requirements.'
    return
  }

  if (!doPasswordsMatch.value) {
    errorMessage.value = 'Passwords do not match.'
    return
  }

  isLoading.value = true
  errorMessage.value = null
  successMessage.value = null

  try {
    const response = await fetch('/api/auth/reset-password', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        token: token.value,
        new_password: newPassword.value,
      }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Password reset failed')
    }

    const data = await response.json()
    successMessage.value = data.message || 'Password successfully reset!'
    setTimeout(() => {
      router.push({ name: 'Login' })
    }, 2500)
  } catch (err: any) {
    errorMessage.value = err.message || 'Failed to reset password. The link may have expired.'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <img src="/favicon.svg" alt="NoteSight" class="auth-logo" />
        <h2>{{ $t('authFlows.setNewPasswordTitle') }}</h2>
        <p class="subtext">{{ $t('authFlows.setNewPasswordSubtitle') }}</p>
      </div>

      <div v-if="errorMessage" class="alert-box error">
        {{ errorMessage }}
      </div>

      <div v-if="successMessage" class="alert-box success">
        <p class="success-title">{{ $t('authFlows.resetCompleteTitle') }}</p>
        <p>{{ successMessage }}</p>
        <p class="redirect-hint">{{ $t('authFlows.redirectingToSignIn') }}</p>
      </div>

      <form v-if="!successMessage && token" @submit.prevent="handleResetPassword" class="auth-form">
        <!-- New Password -->
        <div class="form-group">
          <label for="newPassword">{{ $t('authFlows.newPasswordLabel') }}</label>
          <input
            id="newPassword"
            v-model="newPassword"
            type="password"
            placeholder="••••••••"
            required
            :disabled="isLoading"
          />
          <div class="password-checks">
            <span :class="{ 'valid': hasLength }">{{ $t('authFlows.minChars') }}</span>
            <span :class="{ 'valid': hasUpper }">{{ $t('authFlows.uppercase') }}</span>
            <span :class="{ 'valid': hasNumber }">{{ $t('authFlows.number') }}</span>
            <span :class="{ 'valid': hasSpecial }">{{ $t('authFlows.specialChar') }}</span>
          </div>
        </div>

        <!-- Confirm Password -->
        <div class="form-group">
          <label for="confirmPassword">{{ $t('auth.confirmPasswordLabel') }}</label>
          <input
            id="confirmPassword"
            v-model="confirmPassword"
            type="password"
            placeholder="••••••••"
            required
            :disabled="isLoading"
          />
          <small v-if="confirmPassword && !doPasswordsMatch" class="field-error">{{ $t('auth.passwordsDoNotMatch') }}</small>
        </div>

        <button
          type="submit"
          class="submit-btn"
          :disabled="isLoading || !isPasswordValid || !doPasswordsMatch"
        >
          <span v-if="isLoading">{{ $t('common.saving') }}</span>
          <span v-else>{{ $t('authFlows.setNewPasswordTitle') }}</span>
        </button>
      </form>

      <div class="auth-footer">
        <p><router-link to="/login">{{ $t('authFlows.backToSignIn') }}</router-link></p>
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
  padding: 40px;
  border-radius: 16px;
  box-shadow: var(--shadow-md, 0 10px 25px -5px rgba(0, 0, 0, 0.05));
  width: 100%;
  max-width: 440px;
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
  font-size: 1.45rem;
  font-weight: 700;
  color: var(--text-primary, #121624);
  margin-bottom: 8px;
}

.subtext {
  color: var(--text-secondary, #585d6e);
  font-size: 0.9rem;
  line-height: 1.45;
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

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary, #121624);
}

.form-group input {
  padding: 11px 14px;
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

.password-checks {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.password-checks span {
  font-size: 0.72rem;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-secondary, #64748b);
  transition: all 0.15s ease;
}

.password-checks span.valid {
  background: rgba(16, 185, 129, 0.15);
  color: #059669;
  font-weight: 600;
}

.field-error {
  font-size: 0.76rem;
  color: #ef4444;
}

.submit-btn {
  margin-top: 8px;
  background: var(--color-primary, #4f46e5);
  color: #ffffff;
  padding: 12px;
  border-radius: 8px;
  border: none;
  font-size: 0.95rem;
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

.alert-box {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 18px;
  font-size: 0.875rem;
  line-height: 1.5;
}

.alert-box.error {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.1));
  border: 1px solid var(--color-danger, #ef4444);
  color: var(--color-danger-text, #ef4444);
}

.alert-box.success {
  background: var(--color-success-light, rgba(16, 185, 129, 0.1));
  border: 1px solid var(--color-success, #10b981);
  color: var(--color-success-text, #065f46);
}

.success-title {
  font-weight: 700;
  font-size: 0.95rem;
  margin: 0 0 6px 0;
  color: var(--color-success-text, #047857);
}

.redirect-hint {
  font-size: 0.8rem;
  color: var(--color-success-text, #065f46);
  margin-top: 6px;
  opacity: 0.85;
}

@media (max-width: 480px) {
  .auth-card {
    padding: 24px 18px;
    border-radius: 12px;
  }
}
</style>
