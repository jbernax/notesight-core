import { ref } from 'vue'

export interface CookieConsentPreferences {
  essential: boolean // Strictly necessary: Auth session, CSRF security, Stripe payment fraud
  functional: boolean // Studio preferences: Theme, playback timbre, BPM, notation zoom
  analytics: boolean // Performance metrics: Anonymized latency and usage metrics
  timestamp: string
  version: number
}

const CONSENT_STORAGE_KEY = 'notesight_cookie_consent'
const CURRENT_POLICY_VERSION = 1

export const DEFAULT_CONSENT: CookieConsentPreferences = {
  essential: true,
  functional: true,
  analytics: false,
  timestamp: '',
  version: CURRENT_POLICY_VERSION,
}

// Global reactive states
export const cookieConsent = ref<CookieConsentPreferences | null>(null)
export const isBannerOpen = ref<boolean>(false)
export const isPreferencesModalOpen = ref<boolean>(false)

export function loadSavedConsent(): CookieConsentPreferences | null {
  try {
    const raw = localStorage.getItem(CONSENT_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as CookieConsentPreferences
      if (parsed.version === CURRENT_POLICY_VERSION) {
        return parsed
      }
    }
  } catch (err) {
    console.warn('Failed to parse saved cookie consent:', err)
  }
  return null
}

export function initCookieConsent(): void {
  const saved = loadSavedConsent()
  if (saved) {
    cookieConsent.value = saved
    isBannerOpen.value = false
  } else {
    cookieConsent.value = null
    isBannerOpen.value = true
  }
}

export function saveConsent(prefs: Partial<CookieConsentPreferences>): CookieConsentPreferences {
  const updated: CookieConsentPreferences = {
    essential: true, // Always locked to true
    functional: prefs.functional ?? true,
    analytics: prefs.analytics ?? false,
    timestamp: new Date().toISOString(),
    version: CURRENT_POLICY_VERSION,
  }

  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(updated))
  } catch (err) {
    console.error('Failed to persist cookie consent:', err)
  }

  cookieConsent.value = updated
  isBannerOpen.value = false
  isPreferencesModalOpen.value = false
  return updated
}

export function acceptAll(): void {
  saveConsent({ functional: true, analytics: true })
}

export function acceptEssentialOnly(): void {
  saveConsent({ functional: false, analytics: false })
}

export function openCookiePreferences(): void {
  isPreferencesModalOpen.value = true
}

export function closeCookiePreferences(): void {
  isPreferencesModalOpen.value = false
}
