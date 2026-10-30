<script setup lang="ts">
import { ref } from 'vue'

const email = ref('')
const isLoading = ref(false)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const handleForgotPassword = async () => {
  isLoading.value = true
  errorMessage.value = null
  successMessage.value = null

  try {
    const response = await fetch('/api/auth/forgot-password', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email: email.value.trim() }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Could not send reset link')
    }

    const data = await response.json()
    successMessage.value = data.message || 'If this email is registered, a password reset link has been sent.'
  } catch (err: any) {
    errorMessage.value = err.message || 'An error occurred while sending the reset link.'
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
        <h2>{{ $t('authFlows.forgotTitle') }}</h2>
        <p class="subtext">{{ $t('authFlows.forgotSubtitle') }}</p>
      </div>

      <div v-if="errorMessage" class="alert-box error">
        {{ errorMessage }}
      </div>

      <div v-if="successMessage" class="alert-box success">
        <p class="success-title">{{ $t('authFlows.checkEmail') }}</p>
        <p>{{ successMessage }}</p>
        <p class="email-note">{{ $t('authFlows.resetExpireHint') }}</p>
      </div>

      <form v-if="!successMessage" @submit.prevent="handleForgotPassword" class="auth-form">
        <div class="form-group">
          <label for="email">{{ $t('auth.emailLabel') }}</label>
          <input
            id="email"
            v-model="email"
            type="email"
            placeholder="you@example.com"
            required
            :disabled="isLoading"
          />
        </div>

        <button type="submit" class="submit-btn" :disabled="isLoading">
          <span v-if="isLoading">{{ $t('authFlows.sendingLink') }}</span>
          <span v-else>{{ $t('authFlows.sendResetBtn') }}</span>
        </button>
      </form>

      <div class="auth-footer">
        <p>{{ $t('authFlows.rememberedPwd') }} <router-link to="/login">{{ $t('authFlows.backToSignIn') }}</router-link></p>
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

.email-note {
  font-size: 0.8rem;
  color: var(--color-success-text, #065f46);
  margin-top: 8px;
  opacity: 0.85;
}

@media (max-width: 480px) {
  .auth-card {
    padding: 24px 18px;
    border-radius: 12px;
  }
}
</style>
