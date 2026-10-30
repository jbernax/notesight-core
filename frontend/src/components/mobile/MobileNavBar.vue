<script setup lang="ts">
import { BookOpen, PlusCircle, User } from 'lucide-vue-next';
import { useNativePlatform, activeProcessingCount } from '../../composables/useNativePlatform';
import { t } from '../../i18n';

defineProps<{
  activeTab: 'library' | 'create' | 'settings';
}>();

const emit = defineEmits<{
  (e: 'selectTab', tab: 'library' | 'create' | 'settings'): void;
}>();

const { triggerHapticLight } = useNativePlatform();

const onTabClick = (tab: 'library' | 'create' | 'settings') => {
  triggerHapticLight();
  emit('selectTab', tab);
};
</script>

<template>
  <nav class="mobile-nav-bar" role="navigation" aria-label="Mobile Navigation">
    <div class="nav-container">
      <!-- Tab 1: Score Library (Home) -->
      <button
        type="button"
        class="nav-item-btn"
        :class="{ active: activeTab === 'library' }"
        @click="onTabClick('library')"
        :aria-label="t('nav.library')"
        :aria-current="activeTab === 'library' ? 'page' : undefined"
      >
        <div class="nav-icon-pill">
          <BookOpen class="nav-icon" />
          <span v-if="activeProcessingCount > 0" class="nav-live-badge">
            {{ activeProcessingCount }}
          </span>
        </div>
        <span class="nav-label">{{ t('nav.library') }}</span>
      </button>

      <!-- Tab 2: New / Import Score -->
      <button
        type="button"
        class="nav-item-btn"
        :class="{ active: activeTab === 'create' }"
        @click="onTabClick('create')"
        :aria-label="t('dashboard.createScore')"
        :aria-current="activeTab === 'create' ? 'page' : undefined"
      >
        <div class="nav-icon-pill">
          <PlusCircle class="nav-icon" />
        </div>
        <span class="nav-label">{{ t('dashboard.newScore') }}</span>
      </button>

      <!-- Tab 3: Account & Settings -->
      <button
        type="button"
        class="nav-item-btn"
        :class="{ active: activeTab === 'settings' }"
        @click="onTabClick('settings')"
        :aria-label="t('nav.settings')"
        :aria-current="activeTab === 'settings' ? 'page' : undefined"
      >
        <div class="nav-icon-pill">
          <User class="nav-icon" />
        </div>
        <span class="nav-label">{{ t('nav.account') }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.mobile-nav-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 9000;
  background: var(--bg-glass-heavy, rgba(12, 15, 23, 0.94));
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-top: 1px solid var(--border);
  padding-bottom: max(var(--sab, 0px), 4px);
}

.nav-container {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  align-items: center;
  height: var(--mobile-nav-height, 60px);
  max-width: 520px;
  margin: 0 auto;
  padding: 0 8px;
}

.nav-item-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-height: 52px;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 4px 0;
  transition: color 0.16s ease;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}

.nav-icon-pill {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 28px;
  border-radius: 9999px;
  transition: background-color 0.18s ease, transform 0.12s ease;
}

.nav-item-btn:active .nav-icon-pill {
  transform: scale(0.93);
}

.nav-item-btn.active {
  color: var(--color-primary);
}

.nav-item-btn.active .nav-icon-pill {
  background: var(--color-primary-light, rgba(99, 102, 241, 0.16));
}

.nav-item-btn.active .nav-label {
  font-weight: 700;
  color: var(--text-primary);
}

.nav-icon {
  width: 19px;
  height: 19px;
  stroke-width: 2.1;
}

.nav-label {
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.nav-live-badge {
  position: absolute;
  top: -2px;
  right: 4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 9999px;
  background: var(--color-success, #10b981);
  color: #ffffff;
  font-size: 0.65rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(16, 185, 129, 0.4);
}

/* Hide navigation bar on larger screens */
@media (min-width: 769px) {
  .mobile-nav-bar {
    display: none;
  }
}
</style>

