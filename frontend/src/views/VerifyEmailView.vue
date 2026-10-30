<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const isVerifying = ref(false)
const isSuccess = ref(false)
const errorMessage = ref<string | null>(null)

onMounted(async () => {
  const queryStatus = route.query.status as string
  if (queryStatus === 'success') {
    isSuccess.value = true
    return
  }
  if (queryStatus === 'error') {
    errorMessage.value = 'Verification failed or link expired. Please request a new verification link.'
    return
  }

  const token = route.query.token as string
  if (!token) {
    errorMessage.value = 'No verification token provided.'
    return
  }

  isVerifying.value = true
  try {
    const response = await fetch('/api/auth/verify-email', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ token }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || 'Email verification failed')
    }

    isSuccess.value = true
  } catch (err: any) {
    errorMessage.value = err.message || 'Verification link expired or invalid.'
  } finally {
    isVerifying.value = false
  }
})

const navigateNext = () => {
  const token = localStorage.getItem('token')
  if (token) {
    router.push({ name: 'Dashboard' })
  } else {
    router.push({ name: 'Login', query: { verified: 'true' } })
  }
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <img src="/favicon.svg" alt="NoteSight" class="auth-logo" />
        <h2>{{ $t('authFlows.verifyEmailTitle') }}</h2>
      </div>

      <div v-if="isVerifying" class="status-box loading">
        <div class="spinner"></div>
        <p>{{ $t('authFlows.verifyingEmail') }}</p>
      </div>

      <div v-else-if="isSuccess" class="status-box success">
        <div class="icon-circle success-icon">✓</div>
        <h3>{{ $t('authFlows.verifySuccessTitle') }}</h3>
        <p class="status-desc">{{ $t('authFlows.verifySuccessMsg') }}</p>
        <button class="primary-btn" @click="navigateNext">
          {{ $t('authFlows.continueToDashboard') }}
        </button>
      </div>

      <div v-else-if="errorMessage" class="status-box error">
        <div class="icon-circle error-icon">✕</div>
        <h3>{{ $t('authFlows.verifyFailedTitle') }}</h3>
        <p class="status-desc">{{ errorMessage }}</p>
        <router-link to="/login" class="secondary-btn">
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
  padding: 40px;
  border-radius: 16px;
  box-shadow: var(--shadow-md, 0 10px 25px -5px rgba(0, 0, 0, 0.05));
  width: 100%;
  max-width: 440px;
  border: 1px solid var(--border, #e6e2d8);
  text-align: center;
}

.auth-header {
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
  margin: 0;
}

.status-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 0;
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

.success-icon {
  background: rgba(16, 185, 129, 0.15);
  color: #059669;
  border: 2px solid #10b981;
}

.error-icon {
  background: rgba(239, 68, 68, 0.15);
  color: #dc2626;
  border: 2px solid #ef4444;
}

h3 {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-primary, #121624);
  margin: 0 0 8px 0;
}

.status-desc {
  font-size: 0.9rem;
  color: var(--text-secondary, #585d6e);
  line-height: 1.5;
  margin-bottom: 24px;
}

.primary-btn {
  background: var(--color-primary, #4f46e5);
  color: #ffffff;
  padding: 12px 28px;
  border-radius: 8px;
  border: none;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.25);
}

.primary-btn:hover {
  background: var(--color-primary-hover, #4338ca);
}

.secondary-btn {
  display: inline-block;
  padding: 10px 24px;
  border-radius: 8px;
  background: var(--bg-hover, #f1f5f9);
  color: var(--text-primary, #121624);
  text-decoration: none;
  font-weight: 500;
  font-size: 0.9rem;
  transition: background 0.2s;
}

.secondary-btn:hover {
  background: #e2e8f0;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid rgba(79, 70, 229, 0.15);
  border-top-color: var(--color-primary, #4f46e5);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 16px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
