<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, defineAsyncComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { preferences, applyTheme } from './composables/useSettings'
import { userQuota, fetchUserQuota, isPlanModalOpen } from './composables/useQuota'
import { apiFetch, clearAuthSession } from './services/apiClient'
import CookieAdviceBanner from './components/CookieAdviceBanner.vue'
import ToastNotification from './components/ToastNotification.vue'
import MobileNavBar from './components/mobile/MobileNavBar.vue'

const SettingsModal = defineAsyncComponent(() => import('./components/SettingsModal.vue'))
const PlanModal = defineAsyncComponent(() => import('./components/PlanModal.vue'))
const TermsModal = defineAsyncComponent(() => import('./components/TermsModal.vue'))
const CookiePreferencesModal = defineAsyncComponent(() => import('./components/CookiePreferencesModal.vue'))
import { t } from './i18n'
import { initCookieConsent } from './composables/useCookieConsent'
import { userProfile, fetchUserProfile } from './composables/useUserProfile'
import { useNativePlatform, isMobileImmersiveMode, mobileWorkspaceTab } from './composables/useNativePlatform'
import { showToast } from './composables/useToast'

const router = useRouter()
const route = useRoute()
const userEmail = ref<string | null>(null)
const isLoggedIn = ref<boolean>(false)
const isSettingsOpen = ref<boolean>(false)
const settingsInitialTab = ref<'account' | 'security' | 'billing' | 'preferences' | 'privacy'>('preferences')
const showFooterTerms = ref<boolean>(false)

// Mobile App Shell State
const { isMobile } = useNativePlatform()
const mobileActiveTab = ref<'library' | 'create' | 'settings'>('library')
const hasActiveScoreLoaded = ref<boolean>(false)

const isAuthOrEmbedRoute = computed(() => {
  const rName = String(route.name || '')
  return [
    'Login',
    'Register',
    'ForgotPassword',
    'ResetPassword',
    'VerifyEmail',
    'GoogleCallback',
    'ScoreEmbed',
  ].includes(rName)
})

const showMobileNav = computed(() => {
  return isMobile.value && isLoggedIn.value && !isAuthOrEmbedRoute.value && !isMobileImmersiveMode.value
})

const handleMobileTab = (tab: 'library' | 'create' | 'settings') => {
  mobileActiveTab.value = tab
  if (tab === 'settings') {
    openSettingsTab('account')
  } else if (tab === 'library' || tab === 'create') {
    mobileWorkspaceTab.value = tab
    isMobileImmersiveMode.value = false
    if (route.name !== 'Dashboard') {
      router.push({ name: 'Dashboard' }).then(() => {
        window.dispatchEvent(new CustomEvent('notesight:close-score'))
      })
    } else {
      window.dispatchEvent(new CustomEvent('notesight:close-score'))
    }
  }
}

watch(mobileWorkspaceTab, (newTab) => {
  if (!isSettingsOpen.value) {
    mobileActiveTab.value = newTab
  }
})

watch(isSettingsOpen, (open) => {
  if (open) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
  if (!open && mobileActiveTab.value === 'settings') {
    mobileActiveTab.value = mobileWorkspaceTab.value
  }
})

watch(isMobileImmersiveMode, (immersive) => {
  if (immersive) {
    hasActiveScoreLoaded.value = true
  }
})

const handleScoreStateEvent = (ev: Event) => {
  const customEv = ev as CustomEvent<{ hasScore?: boolean }>
  if (typeof customEv.detail?.hasScore === 'boolean') {
    hasActiveScoreLoaded.value = customEv.detail.hasScore
  }
}

const openSettingsTab = (tab: 'account' | 'security' | 'billing' | 'preferences' | 'privacy') => {
  settingsInitialTab.value = tab
  isSettingsOpen.value = true
}

const checkPendingGuestScoreClaim = async () => {
  const pending = sessionStorage.getItem('pendingGuestScore')
  const authToken = localStorage.getItem('token')
  if (pending && authToken) {
    try {
      const parsed = JSON.parse(pending)
      if (parsed.jobId && parsed.guestToken) {
        const res = await apiFetch(`/api/scores/guest/${parsed.jobId}/claim`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ guest_token: parsed.guestToken })
        })
        if (res.ok) {
          sessionStorage.removeItem('pendingGuestScore')
          showToast({
            title: 'Score Saved to Library!',
            message: `"${parsed.title || 'Your test score'}" was successfully saved to your Score Library.`,
            type: 'success',
            duration: 6000
          })
        }
      }
    } catch (e) {
      console.warn('Could not claim pending guest score:', e)
    }
  }
}

const checkAuth = () => {
  const token = localStorage.getItem('token')
  isLoggedIn.value = !!token
  userEmail.value = localStorage.getItem('user_email')
  if (isLoggedIn.value) {
    fetchUserQuota()
    fetchUserProfile()
    checkPendingGuestScoreClaim()
  }
}


onMounted(() => {
  window.addEventListener('notesight:auth-changed', checkAuth)
  window.addEventListener('notesight:score-state', handleScoreStateEvent)
  checkAuth()
  applyTheme(preferences.value.theme)
  if ('requestIdleCallback' in window) {
    (window as any).requestIdleCallback(() => initCookieConsent(), { timeout: 1500 })
  } else {
    setTimeout(() => initCookieConsent(), 500)
  }
})

onUnmounted(() => {
  window.removeEventListener('notesight:auth-changed', checkAuth)
  window.removeEventListener('notesight:score-state', handleScoreStateEvent)
})

watch(() => route.path, () => {
  checkAuth()
  if (route.name !== 'Dashboard') {
    isMobileImmersiveMode.value = false
  }
})

const handleLogout = async () => {
  try {
    await apiFetch('/api/logout', {
      method: 'POST',
    })
  } catch {
    // Ignore network errors to allow client sign out regardless of connectivity
  }
  clearAuthSession()
  checkAuth()
  router.push({ name: 'Login' })
}

const handleBrandClick = (e: MouseEvent) => {
  if (e.metaKey || e.ctrlKey) return
  e.preventDefault()
  isMobileImmersiveMode.value = false
  if (isLoggedIn.value) {
    if (route.name !== 'Dashboard') {
      router.push({ name: 'Dashboard' }).then(() => {
        window.dispatchEvent(new CustomEvent('notesight:close-score'))
      })
    } else {
      window.dispatchEvent(new CustomEvent('notesight:close-score'))
    }
  } else {
    if (route.name !== 'Home') {
      router.push({ name: 'Home' })
    }
  }
}
</script>

<template>
  <div class="app-layout" :class="{ 'is-mobile-immersive': isMobile && isMobileImmersiveMode, 'has-mobile-nav': showMobileNav }">
    <!-- Header -->
    <header v-if="!(isMobile && isMobileImmersiveMode)" class="app-header">
      <div class="header-content">
        <a href="/" class="brand-link" @click="handleBrandClick" title="Reload NoteSight">
          <div class="logo">
            <img src="/favicon.svg" alt="NoteSight Logo" class="brand-icon" width="36" height="36" />
            <div class="brand-text">
              <span class="brand-name">Note<span class="brand-name-accent">Sight</span></span>
              <span class="tagline">{{ t('nav.tagline') }}</span>
            </div>
          </div>
        </a>

        <div class="header-actions">
          <!-- Quota Indicator Pill -->
          <button 
            v-if="isLoggedIn && userQuota && route.name !== 'Home'" 
            class="quota-pill" 
            @click="isPlanModalOpen = true" 
            title="View Storage & Processing Quotas"
          >
            <span class="quota-tier-tag" :class="userQuota.tier">
              {{ userQuota.tier_name.split(' ')[0] }}
            </span>
            <span class="quota-usage-text">
              {{ userQuota.storage.used_mb }} / {{ userQuota.storage.limit_mb }} MB
            </span>
            <div class="quota-meter">
              <div 
                class="quota-meter-fill" 
                :style="{ width: `${userQuota.storage.percent_used}%` }"
                :class="{ 
                  'warn': userQuota.storage.percent_used > 80, 
                  'danger': userQuota.storage.percent_used > 95 
                }"
              ></div>
            </div>
            <span class="quota-upgrade-hint">{{ t('common.upgrade') }}</span>
          </button>

          <button 
            class="settings-btn" 
            @click="openSettingsTab('preferences')" 
            :title="t('settings.title')"
          >
            <svg class="settings-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
            </svg>
            <span class="settings-btn-text">{{ t('nav.settings') }}</span>
          </button>

          <div v-if="isLoggedIn" class="user-nav">
            <button 
              type="button"
              class="user-pill clickable" 
              @click="openSettingsTab('account')" 
              :title="t('nav.account')"
            >
              <span class="user-dot"></span>
              <span class="user-greeting">{{ userProfile?.full_name || userEmail || 'Musician' }}</span>
            </button>
            <button class="logout-btn" @click="handleLogout">{{ t('nav.signOut') }}</button>
          </div>
          <div v-else class="guest-nav">
            <router-link to="/login" class="nav-signin-link">{{ t('nav.signIn') || 'Sign In' }}</router-link>
            <router-link to="/register" class="nav-signup-btn">{{ t('landing.getStartedFree') }}</router-link>
          </div>
        </div>
      </div>
    </header>

    <main class="main-content">
      <router-view />
    </main>

    <footer v-if="!(isMobile && isMobileImmersiveMode)" class="app-footer">
      <div class="footer-content">
        <p>{{ t('nav.footerCopyright') }}</p>
        <div class="footer-links">
          <router-link to="/terms" class="footer-legal-btn">
            {{ t('nav.terms') }}
          </router-link>
          <span class="footer-sep">•</span>
          <router-link to="/privacy" class="footer-legal-btn">
            Privacy Policy
          </router-link>
        </div>
      </div>
    </footer>

    <!-- Studio Settings Modal -->
    <SettingsModal 
      :is-open="isSettingsOpen" 
      :user-email="userEmail" 
      :initial-tab="settingsInitialTab"
      @close="isSettingsOpen = false" 
    />

    <!-- Terms Modal -->
    <TermsModal
      :is-open="showFooterTerms"
      @close="showFooterTerms = false"
    />

    <!-- Subscription Plans & Quotas Modal -->
    <PlanModal 
      :is-open="isPlanModalOpen" 
      @close="isPlanModalOpen = false" 
    />

    <!-- Cookie & Storage Advice Components -->
    <CookieAdviceBanner />
    <CookiePreferencesModal />

    <!-- Application Toast Notification Viewport -->
    <ToastNotification />

    <!-- Mobile Bottom Navigation Bar (Visible on mobile screens when not in immersive score/auth mode) -->
    <MobileNavBar
      v-if="showMobileNav"
      :active-tab="mobileActiveTab"
      @select-tab="handleMobileTab"
    />
  </div>
</template>


<style scoped>
.app-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas, #faf8f5);
  color: var(--text-primary, #121624);
}

.app-header {
  min-height: var(--app-header-height, 65px);
  background: var(--bg-glass-heavy, var(--bg-card));
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  color: var(--text-primary, #ffffff);
  padding: calc(12px + var(--sat, 0px)) 28px 12px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  box-shadow: var(--shadow-sm, 0 4px 20px rgba(0, 0, 0, 0.2));
  transition: background-color 0.25s ease, border-color 0.25s ease;
  position: sticky;
  top: 0;
  z-index: 100;
  box-sizing: border-box;
}

.header-content {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.brand-link {
  text-decoration: none;
  color: inherit;
  display: inline-flex;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.brand-link:hover {
  opacity: 0.9;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.35);
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-name {
  font-size: 1.35rem;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: var(--text-primary, #ffffff);
  line-height: 1.15;
}

.brand-name-accent {
  color: var(--color-accent, #22d3ee);
  background: linear-gradient(135deg, var(--color-primary, #818cf8) 0%, var(--color-accent, #22d3ee) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.tagline {
  margin: 1px 0 0 0;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.76rem;
  letter-spacing: 0.2px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.quota-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.16));
  color: var(--text-primary, #f1f5f9);
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s ease;
  min-height: 40px;
}

.quota-pill:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.15));
  border-color: var(--color-primary, #6366f1);
  transform: translateY(-1px);
}

.quota-tier-tag {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 7px;
  border-radius: 10px;
  background: var(--color-primary-light, rgba(99, 102, 241, 0.2));
  color: var(--color-primary, #a5b4fc);
  border: 1px solid var(--color-primary, rgba(99, 102, 241, 0.3));
}

.quota-tier-tag.pro {
  background: var(--color-accent-light, rgba(34, 211, 238, 0.18));
  color: var(--color-accent, #67e8f9);
  border-color: var(--color-accent, rgba(34, 211, 238, 0.3));
}

.quota-tier-tag.virtuoso,
.quota-tier-tag.maestro {
  background: var(--color-warning-light, rgba(245, 158, 11, 0.2));
  color: var(--color-warning, #fcd34d);
  border-color: var(--color-warning, rgba(245, 158, 11, 0.35));
}

.quota-usage-text {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-secondary, #cbd5e1);
}

.quota-meter {
  width: 44px;
  height: 5px;
  background: var(--border, rgba(255, 255, 255, 0.15));
  border-radius: 3px;
  overflow: hidden;
}

.quota-meter-fill {
  height: 100%;
  background: var(--color-primary, #6366f1);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.quota-meter-fill.warn {
  background: var(--color-warning, #f59e0b);
}

.quota-meter-fill.danger {
  background: var(--color-danger, #ef4444);
}

.quota-upgrade-hint {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--color-primary, #818cf8);
  padding-left: 2px;
}

.settings-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.16));
  color: var(--text-primary, #f1f5f9);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  min-height: 40px;
}

.settings-btn:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.15));
  border-color: var(--color-primary, rgba(255, 255, 255, 0.3));
  transform: translateY(-1px);
}

.settings-btn-icon {
  width: 16px;
  height: 16px;
  stroke-width: 2.2;
  color: var(--color-primary, #818cf8);
}

.settings-btn-text {
  font-size: 0.8rem;
  letter-spacing: 0.2px;
}

.user-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.06));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  padding: 6px 12px;
  border-radius: 20px;
  min-height: 40px;
}

.user-pill.clickable {
  cursor: pointer;
  transition: all 0.2s ease;
}

.user-pill.clickable:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.12));
  border-color: var(--color-primary, rgba(59, 130, 246, 0.4));
  transform: translateY(-1px);
}

.user-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-success, #10b981);
  flex-shrink: 0;
}

.user-greeting {
  font-size: 0.85rem;
  color: var(--text-primary, #e2e8f0);
  font-weight: 500;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  background: var(--bg-subtle, rgba(255, 255, 255, 0.08));
  color: var(--text-secondary, #cbd5e1);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  min-height: 40px;
}

.logout-btn:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.15));
  color: var(--text-primary, #ffffff);
  border-color: var(--border, rgba(255, 255, 255, 0.3));
}

.guest-nav {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-signin-link {
  color: var(--text-secondary, #cbd5e1);
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.nav-signin-link:hover {
  color: var(--text-primary, #ffffff);
  background: var(--bg-hover, rgba(255, 255, 255, 0.08));
}

.nav-signup-btn {
  background: #4f46e5;
  color: #ffffff;
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 6px;
  transition: all 0.15s ease;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.4);
}

.nav-signup-btn:hover {
  background: #4338ca;
  transform: translateY(-1px);
}

.main-content {
  max-width: 1200px;
  margin: 24px auto;
  padding: 0 20px;
  width: 100%;
  flex: 1;
}

.main-content:has(.landing-page) {
  max-width: 100%;
  padding: 0;
  margin: 0;
}

.main-content:has(.is-wide-canvas) {
  max-width: 1720px;
  padding: 0 16px;
  margin: 12px auto;
}

.main-content:has(.is-studio-active) {
  max-width: 100%;
  padding: 0 8px;
  margin: 0 auto;
}

.app-layout:has(.is-studio-active) .app-footer {
  display: none;
}

.app-layout.is-mobile-immersive .main-content {
  margin: 0;
  padding: 0;
  max-width: 100%;
}

.app-footer {
  padding: 24px;
  color: var(--text-muted, #8b92a5);
  font-size: 0.85rem;
  border-top: 1px solid var(--border, #e6e2d8);
  margin-top: 48px;
}

.footer-content {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.footer-content p {
  margin: 0;
}

.footer-links {
  display: flex;
  align-items: center;
  gap: 12px;
}

.footer-sep {
  color: var(--text-muted, #8b92a5);
  font-size: 0.75rem;
}

.footer-legal-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--text-muted, #8b92a5);
  font-size: 0.82rem;
  cursor: pointer;
  text-decoration: underline;
  transition: color 0.15s ease;
}

.footer-legal-btn:hover {
  color: var(--text-main, #ffffff);
}

@media (max-width: 768px) {
  .app-layout.has-mobile-nav {
    padding-bottom: calc(var(--mobile-nav-height, 60px) + var(--sab, 0px) + 12px);
  }
  .tagline {
    display: none;
  }
  .app-header {
    padding: calc(8px + var(--sat, 0px)) 14px 8px;
  }
  .header-content {
    flex-direction: row;
    flex-wrap: nowrap;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .brand-icon {
    width: 32px;
    height: 32px;
  }
  .brand-name {
    font-size: 1.15rem;
  }
  .header-actions {
    width: auto;
    flex-wrap: nowrap;
    justify-content: flex-end;
    gap: 6px;
  }
  .quota-pill {
    padding: 4px 9px;
    font-size: 0.72rem;
    min-height: 38px;
  }
  .quota-meter,
  .quota-upgrade-hint,
  .quota-usage-text {
    display: none;
  }
  .settings-btn {
    width: 40px;
    height: 40px;
    padding: 0;
    border-radius: 50%;
  }
  .settings-btn-text {
    display: none;
  }
  .user-greeting {
    max-width: 84px;
    font-size: 0.78rem;
  }
  .user-pill {
    padding: 4px 10px;
    min-height: 38px;
  }
  .logout-btn {
    padding: 4px 10px;
    font-size: 0.76rem;
    min-height: 38px;
  }
  .main-content {
    padding: 0 12px;
    margin: 12px auto;
  }
}

@media (max-width: 640px) {
  .quota-pill {
    display: none !important;
  }
  .app-layout.has-mobile-nav .settings-btn,
  .app-layout.has-mobile-nav .user-nav,
  .app-layout.has-mobile-nav .app-footer {
    display: none;
  }
  .header-actions {
    gap: 4px;
  }
  .user-greeting {
    max-width: 68px;
  }
}
</style>
