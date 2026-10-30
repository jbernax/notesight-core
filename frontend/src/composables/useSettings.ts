import { ref, watch } from 'vue'
import type { InstrumentType } from '../audio/synth'
import { currentLocale, setLocale, type SupportedLocale } from '../i18n'
import { cookieConsent } from './useCookieConsent'
import { useNativePlatform } from './useNativePlatform'

export type AppTheme = 'system' | 'dark' | 'light' | 'parchment' | 'high-contrast' | 'stage-eink'

export interface UserPreferences {
  theme: AppTheme
  locale: SupportedLocale
  defaultInstrument: InstrumentType
  defaultBpm: number
  autoFollowCursor: boolean
  metronomeCountIn: boolean
  defaultZoom: number
}

export const DEFAULT_PREFERENCES: UserPreferences = {
  theme: 'dark',
  locale: 'en',
  defaultInstrument: 'piano',
  defaultBpm: 100,
  autoFollowCursor: true,
  metronomeCountIn: false,
  defaultZoom: 100,
}

const STORAGE_KEY = 'notesight_user_settings'

function loadPreferences(): UserPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return { ...DEFAULT_PREFERENCES, ...parsed }
    }
    // Backward compatibility for previous notesight_theme key
    const legacyTheme = localStorage.getItem('notesight_theme')
    if (legacyTheme === 'light') {
      return { ...DEFAULT_PREFERENCES, theme: 'light' }
    } else if (legacyTheme === 'parchment') {
      return { ...DEFAULT_PREFERENCES, theme: 'parchment' }
    } else if (legacyTheme === 'high-contrast') {
      return { ...DEFAULT_PREFERENCES, theme: 'high-contrast' }
    }
  } catch (err) {
    console.warn('Failed to parse saved user settings:', err)
  }
  return { ...DEFAULT_PREFERENCES }
}

// Reactive singleton preferences
export const preferences = ref<UserPreferences>(loadPreferences())

export function savePreferences(): void {
  try {
    if (cookieConsent.value && cookieConsent.value.functional === false) {
      return
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences.value))
    localStorage.setItem('notesight_theme', preferences.value.theme)
  } catch (err) {
    console.warn('Failed to save settings:', err)
  }
}

export function applyTheme(theme: AppTheme): void {
  const root = document.documentElement

  let effectiveTheme = theme
  if (theme === 'system') {
    const prefersLight = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
    effectiveTheme = prefersLight ? 'light' : 'dark'
  }

  const targetClass = effectiveTheme === 'dark' ? 'theme-dark' : `theme-${effectiveTheme}`
  if (!root.classList.contains(targetClass)) {
    root.classList.remove('theme-dark', 'theme-light', 'theme-parchment', 'theme-high-contrast', 'theme-stage-eink')
    root.classList.add(targetClass)
  }

  const { setStatusBarStyle } = useNativePlatform()

  if (effectiveTheme === 'light') {
    setStatusBarStyle(false, '#f8fafc')
  } else if (effectiveTheme === 'parchment') {
    setStatusBarStyle(false, '#f4ede0')
  } else if (effectiveTheme === 'high-contrast') {
    setStatusBarStyle(true, '#000000')
  } else if (effectiveTheme === 'stage-eink') {
    setStatusBarStyle(false, '#ffffff')
  } else {
    setStatusBarStyle(true, '#0c0f17')
  }
}

// System color scheme watcher
if (typeof window !== 'undefined' && window.matchMedia) {
  const mql = window.matchMedia('(prefers-color-scheme: light)')
  mql.addEventListener('change', () => {
    if (preferences.value.theme === 'system') {
      applyTheme('system')
    }
  })
}

export function resetPreferencesToDefaults(): void {
  preferences.value = { ...DEFAULT_PREFERENCES }
  savePreferences()
  applyTheme(preferences.value.theme)
  setLocale(preferences.value.locale)
}

// Keep preferences.locale synced with currentLocale
if (preferences.value.locale && preferences.value.locale !== currentLocale.value) {
  setLocale(preferences.value.locale)
}

watch(currentLocale, (newLoc) => {
  if (preferences.value.locale !== newLoc) {
    preferences.value.locale = newLoc
  }
})

// Watch changes and persist automatically
watch(preferences, (newVal) => {
  savePreferences()
  applyTheme(newVal.theme)
  if (newVal.locale && newVal.locale !== currentLocale.value) {
    setLocale(newVal.locale)
  }
}, { deep: true })

