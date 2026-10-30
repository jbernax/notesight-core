<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Globe, ChevronDown, Check } from 'lucide-vue-next'
import { currentLocale, setLocale, SUPPORTED_LOCALES, type SupportedLocale } from '../i18n'

const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)

const toggleOpen = () => {
  isOpen.value = !isOpen.value
}

const selectLanguage = (code: SupportedLocale) => {
  setLocale(code)
  isOpen.value = false
}

const handleClickOutside = (e: MouseEvent) => {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="language-selector-wrapper" ref="dropdownRef">
    <button
      type="button"
      class="lang-pill-btn"
      @click.stop="toggleOpen"
      :aria-expanded="isOpen"
      :title="$t('settings.language.selectLabel')"
    >
      <Globe class="lang-icon" :size="16" />
      <span class="lang-current-code">{{ currentLocale.toUpperCase() }}</span>
      <ChevronDown class="lang-chevron" :size="14" :class="{ 'rotate': isOpen }" />
    </button>

    <div v-if="isOpen" class="lang-dropdown-menu">
      <div class="lang-dropdown-header">
        <span>{{ $t('settings.language.title') }}</span>
      </div>
      <div class="lang-options-list">
        <button
          v-for="loc in SUPPORTED_LOCALES"
          :key="loc.code"
          type="button"
          class="lang-option-item"
          :class="{ 'is-active': loc.code === currentLocale }"
          @click="selectLanguage(loc.code)"
        >
          <span class="lang-flag">{{ loc.flag }}</span>
          <span class="lang-label-group">
            <span class="lang-native">{{ loc.native }}</span>
            <span class="lang-name">{{ loc.label }}</span>
          </span>
          <Check v-if="loc.code === currentLocale" class="check-icon" :size="15" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.language-selector-wrapper {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.lang-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-subtle, rgba(255, 255, 255, 0.05));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  color: var(--text-primary, #f1f5f9);
  padding: 6px 12px;
  border-radius: 9999px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  min-height: 38px;
}

.lang-pill-btn:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.1));
  border-color: var(--color-primary, #6366f1);
}

.lang-icon {
  color: var(--color-primary, #818cf8);
}

.lang-current-code {
  letter-spacing: 0.5px;
}

.lang-chevron {
  opacity: 0.7;
  transition: transform 0.2s ease;
}

.lang-chevron.rotate {
  transform: rotate(180deg);
}

.lang-dropdown-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 220px;
  background: var(--bg-card, #1e2230);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.15));
  border-radius: 12px;
  box-shadow: var(--shadow-lg, 0 12px 30px rgba(0, 0, 0, 0.45));
  z-index: 1000;
  overflow: hidden;
  backdrop-filter: blur(16px);
  animation: fadeInDown 0.15s ease-out;
}

@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.lang-dropdown-header {
  padding: 10px 14px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted, #94a3b8);
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.08));
}

.lang-options-list {
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.lang-option-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-primary, #e2e8f0);
  font-size: 0.85rem;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
  min-height: 42px;
}

.lang-option-item:hover {
  background: var(--bg-hover, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #ffffff);
}

.lang-option-item.is-active {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.15));
  color: var(--color-primary, #818cf8);
  font-weight: 600;
}

.lang-flag {
  font-size: 1.15rem;
  line-height: 1;
}

.lang-label-group {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.lang-native {
  font-weight: 600;
  font-size: 0.85rem;
}

.lang-name {
  font-size: 0.72rem;
  opacity: 0.8;
  color: var(--text-secondary, #94a3b8);
}

.check-icon {
  color: var(--color-primary, #818cf8);
}
</style>
