<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { preferences, resetPreferencesToDefaults, type AppTheme } from '../composables/useSettings'
import { userQuota, isPlanModalOpen, resumeSubscription } from '../composables/useQuota'
import { cookieConsent, saveConsent } from '../composables/useCookieConsent'
import { userProfile, fetchUserProfile, updateUserProfile, changeUserPassword, requestVerificationEmail } from '../composables/useUserProfile'
import { INSTRUMENT_OPTIONS } from '../audio/synth'
import { showToast } from '../composables/useToast'
import { apiFetch, clearAuthSession } from '../services/apiClient'
import TermsModal from './TermsModal.vue'
import { t, currentLocale, setLocale, SUPPORTED_LOCALES, type SupportedLocale } from '../i18n'


const props = withDefaults(defineProps<{
  isOpen: boolean
  userEmail: string | null
  initialTab?: 'account' | 'security' | 'billing' | 'preferences' | 'privacy'
}>(), {
  initialTab: 'account'
})

const emit = defineEmits<{
  (e: 'close'): void
}>()

const activeTab = ref<'account' | 'security' | 'billing' | 'preferences' | 'privacy'>('account')
const showTermsModal = ref(false)

const getTabLabelShort = (tabKey: 'account' | 'security' | 'billing' | 'preferences' | 'privacy'): string => {
  const full = t(`settings.tabs.${tabKey}`)
  const parts = full.split(/ [&y]| et | und | e | \/ /i)
  if (parts.length > 1 && parts[0].trim().length > 0) {
    return parts[0].trim()
  }
  if (tabKey === 'preferences') {
    if (full.includes('Studio Preferences')) return 'Preferences'
    if (full.includes('Preferencias')) return 'Preferencias'
    if (full.includes('Einstellungen')) return 'Einstellungen'
    if (full.includes('Préférences')) return 'Préférences'
  }
  return full.split(' ')[0] || full
}

// Account Form State
const editFullName = ref('')
const editBirthdate = ref('')
const editMusicalRole = ref('')
const editCountry = ref('')
const editBio = ref('')
const isSavingProfile = ref(false)
const profileFeedback = ref<{ type: 'success' | 'error'; message: string } | null>(null)

const maxBirthdate = computed(() => {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 13)
  return d.toISOString().split('T')[0]
})

const minBirthdate = computed(() => {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 125)
  return d.toISOString().split('T')[0]
})


// ISO Country Options
const ISO_COUNTRIES = [
  { code: '', name: 'Select country / region...' },
  { code: 'US', name: 'United States' },
  { code: 'DE', name: 'Germany' },
  { code: 'FR', name: 'France' },
  { code: 'GB', name: 'United Kingdom' },
  { code: 'IT', name: 'Italy' },
  { code: 'ES', name: 'Spain' },
  { code: 'CA', name: 'Canada' },
  { code: 'AU', name: 'Australia' },
  { code: 'JP', name: 'Japan' },
  { code: 'AT', name: 'Austria' },
  { code: 'BE', name: 'Belgium' },
  { code: 'CH', name: 'Switzerland' },
  { code: 'CZ', name: 'Czech Republic' },
  { code: 'DK', name: 'Denmark' },
  { code: 'FI', name: 'Finland' },
  { code: 'IE', name: 'Ireland' },
  { code: 'NL', name: 'Netherlands' },
  { code: 'NO', name: 'Norway' },
  { code: 'PL', name: 'Poland' },
  { code: 'PT', name: 'Portugal' },
  { code: 'SE', name: 'Sweden' },
  { code: 'BR', name: 'Brazil' },
  { code: 'MX', name: 'Mexico' },
  { code: 'KR', name: 'South Korea' },
  { code: 'CN', name: 'China' },
  { code: 'IN', name: 'India' },
  { code: 'NZ', name: 'New Zealand' },
  { code: 'SG', name: 'Singapore' },
  { code: 'ZA', name: 'South Africa' },
  { code: 'OTHER', name: 'Other / International' }
]

// Password Form State
const currentPassword = ref('')
const newPassword = ref('')
const confirmNewPassword = ref('')
const isChangingPassword = ref(false)
const passwordFeedback = ref<{ type: 'success' | 'error'; message: string } | null>(null)

const passwordStrength = computed(() => {
  const pwd = newPassword.value
  if (!pwd) return { score: 0, label: t('settings.security.strengthEnter'), color: '#64748b', percent: 0 }
  let score = 0
  if (pwd.length >= 8) score += 1
  if (/[A-Z]/.test(pwd) && /[a-z]/.test(pwd)) score += 1
  if (/[0-9]/.test(pwd)) score += 1
  if (/[^A-Za-z0-9]/.test(pwd)) score += 1

  switch (score) {
    case 1:
      return { score, label: t('settings.security.strengthWeak'), color: '#ef4444', percent: 25 }
    case 2:
      return { score, label: t('settings.security.strengthFair'), color: '#f97316', percent: 50 }
    case 3:
      return { score, label: t('settings.security.strengthGood'), color: '#eab308', percent: 75 }
    case 4:
      return { score, label: t('settings.security.strengthStrong'), color: '#10b981', percent: 100 }
    default:
      return { score: 0, label: t('settings.security.strengthTooShort'), color: '#64748b', percent: 10 }
  }
})

// 2FA State & Handlers
const showTotpSetupModal = ref(false)
const showTotpDisableModal = ref(false)
const totpSetupData = ref<{ secret: string; otpauth_uri: string; backup_codes: string[] } | null>(null)
const totpVerifyCode = ref('')
const isVerifyingTotp = ref(false)
const isSettingUpTotp = ref(false)
const totpDisablePassword = ref('')
const isDisablingTotp = ref(false)
const copiedSecret = ref(false)
const copiedBackupCodes = ref(false)

const handleToggle2FA = async () => {
  if (userProfile.value?.totp_enabled) {
    totpDisablePassword.value = ''
    showTotpDisableModal.value = true
  } else {
    await initiateTotpSetup()
  }
}

const initiateTotpSetup = async () => {
  isSettingUpTotp.value = true
  try {
    const res = await apiFetch('/api/auth/2fa/setup', {
      method: 'POST',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Could not initiate 2FA setup')
    }
    totpSetupData.value = await res.json()
    totpVerifyCode.value = ''
    copiedSecret.value = false
    copiedBackupCodes.value = false
    showTotpSetupModal.value = true
  } catch (err: any) {
    showToast({
      title: '2FA Setup Error',
      message: err.message || 'Failed to start 2FA configuration.',
      type: 'error',
    })
  } finally {
    isSettingUpTotp.value = false
  }
}

const confirmTotpVerify = async () => {
  if (!totpVerifyCode.value.trim()) return
  isVerifyingTotp.value = true
  try {
    const res = await apiFetch('/api/auth/2fa/verify', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ code: totpVerifyCode.value.trim() }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Invalid verification code')
    }
    showToast({
      title: '2FA Activated',
      message: 'Two-Factor Authentication is now successfully enabled on your account.',
      type: 'success',
    })
    showTotpSetupModal.value = false
    await fetchUserProfile()
  } catch (err: any) {
    showToast({
      title: 'Verification Failed',
      message: err.message || 'Invalid code. Check your authenticator app and try again.',
      type: 'error',
    })
  } finally {
    isVerifyingTotp.value = false
  }
}

const confirmTotpDisable = async () => {
  isDisablingTotp.value = true
  try {
    const res = await apiFetch('/api/auth/2fa/disable', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ password: totpDisablePassword.value }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Could not disable 2FA')
    }
    showToast({
      title: '2FA Disabled',
      message: 'Two-Factor Authentication has been disabled.',
      type: 'info',
    })
    showTotpDisableModal.value = false
    totpDisablePassword.value = ''
    await fetchUserProfile()
  } catch (err: any) {
    showToast({
      title: 'Disable 2FA Failed',
      message: err.message || 'Incorrect password.',
      type: 'error',
    })
  } finally {
    isDisablingTotp.value = false
  }
}

const copySecret = () => {
  if (totpSetupData.value?.secret) {
    navigator.clipboard.writeText(totpSetupData.value.secret)
    copiedSecret.value = true
    setTimeout(() => { copiedSecret.value = false }, 2500)
  }
}

const copyBackupCodes = () => {
  if (totpSetupData.value?.backup_codes) {
    navigator.clipboard.writeText(totpSetupData.value.backup_codes.join('\n'))
    copiedBackupCodes.value = true
    setTimeout(() => { copiedBackupCodes.value = false }, 2500)
  }
}


// Invoicing & Billing State
interface BillingStatus {
  tier: string
  has_active_subscription: boolean
  stripe_customer_id: string | null
  billing_name: string | null
  billing_email: string | null
  billing_country: string | null
  subscription: any
}
const billingStatus = ref<BillingStatus | null>(null)
const editBillingName = ref('')
const editBillingEmail = ref('')
const editBillingCountry = ref('')
const isSavingBilling = ref(false)
const billingFeedback = ref<{ type: 'success' | 'error'; message: string } | null>(null)
const isOpeningPortal = ref(false)

// Quota calculations
const pageUsagePercent = computed(() => {
  if (!userQuota.value || !userQuota.value.pages?.monthly_limit) return 0
  return Math.min(100, Math.round((userQuota.value.pages.processed_this_month / userQuota.value.pages.monthly_limit) * 100))
})

const storageUsagePercent = computed(() => {
  if (!userQuota.value || !userQuota.value.storage?.percent_used) return 0
  return Math.min(100, Math.round(userQuota.value.storage.percent_used))
})

// Privacy & Cookie toggles
const functionalCookie = ref(cookieConsent.value?.functional ?? true)
const analyticsCookie = ref(cookieConsent.value?.analytics ?? false)
const cookieFeedback = ref<string | null>(null)

const handleUpdateCookies = () => {
  saveConsent({
    functional: functionalCookie.value,
    analytics: analyticsCookie.value
  })
  cookieFeedback.value = t('settings.privacy.cookieSavedFeedback')
  setTimeout(() => {
    cookieFeedback.value = null
  }, 3000)
}

// GDPR Self-Service Actions
const handleExportAccountData = () => {
  const data = {
    profile: userProfile.value,
    quota: userQuota.value,
    preferences: preferences.value,
    cookieConsent: cookieConsent.value,
    exportedAt: new Date().toISOString()
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `notesight-account-data-${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

const isDeletingAccount = ref(false)
const showDeleteConfirm = ref(false)
const deleteAccountPassword = ref('')

const handleDeleteAccount = async () => {
  const isOAuth = userProfile.value?.oauth_provider != null
  let password: string | null = null

  if (!isOAuth) {
    if (!deleteAccountPassword.value) {
      showToast({
        title: 'Password Required',
        message: 'Please enter your password to confirm account deletion.',
        type: 'warning',
      })
      return
    }
    password = deleteAccountPassword.value
  }

  try {
    isDeletingAccount.value = true
    const resp = await apiFetch('/api/user/account', {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ password }),
    })

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}))
      throw new Error(errData.detail || 'Failed to delete account')
    }

    showToast({
      title: 'Account Deleted',
      message: 'Your account and all associated files have been permanently deleted.',
      type: 'info',
      duration: 5000,
    })

    clearAuthSession()
    emit('close')
    window.location.href = '/login'
  } catch (err: any) {
    showToast({
      title: 'Deletion Failed',
      message: err.message || 'Could not complete account deletion request.',
      type: 'error',
    })
  } finally {
    isDeletingAccount.value = false
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

const syncProfileForm = () => {
  if (userProfile.value) {
    editFullName.value = userProfile.value.full_name || ''
    editBirthdate.value = userProfile.value.birthdate || ''
    editMusicalRole.value = userProfile.value.musical_role || 'Pianist'

    const rawCountry = userProfile.value.country || ''
    const matched = ISO_COUNTRIES.find(c => c.code.toLowerCase() === rawCountry.toLowerCase() || c.name.toLowerCase() === rawCountry.toLowerCase())
    editCountry.value = matched ? matched.code : rawCountry

    editBio.value = userProfile.value.bio || ''
    editBillingName.value = userProfile.value.billing_name || userProfile.value.full_name || ''
    editBillingEmail.value = userProfile.value.email || ''

    const rawBillCountry = userProfile.value.billing_country || userProfile.value.country || ''
    const matchedBill = ISO_COUNTRIES.find(c => c.code.toLowerCase() === rawBillCountry.toLowerCase() || c.name.toLowerCase() === rawBillCountry.toLowerCase())
    editBillingCountry.value = matchedBill ? matchedBill.code : rawBillCountry

    emailNotificationsEnabled.value = userProfile.value.email_notifications_enabled ?? true
    allowOmrTelemetry.value = userProfile.value.allow_omr_telemetry ?? false
  }
}

// Email Verification & Notification Preferences
const isResendingVerification = ref(false)
const verificationFeedback = ref<{ type: 'success' | 'error'; message: string } | null>(null)
const emailNotificationsEnabled = ref(true)

const allowOmrTelemetry = ref(false)
const isUpdatingTelemetry = ref(false)

const handleResendVerification = async () => {
  isResendingVerification.value = true
  verificationFeedback.value = null
  const res = await requestVerificationEmail()
  isResendingVerification.value = false
  verificationFeedback.value = {
    type: res.success ? 'success' : 'error',
    message: res.message || (res.success ? t('settings.security.verificationSent') : t('common.error')),
  }
}

const handleToggleEmailNotifications = async () => {
  await updateUserProfile({
    email_notifications_enabled: emailNotificationsEnabled.value
  })
}

const handleToggleOmrTelemetry = async () => {
  isUpdatingTelemetry.value = true
  const res = await updateUserProfile({
    allow_omr_telemetry: allowOmrTelemetry.value
  })
  isUpdatingTelemetry.value = false
  if (res.success) {
    showToast({
      title: allowOmrTelemetry.value ? t('settings.privacy.telemetryEnabledTitle') : t('settings.privacy.telemetryDisabledTitle'),
      message: allowOmrTelemetry.value
        ? t('settings.privacy.telemetryEnabledMsg')
        : t('settings.privacy.telemetryDisabledMsg'),
      type: 'success',
      duration: 4000
    })
  } else {
    showToast({
      title: t('common.error'),
      message: res.message || 'Could not update telemetry preference.',
      type: 'error'
    })
  }
}

const fetchBillingDetails = async () => {
  const token = localStorage.getItem('token')
  if (!token) return
  try {
    const res = await apiFetch('/api/billing/status')
    if (res.ok) {
      billingStatus.value = await res.json()
      if (billingStatus.value?.billing_name) editBillingName.value = billingStatus.value.billing_name
      if (billingStatus.value?.billing_email) editBillingEmail.value = billingStatus.value.billing_email
      if (billingStatus.value?.billing_country) editBillingCountry.value = billingStatus.value.billing_country
    }
  } catch (err) {
    console.error('Failed to load billing status:', err)
  }
}

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    if (typeof window !== 'undefined' && window.innerWidth <= 640 && props.initialTab === 'billing') {
      activeTab.value = 'preferences'
    } else {
      activeTab.value = props.initialTab || 'account'
    }
    fetchUserProfile().then(syncProfileForm)
    fetchBillingDetails()
    functionalCookie.value = cookieConsent.value?.functional ?? true
    analyticsCookie.value = cookieConsent.value?.analytics ?? false
    profileFeedback.value = null
    passwordFeedback.value = null
    billingFeedback.value = null
    cookieFeedback.value = null
  }
})

const handleSaveProfile = async () => {
  if (!editFullName.value.trim() || editFullName.value.trim().length < 2) {
    profileFeedback.value = { type: 'error', message: t('settings.profile.nameTooShort') }
    return
  }

  if (editBirthdate.value) {
    const bdate = new Date(editBirthdate.value)
    const today = new Date()
    let age = today.getFullYear() - bdate.getFullYear()
    const m = today.getMonth() - bdate.getMonth()
    if (m < 0 || (m === 0 && today.getDate() < bdate.getDate())) {
      age--
    }
    if (age < 13 || editBirthdate.value > maxBirthdate.value) {
      profileFeedback.value = { type: 'error', message: t('settings.profile.minAgeError') }
      return
    }
    if (age > 125 || editBirthdate.value < minBirthdate.value) {
      profileFeedback.value = { type: 'error', message: t('settings.profile.maxAgeError') }
      return
    }
  }
  isSavingProfile.value = true
  profileFeedback.value = null
  const res = await updateUserProfile({
    full_name: editFullName.value.trim(),
    birthdate: editBirthdate.value || null,
    musical_role: editMusicalRole.value || null,
    country: editCountry.value.trim() || null,
    bio: editBio.value.trim() || null,
  })
  isSavingProfile.value = false
  if (res.success) {
    profileFeedback.value = { type: 'success', message: t('settings.profile.updateSuccess') }
  } else {
    profileFeedback.value = { type: 'error', message: res.message || t('settings.profile.updateError') }
  }
}

const handleChangePassword = async () => {
  passwordFeedback.value = null
  if (!currentPassword.value) {
    passwordFeedback.value = { type: 'error', message: t('settings.security.enterCurrentPasswordError') }
    return
  }
  if (newPassword.value !== confirmNewPassword.value) {
    passwordFeedback.value = { type: 'error', message: t('settings.security.passwordMismatchError') }
    return
  }
  if (newPassword.value.length < 8) {
    passwordFeedback.value = { type: 'error', message: t('settings.security.passwordLengthError') }
    return
  }

  isChangingPassword.value = true
  const res = await changeUserPassword({
    current_password: currentPassword.value,
    new_password: newPassword.value,
  })
  isChangingPassword.value = false

  if (res.success) {
    passwordFeedback.value = { type: 'success', message: t('settings.security.passwordUpdateSuccess') }
    currentPassword.value = ''
    newPassword.value = ''
    confirmNewPassword.value = ''
  } else {
    passwordFeedback.value = { type: 'error', message: res.message || t('settings.security.passwordUpdateError') }
  }
}

const handleSaveOptionalBilling = async () => {
  const token = localStorage.getItem('token')
  if (!token) return
  isSavingBilling.value = true
  billingFeedback.value = null
  try {
    const res = await apiFetch('/api/billing/details', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        billing_name: editBillingName.value.trim() || null,
        billing_email: editBillingEmail.value.trim() || null,
        billing_country: editBillingCountry.value.trim() || null,
      })
    })
    if (res.ok) {
      billingStatus.value = await res.json()
      billingFeedback.value = { type: 'success', message: t('settings.quotaSection.billingSaved') }
    } else {
      const err = await res.json().catch(() => ({}))
      billingFeedback.value = { type: 'error', message: err.detail || t('settings.quotaSection.billingSaveError') }
    }
  } catch (err: any) {
    billingFeedback.value = { type: 'error', message: err.message || 'Network error' }
  } finally {
    isSavingBilling.value = false
  }
}

const handleOpenStripePortal = async () => {
  const token = localStorage.getItem('token')
  if (!token) return
  isOpeningPortal.value = true
  try {
    const res = await apiFetch('/api/billing/create-portal-session', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        locale: currentLocale.value
      })
    })
    if (res.ok) {
      const data = await res.json()
      if (data.portal_url) {
        window.location.href = data.portal_url
      }
    } else {
      showToast({
        title: 'Billing Portal',
        message: 'Could not open Stripe Billing Portal at this time.',
        type: 'error',
      })
    }
  } catch {
    showToast({
      title: 'Billing Error',
      message: 'Failed to connect to billing provider.',
      type: 'error',
    })
  } finally {
    isOpeningPortal.value = false
  }
}

const isResumingInSettings = ref(false)

const handleResumeInSettings = async () => {
  isResumingInSettings.value = true
  try {
    const res = await resumeSubscription()
    if (res.success) {
      await fetchBillingDetails()
      showToast({
        title: t('plans.resumeSubscription'),
        message: t('plans.subscriptionResumedSuccess'),
        type: 'success',
      })
    } else {
      showToast({
        title: 'Billing Error',
        message: res.error || 'Failed to resume subscription.',
        type: 'error',
      })
    }
  } finally {
    isResumingInSettings.value = false
  }
}

const formatSettingsDate = (dateStr?: string | null): string => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

// Studio Preferences
const setTheme = (theme: AppTheme) => {
  preferences.value.theme = theme
}
const handleReset = () => {
  resetPreferencesToDefaults()
  showToast({
    title: 'Preferences Reset',
    message: 'Reset all studio preferences to default settings.',
    type: 'info',
  })
}

const formatDate = (isoString?: string | null) => {
  if (!isoString) return 'Not recorded'
  try {
    return new Date(isoString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  } catch {
    return isoString
  }
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen) {
    emit('close')
  }
}

const handleSignOutFromSettings = async () => {
  try {
    await apiFetch('/api/logout', { method: 'POST' })
  } catch {
    // Ignore network error so client sign out always succeeds
  }
  clearAuthSession()
  emit('close')
  window.dispatchEvent(new Event('notesight:auth-changed'))
  window.location.href = '/login'
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <teleport to="body">
    <div v-if="isOpen" class="settings-modal-backdrop" @click="emit('close')">
      <div class="settings-modal-card" @click.stop role="dialog" aria-modal="true" aria-labelledby="settings-title">
        
        <!-- Header -->
        <div class="settings-header">
          <div class="settings-title-group">
            <div class="settings-icon-wrapper">
              <svg class="settings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                <circle cx="12" cy="7" r="4"></circle>
              </svg>
            </div>
            <div>
              <h3 id="settings-title" class="settings-title">{{ t('settings.title') }}</h3>
              <p class="settings-subtitle">{{ t('settings.subtitle') }}</p>
            </div>
          </div>
          <button class="settings-close-btn" @click="emit('close')" :aria-label="t('common.close')">✕</button>
        </div>

        <!-- Navigation Tabs -->
        <div class="settings-nav-tabs" role="tablist">
          <button
            type="button"
            class="tab-btn"
            role="tab"
            :aria-selected="activeTab === 'account'"
            :class="{ 'active': activeTab === 'account' }"
            @click="activeTab = 'account'"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
            <span class="tab-label-text tab-label-full">{{ t('settings.tabs.account') }}</span>
            <span class="tab-label-text tab-label-short">{{ getTabLabelShort('account') }}</span>
          </button>

          <button
            type="button"
            class="tab-btn"
            role="tab"
            :aria-selected="activeTab === 'security'"
            :class="{ 'active': activeTab === 'security' }"
            @click="activeTab = 'security'"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
            <span class="tab-label-text tab-label-full">{{ t('settings.tabs.security') }}</span>
            <span class="tab-label-text tab-label-short">{{ getTabLabelShort('security') }}</span>
          </button>

          <button
            type="button"
            class="tab-btn tab-btn-billing"
            role="tab"
            :aria-selected="activeTab === 'billing'"
            :class="{ 'active': activeTab === 'billing' }"
            @click="activeTab = 'billing'"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="1" y="4" width="22" height="16" rx="2" ry="2"></rect>
              <line x1="1" y1="10" x2="23" y2="10"></line>
            </svg>
            <span class="tab-label-text tab-label-full">{{ t('settings.tabs.billing') }}</span>
            <span class="tab-label-text tab-label-short">{{ getTabLabelShort('billing') }}</span>
          </button>

          <button
            type="button"
            class="tab-btn"
            role="tab"
            :aria-selected="activeTab === 'preferences'"
            :class="{ 'active': activeTab === 'preferences' }"
            @click="activeTab = 'preferences'"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
            </svg>
            <span class="tab-label-text tab-label-full">{{ t('settings.tabs.preferences') }}</span>
            <span class="tab-label-text tab-label-short">{{ getTabLabelShort('preferences') }}</span>
          </button>

          <button
            type="button"
            class="tab-btn"
            role="tab"
            :aria-selected="activeTab === 'privacy'"
            :class="{ 'active': activeTab === 'privacy' }"
            @click="activeTab = 'privacy'"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            </svg>
            <span class="tab-label-text tab-label-full">{{ t('settings.tabs.privacy') }}</span>
            <span class="tab-label-text tab-label-short">{{ getTabLabelShort('privacy') }}</span>
          </button>
        </div>

        <!-- Body Content -->
        <div class="settings-body">
          
          <!-- TAB 1: PROFILE & ACCOUNT -->
          <div v-if="activeTab === 'account'" class="tab-pane">
            <div class="profile-hero-card">
              <div class="avatar-large">
                {{ (editFullName || userEmail || 'NS').slice(0, 2).toUpperCase() }}
              </div>
              <div class="hero-details">
                <h4 class="hero-name">{{ editFullName || t('settings.profile.defaultMusician') }}</h4>
                <p class="hero-meta">
                  <span class="hero-email">{{ userEmail }}</span> • 
                  <span class="role-badge">{{ editMusicalRole || t('settings.profile.defaultRole') }}</span>
                </p>
                <small class="member-since">{{ t('settings.profile.memberSince', { date: formatDate(userProfile?.created_at) }) }}</small>
              </div>
              <button
                type="button"
                class="hero-signout-btn"
                @click="handleSignOutFromSettings"
              >
                {{ t('nav.signOut') }}
              </button>
            </div>

            <div v-if="profileFeedback" class="feedback-banner" :class="profileFeedback.type">
              {{ profileFeedback.message }}
            </div>

            <div class="settings-form">
              <div class="form-row">
                <div class="form-group flex-1">
                  <label for="acc-name">{{ t('auth.fullName') }}</label>
                  <input id="acc-name" v-model="editFullName" type="text" :placeholder="t('settings.profile.fullNamePlaceholder')" />
                </div>
                <div class="form-group flex-1">
                  <label for="acc-bdate">{{ t('auth.birthdate') }}</label>
                  <input id="acc-bdate" v-model="editBirthdate" type="date" :min="minBirthdate" :max="maxBirthdate" />
                  <small class="field-hint">{{ t('auth.ageRequirement') }}</small>
                </div>
              </div>

              <div class="form-row">
                <div class="form-group flex-1">
                  <label for="acc-role">{{ t('settings.musicalRole') }}</label>
                  <select id="acc-role" v-model="editMusicalRole" class="setting-select">
                    <option v-for="role in roleOptions" :key="role" :value="role">{{ role }}</option>
                  </select>
                </div>
                <div class="form-group flex-1">
                  <label for="acc-country">{{ t('settings.countryRegion') }}</label>
                  <select id="acc-country" v-model="editCountry" class="setting-select">
                    <option v-for="c in ISO_COUNTRIES" :key="c.code" :value="c.code">
                      {{ c.code ? `${c.name} (${c.code})` : t('settings.selectCountry') }}
                    </option>
                  </select>
                </div>
              </div>

              <div class="form-group">
                <div class="label-with-counter">
                  <label for="acc-bio">{{ t('settings.bio') }}</label>
                  <span class="char-counter" :class="{ 'near-limit': editBio.length > 250 }">{{ editBio.length }} / 300</span>
                </div>
                <textarea id="acc-bio" v-model="editBio" maxlength="300" rows="3" :placeholder="t('settings.profile.bioPlaceholder')"></textarea>
              </div>

              <div class="form-actions">
                <button type="button" class="btn-save" :disabled="isSavingProfile" @click="handleSaveProfile">
                  <span v-if="isSavingProfile">{{ t('common.saving') }}</span>
                  <span v-else>{{ t('common.save') }}</span>
                </button>
              </div>
            </div>
          </div>

          <!-- TAB 2: SECURITY & TERMS -->
          <div v-if="activeTab === 'security'" class="tab-pane">
            <!-- Account Email & Verification Status -->
            <div class="settings-card">
              <div class="card-header-row">
                <span class="card-label">{{ t('settings.registeredEmail') }}</span>
                <span v-if="userProfile?.is_verified" class="verified-pill">✓ {{ t('common.verified') }}</span>
                <div v-else class="unverified-group">
                  <span class="unverified-pill">⚠️ {{ t('common.unverified') }}</span>
                  <button
                    type="button"
                    class="btn-resend-verify"
                    :disabled="isResendingVerification"
                    @click="handleResendVerification"
                  >
                    <span v-if="isResendingVerification">{{ t('common.saving') }}</span>
                    <span v-else>{{ t('settings.resendLink') }}</span>
                  </button>
                </div>
              </div>
              <p class="card-value">{{ userEmail }}</p>
              <div v-if="verificationFeedback" class="feedback-banner" :class="verificationFeedback.type" style="margin-top: 8px;">
                {{ verificationFeedback.message }}
              </div>
              <small class="card-note">{{ t('settings.security.primaryIdentity') }}<span v-if="userProfile?.oauth_provider"> {{ t('settings.security.connectedViaGoogle') }}</span></small>
            </div>

            <!-- Email Notification Preferences -->
            <div class="settings-card">
              <div class="card-header-row card-header-row-toggle">
                <div>
                  <span class="card-label">{{ t('settings.security.emailNotificationsTitle') }}</span>
                  <p class="card-desc" style="margin-top: 4px; margin-bottom: 0;">{{ t('settings.security.emailNotificationsDesc') }}</p>
                </div>
                <label class="toggle-switch">
                  <input
                    type="checkbox"
                    v-model="emailNotificationsEnabled"
                    @change="handleToggleEmailNotifications"
                  />
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>

            <!-- Password Change -->
            <div class="settings-card">
              <span class="card-label">{{ t('settings.security.changePassword') }}</span>
              <p class="card-desc">{{ t('settings.security.changePasswordDesc') }}</p>

              <div v-if="passwordFeedback" class="feedback-banner" :class="passwordFeedback.type">
                {{ passwordFeedback.message }}
              </div>

              <div class="password-form-grid">
                <div class="form-group">
                  <label for="cur-pwd">{{ t('settings.security.currentPassword') }}</label>
                  <input id="cur-pwd" v-model="currentPassword" type="password" placeholder="••••••••" />
                </div>
                <div class="form-group">
                  <label for="new-pwd">{{ t('settings.security.newPassword') }}</label>
                  <input id="new-pwd" v-model="newPassword" type="password" placeholder="••••••••" />
                  
                  <!-- Real-time Password Strength Meter -->
                  <div class="password-strength-box" v-if="newPassword">
                    <div class="strength-bar-track">
                      <div class="strength-bar-fill" :style="{ width: `${passwordStrength.percent}%`, backgroundColor: passwordStrength.color }"></div>
                    </div>
                    <div class="strength-status-row">
                      <span class="strength-label">{{ t('settings.security.passwordStrength') }} <strong :style="{ color: passwordStrength.color }">{{ passwordStrength.label }}</strong></span>
                      <span class="strength-hint">{{ t('settings.security.strengthHint') }}</span>
                    </div>
                  </div>
                  <small v-else class="field-hint">{{ t('settings.security.passwordRequirementHint') }}</small>
                </div>
                <div class="form-group">
                  <label for="conf-new-pwd">{{ t('settings.security.confirmNewPassword') }}</label>
                  <input id="conf-new-pwd" v-model="confirmNewPassword" type="password" placeholder="••••••••" />
                </div>
                <button type="button" class="btn-save" :disabled="isChangingPassword" @click="handleChangePassword">
                  <span v-if="isChangingPassword">{{ t('settings.security.updatingPassword') }}</span>
                  <span v-else>{{ t('settings.security.updatePasswordBtn') }}</span>
                </button>
              </div>
            </div>

            <!-- Two-Factor Authentication (2FA) -->
            <div class="settings-card">
              <div class="card-header-row card-header-row-toggle">
                <div>
                  <div class="badge-title-row">
                    <span class="card-label">{{ $t('settings.twoFactor.title') }}</span>
                    <span
                      class="preview-badge-pill"
                      :class="{ 'status-active': userProfile?.totp_enabled }"
                    >
                      {{ userProfile?.totp_enabled ? $t('settings.twoFactor.active') : $t('settings.twoFactor.disabled') }}
                    </span>
                  </div>
                  <p class="card-desc">{{ $t('settings.twoFactor.desc') }}</p>
                </div>
                <label class="toggle-switch">
                  <input
                    type="checkbox"
                    :checked="userProfile?.totp_enabled || false"
                    :disabled="isSettingUpTotp || isDisablingTotp"
                    @change="handleToggle2FA"
                  />
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>

            <!-- Legal Terms Compliance Audit -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ $t('settings.legal.title') }}</span>
                  <p class="card-desc">{{ $t('settings.legal.desc') }}</p>
                </div>
                <button type="button" class="btn-secondary" @click="showTermsModal = true">
                  {{ $t('settings.legal.viewTerms') }}
                </button>
              </div>
              <div class="legal-audit-badge">
                <div class="audit-row">
                  <span class="audit-title">{{ $t('settings.legal.version') }}</span>
                  <span class="audit-val">{{ userProfile?.terms_version || '2026.1-copyright' }}</span>
                </div>
                <div class="audit-row">
                  <span class="audit-title">{{ $t('settings.legal.acceptedOn') }}</span>
                  <span class="audit-val">{{ formatDate(userProfile?.terms_accepted_at) }}</span>
                </div>
                <div class="audit-row">
                  <span class="audit-title">{{ t('settings.legal.complianceStatus') }}</span>
                  <span class="audit-val status-ok">{{ t('settings.legal.activeVerified') }}</span>
                </div>
              </div>
            </div>

            <!-- Support & Contact -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.security.supportTitle') }}</span>
                  <p class="card-desc">{{ t('settings.security.supportDesc') }}</p>
                </div>
                <span class="btn-secondary" style="display: inline-flex; align-items: center; gap: 6px;">
                  {{ t('settings.security.contactTeam') }}
                </span>
              </div>
              <small class="card-note">{{ t('settings.security.directResponse') }}</small>
            </div>
          </div>

          <!-- TAB 3: BILLING -->
          <div v-if="activeTab === 'billing'" class="tab-pane">
            <!-- Account Quota & Usage Meter Card -->
            <div class="settings-card quota-summary-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.quotaSection.title') }}</span>
                  <p class="card-desc">{{ t('settings.quotaSection.subtitle') }}</p>
                </div>
                <span class="quota-tier-tag" :class="userQuota?.tier || 'starter'">
                  {{ userQuota?.tier_name || t('settings.quotaSection.starterPlan') }}
                </span>
              </div>
              <div class="quota-bars-grid">
                <div class="quota-meter-item">
                  <div class="meter-info">
                    <span class="meter-name">{{ t('settings.quotaSection.monthlyPages') }}</span>
                    <span class="meter-numbers">{{ t('settings.quotaSection.pagesCount', { used: userQuota?.pages?.processed_this_month || 0, limit: userQuota?.pages?.monthly_limit || 20 }) }}</span>
                  </div>
                  <div class="meter-track">
                    <div class="meter-fill" :style="{ width: `${pageUsagePercent}%` }" :class="{ 'near-cap': pageUsagePercent > 80 }"></div>
                  </div>
                </div>
                <div class="quota-meter-item">
                  <div class="meter-info">
                    <span class="meter-name">{{ t('settings.quotaSection.cloudStorage') }}</span>
                    <span class="meter-numbers">{{ t('settings.quotaSection.storageCount', { used: userQuota?.storage?.used_mb || 0, limit: userQuota?.storage?.limit_mb || 100 }) }}</span>
                  </div>
                  <div class="meter-track">
                    <div class="meter-fill" :style="{ width: `${storageUsagePercent}%` }" :class="{ 'near-cap': storageUsagePercent > 80 }"></div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Plan Overview Card -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.quotaSection.currentPlan') }}</span>
                  <div class="tier-pill-row">
                    <span class="plan-badge-tag" :class="userQuota?.tier || 'starter'">
                      {{ userQuota?.tier_name || t('settings.quotaSection.starterPlan') }}
                    </span>
                    <span class="plan-price-label">
                      {{ userQuota?.tier === 'starter' ? t('auth.freeForever') : t('settings.quotaSection.paidSubscription') }}
                    </span>
                  </div>
                </div>
                <button type="button" class="btn-primary" @click="isPlanModalOpen = true; emit('close')">
                  {{ t('settings.quotaSection.changePlan') }}
                </button>
              </div>

              <!-- Scheduled Downgrade Notice in Settings -->
              <div v-if="userQuota?.subscription?.cancel_at_period_end || billingStatus?.subscription?.cancel_at_period_end" class="settings-downgrade-notice">
                <div class="downgrade-notice-text">
                  <strong class="downgrade-notice-title">ℹ️ {{ t('plans.downgradeScheduled') }}</strong>
                  <p class="downgrade-notice-desc">
                    {{ t('plans.downgradeScheduledBanner', {
                      target: (userQuota?.subscription?.pending_tier || billingStatus?.subscription?.pending_tier || 'starter').toUpperCase(),
                      date: formatSettingsDate(userQuota?.subscription?.current_period_end || billingStatus?.subscription?.current_period_end),
                      current: userQuota?.tier_name || 'Virtuoso'
                    }) }}
                  </p>
                </div>
                <button type="button" class="btn-resume-plan" :disabled="isResumingInSettings" @click="handleResumeInSettings">
                  <span v-if="isResumingInSettings">{{ t('plans.resuming') }}</span>
                  <span v-else>{{ t('plans.resumeSubscription') }}</span>
                </button>
              </div>

              <!-- Stripe Customer Portal link if active -->
              <div v-if="billingStatus?.has_active_subscription || billingStatus?.stripe_customer_id" class="stripe-portal-group">
                <p class="card-desc">{{ t('settings.quotaSection.manageStripe') }}</p>
                <button type="button" class="btn-secondary" :disabled="isOpeningPortal" @click="handleOpenStripePortal">
                  <span v-if="isOpeningPortal">{{ t('settings.quotaSection.connectingStripe') }}</span>
                  <span v-else>{{ t('settings.quotaSection.openStripePortal') }}</span>
                </button>
              </div>
            </div>

            <!-- Invoicing & Billing Contact Details Form -->
            <div class="settings-card">
              <span class="card-label">{{ t('settings.quotaSection.invoiceDetails') }}</span>
              <p class="card-desc">{{ t('settings.quotaSection.invoiceDetailsDesc') }}</p>

              <div v-if="billingFeedback" class="feedback-banner" :class="billingFeedback.type">
                {{ billingFeedback.message }}
              </div>

              <div class="settings-form">
                <div class="form-row">
                  <div class="form-group flex-1">
                    <label for="bill-name">{{ t('settings.quotaSection.billingName') }}</label>
                    <input id="bill-name" v-model="editBillingName" type="text" :placeholder="t('settings.quotaSection.billingNamePlaceholder')" />
                  </div>
                  <div class="form-group flex-1">
                    <label for="bill-email">{{ t('settings.quotaSection.invoiceEmail') }}</label>
                    <input id="bill-email" v-model="editBillingEmail" type="email" :placeholder="t('settings.quotaSection.invoiceEmailPlaceholder')" />
                  </div>
                </div>

                <div class="form-group">
                  <label for="bill-country">{{ t('settings.quotaSection.taxJurisdiction') }}</label>
                  <select id="bill-country" v-model="editBillingCountry" class="setting-select">
                    <option v-for="c in ISO_COUNTRIES" :key="c.code" :value="c.code">
                      {{ c.code ? `${c.name} (${c.code})` : t('settings.selectCountry') }}
                    </option>
                  </select>
                </div>

                <div class="form-actions">
                  <button type="button" class="btn-save" :disabled="isSavingBilling" @click="handleSaveOptionalBilling">
                    <span v-if="isSavingBilling">{{ t('common.saving') }}</span>
                    <span v-else>{{ t('settings.quotaSection.saveBillingDetails') }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 4: STUDIO PREFERENCES -->
          <div v-if="activeTab === 'preferences'" class="tab-pane">
            <!-- Language & Localization -->
            <div class="settings-section">
              <label class="section-label">{{ t('settings.language.title') }}</label>
              <p class="section-desc">{{ t('settings.language.description') }}</p>
              
              <div class="setting-item">
                <span class="setting-item-label">{{ t('settings.language.selectLabel') }}</span>
                <select :value="currentLocale" @change="setLocale(($event.target as HTMLSelectElement).value as SupportedLocale)" class="setting-select">
                  <option v-for="loc in SUPPORTED_LOCALES" :key="loc.code" :value="loc.code">
                    {{ loc.flag }} {{ loc.native }} ({{ loc.label }})
                  </option>
                </select>
              </div>
            </div>

            <!-- Studio Color / Theme -->
            <div class="settings-section">
              <label class="section-label">{{ t('settings.theme.title') }}</label>
              <p class="section-desc">{{ t('settings.theme.description') }}</p>
              
              <div class="theme-choice-grid">
                <!-- System Auto -->
                <button 
                  type="button"
                  class="theme-choice-card"
                  :class="{ 'selected': preferences.theme === 'system' }"
                  @click="setTheme('system')"
                >
                  <div class="theme-preview system-preview">
                    <div class="preview-header"></div>
                    <div class="preview-content">
                      <div class="preview-line w-full"></div>
                      <div class="preview-line w-2-3"></div>
                    </div>
                  </div>
                  <div class="theme-choice-info">
                    <svg class="choice-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
                      <line x1="8" y1="21" x2="16" y2="21"></line>
                      <line x1="12" y1="17" x2="12" y2="21"></line>
                    </svg>
                    <span class="choice-name">{{ t('settings.theme.system') }}</span>
                  </div>
                </button>

                <!-- Dark Studio -->
                <button 
                  type="button"
                  class="theme-choice-card"
                  :class="{ 'selected': preferences.theme === 'dark' }"
                  @click="setTheme('dark')"
                >
                  <div class="theme-preview dark-preview">
                    <div class="preview-header"></div>
                    <div class="preview-content">
                      <div class="preview-line w-full"></div>
                      <div class="preview-line w-2-3"></div>
                    </div>
                  </div>
                  <div class="theme-choice-info">
                    <svg class="choice-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                    </svg>
                    <span class="choice-name">{{ t('settings.theme.dark') }}</span>
                  </div>
                </button>

                <!-- Clean Light -->
                <button 
                  type="button"
                  class="theme-choice-card"
                  :class="{ 'selected': preferences.theme === 'light' }"
                  @click="setTheme('light')"
                >
                  <div class="theme-preview light-preview">
                    <div class="preview-header"></div>
                    <div class="preview-content">
                      <div class="preview-line w-full"></div>
                      <div class="preview-line w-2-3"></div>
                    </div>
                  </div>
                  <div class="theme-choice-info">
                    <svg class="choice-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <circle cx="12" cy="12" r="5"></circle>
                      <line x1="12" y1="1" x2="12" y2="3"></line>
                      <line x1="12" y1="21" x2="12" y2="23"></line>
                      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                      <line x1="1" y1="12" x2="3" y2="12"></line>
                      <line x1="21" y1="12" x2="23" y2="12"></line>
                      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                    </svg>
                    <span class="choice-name">{{ t('settings.theme.cleanLight') }}</span>
                  </div>
                </button>

                <!-- Classical Parchment -->
                <button 
                  type="button"
                  class="theme-choice-card"
                  :class="{ 'selected': preferences.theme === 'parchment' }"
                  @click="setTheme('parchment')"
                >
                  <div class="theme-preview parchment-preview">
                    <div class="preview-header"></div>
                    <div class="preview-content">
                      <div class="preview-line w-full"></div>
                      <div class="preview-line w-2-3"></div>
                    </div>
                  </div>
                  <div class="theme-choice-info">
                    <svg class="choice-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
                    </svg>
                    <span class="choice-name">{{ t('settings.theme.parchment') }}</span>
                  </div>
                </button>

                <!-- High Contrast -->
                <button 
                  type="button"
                  class="theme-choice-card"
                  :class="{ 'selected': preferences.theme === 'high-contrast' }"
                  @click="setTheme('high-contrast')"
                >
                  <div class="theme-preview contrast-preview">
                    <div class="preview-header"></div>
                    <div class="preview-content">
                      <div class="preview-line w-full"></div>
                      <div class="preview-line w-2-3"></div>
                    </div>
                  </div>
                  <div class="theme-choice-info">
                    <svg class="choice-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <circle cx="12" cy="12" r="10"></circle>
                      <path d="M12 2a10 10 0 0 1 0 20z" fill="currentColor"></path>
                    </svg>
                    <span class="choice-name">{{ t('settings.theme.highContrast') }}</span>
                  </div>
                </button>
              </div>
            </div>

            <!-- Audio Timbre -->
            <div class="settings-section">
              <label class="section-label">{{ t('settings.playbackSection.title') }}</label>
              <div class="setting-item">
                <span class="setting-item-label">{{ t('settings.playbackSection.defaultInstrument') }}</span>
                <select v-model="preferences.defaultInstrument" class="setting-select">
                  <option v-for="inst in INSTRUMENT_OPTIONS" :key="inst.id" :value="inst.id">
                    {{ inst.name }}
                  </option>
                </select>
              </div>

              <div class="setting-item">
                <div class="setting-item-text">
                  <span class="setting-item-label">{{ t('settings.playbackSection.defaultTempo') }}</span>
                  <span class="setting-item-hint">{{ t('settings.playbackSection.tempoHint') }}</span>
                </div>
                <div class="bpm-slider-row">
                  <input 
                    type="range" 
                    min="40" 
                    max="220" 
                    step="5" 
                    v-model.number="preferences.defaultBpm" 
                    class="bpm-slider" 
                  />
                  <span class="bpm-number">{{ preferences.defaultBpm }} BPM</span>
                </div>
              </div>

              <div class="setting-item toggle-item">
                <div class="setting-item-text">
                  <span class="setting-item-label">{{ t('settings.playbackSection.autoFollowCursor') }}</span>
                  <span class="setting-item-hint">{{ t('settings.playbackSection.autoFollowHint') }}</span>
                </div>
                <label class="toggle-switch">
                  <input type="checkbox" v-model="preferences.autoFollowCursor" />
                  <span class="toggle-slider"></span>
                </label>
              </div>

              <div class="setting-item toggle-item">
                <div class="setting-item-text">
                  <span class="setting-item-label">{{ t('settings.playbackSection.metronomeCountIn') }}</span>
                  <span class="setting-item-hint">{{ t('settings.playbackSection.countInHint') }}</span>
                </div>
                <label class="toggle-switch">
                  <input type="checkbox" v-model="preferences.metronomeCountIn" />
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>

            <!-- Notation Scaling -->
            <div class="settings-section">
              <label class="section-label">{{ t('settings.viewSection.title') }}</label>
              <div class="setting-item">
                <span class="setting-item-label">{{ t('settings.viewSection.defaultZoom') }}</span>
                <select v-model.number="preferences.defaultZoom" class="setting-select">
                  <option :value="75">75%</option>
                  <option :value="100">100%</option>
                  <option :value="125">125%</option>
                  <option :value="150">150%</option>
                </select>
              </div>
            </div>
          </div>

          <!-- TAB 5: PRIVACY & COOKIES -->
          <div v-if="activeTab === 'privacy'" class="tab-pane">
            <!-- In-Tab Cookie Consent Controls -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.privacy.cookieCategoriesTitle') }}</span>
                  <p class="card-desc">{{ t('settings.privacy.cookieCategoriesDesc') }}</p>
                </div>
                <button type="button" class="btn-save" @click="handleUpdateCookies">
                  {{ t('cookies.savePreferences') }}
                </button>
              </div>

              <div v-if="cookieFeedback" class="feedback-banner success">
                {{ cookieFeedback }}
              </div>

              <div class="cookie-category-list">
                <div class="cookie-category-item">
                  <div class="category-meta">
                    <span class="category-title">{{ t('cookies.strictlyNecessary') }}</span>
                    <span class="category-desc">{{ t('cookies.strictlyNecessaryDesc') }}</span>
                  </div>
                  <span class="locked-badge">{{ t('cookies.alwaysActive') }}</span>
                </div>

                <div class="cookie-category-item">
                  <div class="category-meta">
                    <span class="category-title">{{ t('cookies.functional') }}</span>
                    <span class="category-desc">{{ t('cookies.functionalDesc') }}</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" v-model="functionalCookie" />
                    <span class="toggle-slider"></span>
                  </label>
                </div>

                <div class="cookie-category-item">
                  <div class="category-meta">
                    <span class="category-title">{{ t('cookies.analytics') }}</span>
                    <span class="category-desc">{{ t('cookies.analyticsDesc') }}</span>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" v-model="analyticsCookie" />
                    <span class="toggle-slider"></span>
                  </label>
                </div>
              </div>
            </div>

            <!-- Continuous OMR Active Learning Telemetry (Track P7) -->
            <div class="settings-card">
              <div class="card-header-row card-header-row-toggle">
                <div>
                  <span class="card-label">{{ t('settings.privacy.omrTelemetryTitle') }}</span>
                  <p class="card-desc">{{ t('settings.privacy.omrTelemetryDesc') }}</p>
                </div>
                <label class="toggle-switch">
                  <input
                    type="checkbox"
                    v-model="allowOmrTelemetry"
                    :disabled="isUpdatingTelemetry"
                    @change="handleToggleOmrTelemetry"
                  />
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>

            <!-- GDPR Self-Service Portability -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.privacy.gdprTitle') }}</span>
                  <p class="card-desc">{{ t('settings.privacy.gdprDesc') }}</p>
                </div>
                <button type="button" class="btn-secondary" @click="handleExportAccountData">
                  {{ t('settings.privacy.exportDataBtn') }}
                </button>
              </div>
            </div>

            <!-- Reset Defaults Card -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.privacy.resetDefaultsTitle') }}</span>
                  <p class="card-desc">{{ t('settings.privacy.resetDefaultsDesc') }}</p>
                </div>
                <button type="button" class="btn-secondary" @click="handleReset">
                  {{ t('settings.privacy.resetDefaultsBtn') }}
                </button>
              </div>
            </div>

            <!-- Open-Source Attribution & AGPL-3.0 Notice (Track P15) -->
            <div class="settings-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label">{{ t('settings.privacy.openSourceTitle') }}</span>
                  <p class="card-desc">{{ t('settings.privacy.openSourceDesc') }}</p>
                </div>
                <a
                  href="https://github.com/jbernax/notesight-omr-engine"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn-secondary"
                  style="text-decoration: none; white-space: nowrap;"
                >
                  {{ t('settings.privacy.omrEngineSourceBtn') }}
                </a>
              </div>
            </div>

            <!-- Danger Zone -->
            <div class="settings-card danger-card">
              <div class="card-header-row">
                <div>
                  <span class="card-label text-danger">{{ t('settings.privacy.deleteAccountTitle') }}</span>
                  <p class="card-desc">{{ t('settings.privacy.deleteAccountDesc') }}</p>
                </div>
                <button v-if="!showDeleteConfirm" type="button" class="btn-secondary danger" @click="showDeleteConfirm = true">
                  {{ t('settings.privacy.deleteAccountBtn') }}
                </button>
              </div>
              <div v-if="showDeleteConfirm" class="mt-4 p-4 border border-rose-500/30 rounded-lg bg-rose-500/10 space-y-3">
                <p class="text-xs text-rose-300 font-medium">{{ t('settings.privacy.deleteAccountConfirmPrompt') }}</p>
                <div v-if="!userProfile?.oauth_provider">
                  <label class="block text-xs text-slate-300 mb-1">{{ t('settings.privacy.enterPasswordConfirm') }}</label>
                  <input type="password" v-model="deleteAccountPassword" class="form-input text-xs" :placeholder="t('settings.privacy.passwordPlaceholder')" />
                </div>
                <div class="flex gap-2">
                  <button type="button" class="btn-secondary danger" :disabled="isDeletingAccount" @click="handleDeleteAccount">
                    {{ isDeletingAccount ? t('settings.privacy.deleting') : t('settings.privacy.confirmPermanentDeleteBtn') }}
                  </button>
                  <button type="button" class="btn-secondary" @click="showDeleteConfirm = false; deleteAccountPassword = ''">
                    {{ t('common.cancel') }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>


        <!-- Footer -->
        <div class="settings-footer">
          <span class="auto-save-hint">✓ {{ t('settings.autoSavedHint') }}</span>
          <button class="settings-done-btn" @click="emit('close')">{{ t('common.done') }}</button>
        </div>
      </div>
    </div>

    <!-- 2FA Setup Modal Dialog -->
    <div v-if="showTotpSetupModal" class="totp-dialog-backdrop" @click.self="showTotpSetupModal = false">
      <div class="totp-dialog-card">
        <div class="totp-dialog-header">
          <div class="totp-dialog-icon">
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <h3>{{ $t('settings.twoFactor.setupTitle') }}</h3>
          <p class="card-desc">{{ $t('settings.twoFactor.setupDesc') }}</p>
        </div>

        <div class="totp-dialog-body" v-if="totpSetupData">
          <div class="totp-secret-block">
            <label class="block-label">{{ $t('settings.twoFactor.secretKey') }}</label>
            <div class="secret-key-display">
              <code>{{ totpSetupData.secret }}</code>
              <button type="button" class="btn-copy" @click="copySecret">
                {{ copiedSecret ? $t('settings.twoFactor.copied') : $t('settings.twoFactor.copyKey') }}
              </button>
            </div>
          </div>

          <div class="totp-backup-block">
            <div class="backup-header-row">
              <label class="block-label">{{ $t('settings.twoFactor.backupCodes') }}</label>
              <button type="button" class="btn-copy-small" @click="copyBackupCodes">
                {{ copiedBackupCodes ? $t('settings.twoFactor.copiedCodes') : $t('settings.twoFactor.copyAllCodes') }}
              </button>
            </div>
            <p class="backup-hint">{{ $t('settings.twoFactor.backupHint') }}</p>
            <div class="backup-codes-grid">
              <span v-for="code in totpSetupData.backup_codes" :key="code" class="backup-code-pill">
                {{ code }}
              </span>
            </div>
          </div>

          <div class="totp-verify-block">
            <label class="block-label" for="totpVerifyInput">{{ $t('settings.twoFactor.enterCode') }}</label>
            <input
              id="totpVerifyInput"
              v-model="totpVerifyCode"
              type="text"
              maxlength="8"
              placeholder="000000"
              class="totp-dialog-input"
              @keyup.enter="confirmTotpVerify"
            />
          </div>
        </div>

        <div class="totp-dialog-footer">
          <button type="button" class="btn-secondary" @click="showTotpSetupModal = false">
            {{ $t('common.cancel') }}
          </button>
          <button
            type="button"
            class="btn-save"
            :disabled="isVerifyingTotp || !totpVerifyCode.trim()"
            @click="confirmTotpVerify"
          >
            <span v-if="isVerifyingTotp">{{ $t('settings.twoFactor.activating') }}</span>
            <span v-else>{{ $t('settings.twoFactor.verifyAndEnable') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 2FA Disable Modal Dialog -->
    <div v-if="showTotpDisableModal" class="totp-dialog-backdrop" @click.self="showTotpDisableModal = false">
      <div class="totp-dialog-card disable-card">
        <div class="totp-dialog-header">
          <div class="totp-dialog-icon warning">
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <h3>{{ $t('settings.twoFactor.disableTitle') }}</h3>
          <p class="card-desc">{{ $t('settings.twoFactor.disableDesc') }}</p>
        </div>

        <div class="totp-dialog-body">
          <div class="form-group">
            <label for="disable2faPwd">{{ $t('settings.twoFactor.accountPassword') }}</label>
            <input
              id="disable2faPwd"
              v-model="totpDisablePassword"
              type="password"
              placeholder="••••••••"
              class="totp-dialog-input"
              @keyup.enter="confirmTotpDisable"
            />
          </div>
        </div>

        <div class="totp-dialog-footer">
          <button type="button" class="btn-secondary" @click="showTotpDisableModal = false">
            {{ $t('common.cancel') }}
          </button>
          <button
            type="button"
            class="btn-secondary danger"
            :disabled="isDisablingTotp || !totpDisablePassword"
            @click="confirmTotpDisable"
          >
            <span v-if="isDisablingTotp">{{ $t('settings.twoFactor.disabling') }}</span>
            <span v-else>{{ $t('settings.twoFactor.confirmDisable') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Reusable Terms and Copyright Policy Modal -->
    <TermsModal
      :is-open="showTermsModal"
      @close="showTermsModal = false"
    />
  </teleport>
</template>

<style scoped>
.settings-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.68);
  backdrop-filter: blur(4px);
  z-index: 9500;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.settings-modal-card {
  background: var(--bg-card, #151b28);
  border: 1px solid var(--border, #28334a);
  border-radius: 16px;
  width: 100%;
  max-width: 680px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg, 0 25px 50px -12px rgba(0, 0, 0, 0.5));
  color: var(--text-primary, #e2e8f0);
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px 24px;
  border-bottom: 1px solid var(--border, #28334a);
}

.settings-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.settings-icon-wrapper {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--color-primary-light, rgba(37, 99, 235, 0.15));
  color: var(--color-primary, #3b82f6);
  display: flex;
  align-items: center;
  justify-content: center;
}

.settings-icon {
  width: 20px;
  height: 20px;
}

.settings-title {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}

.settings-subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary, #94a3b8);
  margin-top: 2px;
}

.settings-close-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #94a3b8);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.settings-close-btn:hover {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #fff);
}

/* Tabs */
.settings-nav-tabs {
  display: flex;
  padding: 8px 16px;
  gap: 6px;
  border-bottom: 1px solid var(--border, #28334a);
  background: var(--bg-subtle, rgba(0, 0, 0, 0.15));
  overflow-x: auto;
}

.tab-btn {
  background: transparent;
  border: none;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.84rem;
  font-weight: 600;
  color: var(--text-secondary, #94a3b8);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.tab-btn svg {
  width: 15px;
  height: 15px;
}

.tab-btn:hover {
  color: var(--text-primary, #fff);
  background: var(--bg-elevated, rgba(255, 255, 255, 0.06));
}

.tab-btn.active {
  color: var(--color-primary, #3b82f6);
  background: var(--color-primary-light, rgba(59, 130, 246, 0.12));
  font-weight: 700;
}

.tab-label-short {
  display: none;
}

.tab-label-full {
  display: inline;
}

/* Body */
.settings-body {
  padding: 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-pane {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* Cards & Components */
.profile-hero-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.03));
  border: 1px solid var(--border, #28334a);
  padding: 16px 20px;
  border-radius: 12px;
}

.avatar-large {
  width: 54px;
  height: 54px;
  min-width: 54px;
  min-height: 54px;
  flex-shrink: 0;
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #7c3aed);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  font-weight: 700;
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.3);
}

.hero-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.hero-name {
  font-size: 1.1rem;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}

.hero-meta {
  font-size: 0.84rem;
  color: var(--text-secondary, #94a3b8);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px 8px;
  flex-wrap: wrap;
}

.hero-email {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.role-badge {
  background: var(--color-primary-light, rgba(59, 130, 246, 0.15));
  color: var(--color-primary, #60a5fa);
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 0.76rem;
  font-weight: 600;
  flex-shrink: 0;
}

.member-since {
  font-size: 0.74rem;
  color: var(--text-muted, #64748b);
}

.hero-signout-btn {
  margin-left: auto;
  flex-shrink: 0;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.16));
  color: var(--text-secondary, #cbd5e1);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  min-height: 36px;
  transition: all 0.16s ease;
}

.hero-signout-btn:hover {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12));
  border-color: var(--color-danger, rgba(239, 68, 68, 0.35));
  color: var(--color-danger, #ef4444);
}

.settings-card {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.02));
  border: 1px solid var(--border, #28334a);
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-label {
  font-size: 0.94rem;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.card-desc {
  font-size: 0.82rem;
  color: var(--text-secondary, #94a3b8);
  margin: 0;
}

.card-value {
  font-size: 1.02rem;
  font-weight: 600;
  color: var(--text-primary, #fff);
  margin: 0;
}

.card-note {
  font-size: 0.76rem;
  color: var(--text-muted, #64748b);
}

.verified-pill {
  font-size: 0.72rem;
  background: var(--color-success-light, rgba(16, 185, 129, 0.15));
  color: var(--color-success, #10b981);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 9999px;
}

.unverified-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.unverified-pill {
  font-size: 0.72rem;
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 9999px;
}

.btn-resend-verify {
  font-size: 0.72rem;
  background: var(--bg-hover, #f1f5f9);
  color: var(--color-primary, #4f46e5);
  border: 1px solid var(--border, #cbd5e1);
  border-radius: 6px;
  padding: 2px 8px;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s ease;
}

.btn-resend-verify:hover:not(:disabled) {
  background: var(--color-primary-light, rgba(79, 70, 229, 0.1));
  border-color: var(--color-primary, #4f46e5);
}

.btn-resend-verify:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.feedback-banner {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.84rem;
  margin-bottom: 6px;
}

.feedback-banner.success {
  background: var(--color-success-light, rgba(16, 185, 129, 0.12));
  border: 1px solid var(--color-success, rgba(16, 185, 129, 0.3));
  color: var(--color-success, #34d399);
}

.feedback-banner.error {
  background: var(--color-danger-light, rgba(239, 68, 68, 0.12));
  border: 1px solid var(--color-danger, rgba(239, 68, 68, 0.3));
  color: var(--color-danger, #f87171);
}

/* Forms */
.settings-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
  gap: 5px;
}

.form-group label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-primary, #94a3b8);
}

.form-group input,
.form-group textarea,
.setting-select {
  background: var(--input-bg, rgba(0, 0, 0, 0.25));
  border: 1px solid var(--input-border, #28334a);
  border-radius: 8px;
  padding: 9px 12px;
  color: var(--text-primary, #fff);
  font-size: 0.88rem;
  outline: none;
  transition: border-color 0.15s ease;
}

.form-group input:focus,
.form-group textarea:focus,
.setting-select:focus {
  border-color: var(--border-focus, #3b82f6);
}

.field-hint {
  font-size: 0.72rem;
  color: var(--text-muted, #64748b);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

.password-form-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 6px;
}

/* Buttons */
.btn-save,
.btn-primary {
  background: var(--color-primary, #2563eb);
  color: white;
  border: none;
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.btn-save:hover,
.btn-primary:hover {
  background: var(--color-primary-hover, #1d4ed8);
}

.btn-save:disabled,
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, #374151);
  color: var(--text-primary, #e2e8f0);
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary:hover:not(:disabled) {
  background: var(--bg-elevated, rgba(255, 255, 255, 0.15));
  border-color: var(--border-focus, #4b5563);
  color: var(--text-primary);
}

.btn-secondary.danger:hover {
  border-color: var(--color-danger, #ef4444);
  color: var(--color-danger, #f87171);
}

/* Legal Audit */
.legal-audit-badge {
  background: var(--bg-subtle, rgba(0, 0, 0, 0.2));
  border: 1px solid var(--border, transparent);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 0.82rem;
}

.audit-row {
  display: flex;
  justify-content: space-between;
}

.audit-title {
  color: var(--text-secondary, #94a3b8);
}

.audit-val {
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
}

.status-ok {
  color: var(--color-success, #10b981);
}

/* Optional Billing */
.optional-notice-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--color-primary-light, rgba(59, 130, 246, 0.08));
  border: 1px solid var(--color-primary, rgba(59, 130, 246, 0.25));
  padding: 14px 16px;
  border-radius: 10px;
  font-size: 0.84rem;
  line-height: 1.45;
  color: var(--color-primary, #93c5fd);
}

.optional-notice-banner svg {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  margin-top: 1px;
}

.tier-pill-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.plan-badge-tag {
  font-size: 0.78rem;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
  text-transform: uppercase;
}

.plan-badge-tag.starter {
  background: rgba(148, 163, 184, 0.15);
  color: var(--text-secondary, #94a3b8);
}

.plan-badge-tag.pro {
  background: var(--color-primary-light, rgba(59, 130, 246, 0.2));
  color: var(--color-primary, #60a5fa);
}

.plan-badge-tag.virtuoso {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
}

.plan-badge-tag.maestro {
  background: var(--color-warning-light, rgba(245, 158, 11, 0.2));
  color: var(--color-warning, #fcd34d);
}

.plan-price-label {
  font-size: 0.84rem;
  color: var(--text-secondary, #94a3b8);
}

.stripe-portal-group {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.06));
}

.settings-downgrade-notice {
  margin-top: 14px;
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.25);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.downgrade-notice-text {
  flex: 1;
}

.downgrade-notice-title {
  font-size: 0.88rem;
  color: #c7d2fe;
  display: block;
  margin-bottom: 2px;
}

.downgrade-notice-desc {
  margin: 0;
  font-size: 0.82rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.4;
}

.btn-resume-plan {
  background: rgba(99, 102, 241, 0.2);
  border: 1px solid rgba(99, 102, 241, 0.45);
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 600;
  padding: 7px 14px;
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.btn-resume-plan:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.35);
  border-color: #818cf8;
}

.btn-resume-plan:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

@media (max-width: 640px) {
  .settings-downgrade-notice {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* Studio & Preferences Sections */
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
}

.section-label {
  font-size: 0.94rem;
  font-weight: 600;
  color: var(--text-primary, #fff);
  margin: 0;
}

.section-desc {
  font-size: 0.82rem;
  color: var(--text-secondary, #94a3b8);
  margin: 0;
}

.theme-choice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 12px;
}

.theme-choice-card {
  background: var(--bg-subtle, rgba(0, 0, 0, 0.2));
  border: 1px solid var(--border, #28334a);
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
  color: var(--text-primary);
  transition: all 0.15s ease;
}

.theme-choice-card.selected {
  border-color: var(--color-primary, #3b82f6);
  background: var(--color-primary-light, rgba(59, 130, 246, 0.08));
}

.theme-preview {
  height: 50px;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.system-preview {
  background: linear-gradient(135deg, #0f172a 50%, #f8fafc 50%);
}

.system-preview .preview-header {
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.4) 50%, rgba(0, 0, 0, 0.2) 50%);
  border-radius: 2px;
  height: 8px;
}

.system-preview .preview-line {
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.25) 50%, rgba(0, 0, 0, 0.15) 50%);
}

.dark-preview {
  background: #0f172a;
}

.light-preview {
  background: #f8fafc;
}

.parchment-preview {
  background: #f4ede0;
}

.parchment-preview .preview-header {
  background: rgba(124, 74, 30, 0.25);
  border-radius: 2px;
  height: 8px;
}

.parchment-preview .preview-line {
  background: rgba(124, 74, 30, 0.18);
}

.contrast-preview {
  background: #000000;
  border: 1px solid #ffffff;
}

.contrast-preview .preview-header {
  background: #38bdf8;
  border-radius: 2px;
  height: 8px;
}

.contrast-preview .preview-line {
  background: #ffffff;
}

.preview-header {
  height: 8px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
}

.light-preview .preview-header {
  background: rgba(0, 0, 0, 0.15);
}

.preview-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.preview-line {
  height: 6px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.1);
}

.light-preview .preview-line {
  background: rgba(0, 0, 0, 0.1);
}

.w-full { width: 100%; }
.w-2-3 { width: 66%; }

.theme-choice-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--text-primary);
}

.choice-icon {
  width: 16px;
  height: 16px;
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.setting-item-label {
  font-size: 0.88rem;
  font-weight: 500;
  color: var(--text-primary, #e2e8f0);
}

.setting-item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.setting-item-hint {
  font-size: 0.78rem;
  color: var(--text-secondary, #94a3b8);
}

.bpm-slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bpm-slider {
  width: 140px;
  accent-color: var(--color-primary, #3b82f6);
}

.bpm-number {
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 60px;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 44px;
  min-width: 44px;
  height: 24px;
  flex-shrink: 0;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-switch input:disabled + .toggle-slider {
  opacity: 0.5;
  cursor: not-allowed;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background-color: var(--input-border, #334155);
  transition: 0.2s;
  border-radius: 24px;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.2s;
  border-radius: 50%;
}

input:checked + .toggle-slider {
  background-color: var(--color-primary, #2563eb);
}

input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

.privacy-status-box {
  background: var(--bg-subtle, rgba(0, 0, 0, 0.2));
  border: 1px solid var(--border, transparent);
  border-radius: 8px;
  padding: 12px;
  font-size: 0.82rem;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.privacy-status-tag {
  color: var(--color-success, #10b981);
  font-weight: 600;
}

.privacy-status-note {
  color: var(--text-secondary, #94a3b8);
  margin: 0;
  line-height: 1.4;
}

/* Footer */
.settings-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  border-top: 1px solid var(--border, #28334a);
  background: var(--bg-subtle, rgba(0, 0, 0, 0.15));
}

.auto-save-hint {
  font-size: 0.78rem;
  color: var(--text-muted, #94a3b8);
}

.settings-done-btn {
  background: var(--color-primary, #2563eb);
  color: white;
  border: none;
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 0.86rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.settings-done-btn:hover {
  background: var(--color-primary-hover, #1d4ed8);
}

/* Label with character counter */
.label-with-counter {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.char-counter {
  font-size: 0.72rem;
  color: var(--text-secondary, #64748b);
  font-weight: 500;
}

.char-counter.near-limit {
  color: #f59e0b;
}

/* Password Strength Meter */
.password-strength-box {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.strength-bar-track {
  width: 100%;
  height: 4px;
  background: var(--border, #28334a);
  border-radius: 2px;
  overflow: hidden;
}

.strength-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.25s ease, background-color 0.25s ease;
}

.strength-status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.72rem;
}

.strength-label {
  color: var(--text-secondary, #94a3b8);
}

.strength-hint {
  color: var(--text-secondary, #64748b);
  font-size: 0.68rem;
}

/* Badge Title Row */
.badge-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-badge-pill {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 9999px;
  background: rgba(99, 102, 241, 0.15);
  color: #818cf8;
  border: 1px solid rgba(99, 102, 241, 0.3);
}

/* Quota Summary Card */
.quota-summary-card {
  background: linear-gradient(145deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%);
  border: 1px solid var(--border, #28334a);
}

.quota-tier-tag {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 3px 10px;
  border-radius: 6px;
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.quota-bars-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 14px;
}

.quota-meter-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meter-info {
  display: flex;
  justify-content: space-between;
  font-size: 0.78rem;
}

.meter-name {
  color: var(--text-secondary, #94a3b8);
  font-weight: 500;
}

.meter-numbers {
  color: var(--text-primary, #ffffff);
  font-weight: 600;
}

.meter-track {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
  overflow: hidden;
}

.meter-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #6366f1);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.meter-fill.near-cap {
  background: linear-gradient(90deg, #f59e0b, #ef4444);
}

/* In-Tab Cookie Category List */
.cookie-category-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 10px;
}

.cookie-category-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border, #28334a);
  border-radius: 8px;
}

.category-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.category-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-primary, #ffffff);
}

.category-desc {
  font-size: 0.74rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.35;
}

.locked-badge {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  color: #10b981;
  background: rgba(16, 185, 129, 0.12);
  padding: 3px 8px;
  border-radius: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Danger Card */
.danger-card {
  border-color: rgba(239, 68, 68, 0.25);
  background: rgba(239, 68, 68, 0.04);
}

.text-danger {
  color: #ef4444;
}

/* Responsive Modal Styles (Mobile & Tablet) */
@media (max-width: 640px) {
  .settings-modal-backdrop {
    padding: 0;
    align-items: stretch;
  }

  .settings-modal-card {
    width: 100%;
    height: 100%;
    max-height: 100dvh;
    border-radius: 0;
    border: none;
    box-shadow: none;
    padding-top: env(safe-area-inset-top, 0);
  }

  .settings-header {
    padding: 12px 16px;
    flex-shrink: 0;
  }

  .settings-icon-wrapper {
    width: 34px;
    height: 34px;
  }

  .settings-icon {
    width: 18px;
    height: 18px;
  }

  .settings-title {
    font-size: 1.05rem;
  }

  .settings-subtitle {
    display: none;
  }

  .settings-nav-tabs {
    padding: 6px 12px;
    gap: 4px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    flex-shrink: 0;
  }

  .settings-nav-tabs::-webkit-scrollbar {
    display: none;
  }

  .tab-btn {
    padding: 7px 10px;
    font-size: 0.78rem;
    min-height: 38px;
    gap: 5px;
    flex-shrink: 0;
  }

  .tab-btn svg {
    width: 14px;
    height: 14px;
  }

  .tab-btn-billing {
    display: none !important;
  }

  .tab-label-full {
    display: none;
  }

  .tab-label-short {
    display: inline;
  }

  .settings-body {
    padding: 16px 14px;
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .form-row {
    flex-direction: column;
    gap: 12px;
  }

  .profile-hero-card {
    padding: 14px 16px;
    gap: 12px;
  }

  .card-header-row {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .card-header-row.card-header-row-toggle,
  .card-header-row:has(.toggle-switch) {
    flex-direction: row;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .card-header-row.card-header-row-toggle > div:first-child,
  .card-header-row:has(.toggle-switch) > div:first-child {
    flex: 1;
    min-width: 0;
  }

  .settings-footer {
    padding: 12px 16px;
    padding-bottom: max(env(safe-area-inset-bottom, 0px), 14px);
    flex-shrink: 0;
  }

  .settings-done-btn {
    min-height: 42px;
    padding: 8px 22px;
  }

  .btn-save,
  .btn-primary,
  .btn-secondary {
    width: 100%;
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .theme-choice-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }

  .theme-choice-card {
    padding: 8px;
  }

  .theme-preview {
    height: 46px;
  }

  .totp-dialog-backdrop {
    padding: 12px;
  }

  .totp-dialog-card {
    padding: 16px;
    max-height: 95vh;
    overflow-y: auto;
  }
}

@media (min-width: 641px) and (max-width: 840px) {
  .settings-modal-card {
    max-width: min(680px, calc(100vw - 32px));
    max-height: 88vh;
  }

  .settings-nav-tabs {
    overflow-x: auto;
    scrollbar-width: none;
    gap: 4px;
  }

  .settings-nav-tabs::-webkit-scrollbar {
    display: none;
  }

  .tab-btn {
    padding: 8px 10px;
    font-size: 0.8rem;
  }

  .theme-choice-grid {
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }
}

.preview-badge-pill.status-active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.3);
}

.totp-dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(5px);
  z-index: 9600;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.15s ease;
}

.totp-dialog-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  width: 100%;
  max-width: 480px;
  padding: 24px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.totp-dialog-card.disable-card {
  max-width: 420px;
}

.totp-dialog-header {
  text-align: center;
}

.totp-dialog-icon {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.totp-dialog-icon.warning {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

.totp-dialog-header h3 {
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0 0 6px 0;
  color: var(--text-primary);
}

.totp-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.block-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
  display: block;
}

.secret-key-display {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
}

.secret-key-display code {
  font-family: monospace;
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-primary);
}

.btn-copy, .btn-copy-small {
  background: var(--color-primary);
  color: #ffffff;
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-copy-small {
  padding: 4px 8px;
  font-size: 0.75rem;
}

.backup-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.backup-hint {
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin: 4px 0 8px 0;
  line-height: 1.4;
}

.backup-codes-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  background: var(--bg-subtle);
  padding: 10px;
  border-radius: 8px;
  border: 1px dashed var(--border);
}

.backup-code-pill {
  font-family: monospace;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--bg-card);
  padding: 4px 6px;
  border-radius: 4px;
  text-align: center;
  border: 1px solid var(--border);
}

.totp-dialog-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  font-family: monospace;
  font-size: 1.25rem;
  letter-spacing: 0.2em;
  text-align: center;
  color: var(--text-primary);
}

.totp-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}
</style>
