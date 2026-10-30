import { ref, reactive, computed } from 'vue'
import { en, type TranslationSchema } from './locales/en'

export type SupportedLocale = 'en' | 'es' | 'fr' | 'it' | 'pt' | 'de' | 'ja' | 'zh' | 'ko' | 'nl' | 'pl' | 'ru'

export interface LocaleOption {
  code: SupportedLocale
  label: string
  native: string
  flag: string
}

export const SUPPORTED_LOCALES: LocaleOption[] = [
  { code: 'en', label: 'English', native: 'English', flag: '🇬🇧' },
  { code: 'es', label: 'Spanish', native: 'Español', flag: '🇪🇸' },
  { code: 'fr', label: 'French', native: 'Français', flag: '🇫🇷' },
  { code: 'it', label: 'Italian', native: 'Italiano', flag: '🇮🇹' },
  { code: 'pt', label: 'Portuguese', native: 'Português', flag: '🇵🇹' },
  { code: 'de', label: 'German', native: 'Deutsch', flag: '🇩🇪' },
  { code: 'ja', label: 'Japanese', native: '日本語', flag: '🇯🇵' },
  { code: 'zh', label: 'Chinese', native: '简体中文', flag: '🇨🇳' },
  { code: 'ko', label: 'Korean', native: '한국어', flag: '🇰🇷' },
  { code: 'nl', label: 'Dutch', native: 'Nederlands', flag: '🇳🇱' },
  { code: 'pl', label: 'Polish', native: 'Polski', flag: '🇵🇱' },
  { code: 'ru', label: 'Russian', native: 'Русский', flag: '🇷🇺' },
]

export const translations = reactive<Record<SupportedLocale, TranslationSchema>>({
  en,
  es: en,
  fr: en,
  it: en,
  pt: en,
  de: en,
  ja: en,
  zh: en,
  ko: en,
  nl: en,
  pl: en,
  ru: en,
})

const localeLoaders: Record<SupportedLocale, () => Promise<any>> = {
  en: async () => ({ default: en, en }),
  es: () => import('./locales/es'),
  fr: () => import('./locales/fr'),
  it: () => import('./locales/it'),
  pt: () => import('./locales/pt'),
  de: () => import('./locales/de'),
  ja: () => import('./locales/ja'),
  zh: () => import('./locales/zh'),
  ko: () => import('./locales/ko'),
  nl: () => import('./locales/nl'),
  pl: () => import('./locales/pl'),
  ru: () => import('./locales/ru'),
}

const loadedLocales = new Set<SupportedLocale>(['en'])

export async function loadLocale(locale: SupportedLocale): Promise<void> {
  if (loadedLocales.has(locale)) return
  try {
    const mod = await localeLoaders[locale]()
    const schema = (mod[locale] || mod.default) as TranslationSchema
    if (schema) {
      translations[locale] = schema
      loadedLocales.add(locale)
    }
  } catch (err) {
    console.warn(`[i18n] Failed to load locale "${locale}":`, err)
  }
}

const STORAGE_KEY = 'notesight_locale'

function detectInitialLocale(): SupportedLocale {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      const saved = window.localStorage.getItem(STORAGE_KEY)
      if (saved && saved in translations) {
        return saved as SupportedLocale
      }
    }
    // Check browser languages
    const browserLang = typeof navigator !== 'undefined' ? (navigator.language || '').toLowerCase().split('-')[0] : 'en'
    if (browserLang in translations) {
      return browserLang as SupportedLocale
    }
  } catch (err) {
    console.warn('Failed to detect locale:', err)
  }
  return 'en'
}

const initial = detectInitialLocale()
export const currentLocale = ref<SupportedLocale>(initial)
export const isLocaleReady = ref<boolean>(initial === 'en')

if (initial !== 'en') {
  loadLocale(initial).then(() => {
    isLocaleReady.value = true
    currentLocale.value = initial
    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.setAttribute('lang', initial)
    }
  })
}

export async function setLocale(locale: SupportedLocale): Promise<void> {
  if (locale in translations) {
    if (!loadedLocales.has(locale)) {
      await loadLocale(locale)
    }
    currentLocale.value = locale
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.setItem(STORAGE_KEY, locale)
      }
      if (typeof document !== 'undefined' && document.documentElement) {
        document.documentElement.setAttribute('lang', locale)
      }
    } catch (err) {
      console.warn('Failed to save locale preference:', err)
    }
  }
}

/**
 * Helper to get nested value from object by dot notation path
 */
function getNestedValue(obj: any, path: string): any {
  if (!obj) return undefined
  const parts = path.split('.')
  let current = obj
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part]
    } else {
      return undefined
    }
  }
  return current
}

/**
 * Translate a key path with optional parameter substitution
 * e.g. t('dashboard.processingCount', { count: 3 })
 */
export function t(key: string, params?: Record<string, string | number>): string {
  const dict = translations[currentLocale.value] || translations.en
  let value = getNestedValue(dict, key)

  // Fallback to English if missing
  if (value === undefined && currentLocale.value !== 'en') {
    value = getNestedValue(translations.en, key)
  }

  if (value === undefined) {
    return key
  }

  let str = String(value)
  if (params) {
    for (const [pKey, pVal] of Object.entries(params)) {
      str = str.replace(new RegExp(`\\{${pKey}\\}`, 'g'), String(pVal))
    }
  }
  return str
}

export const activeLocaleOption = computed(() => {
  return SUPPORTED_LOCALES.find(l => l.code === currentLocale.value) || SUPPORTED_LOCALES[0]
})

export function useI18n() {
  return {
    t,
    locale: currentLocale,
    setLocale,
    activeLocaleOption,
    supportedLocales: SUPPORTED_LOCALES,
  }
}
