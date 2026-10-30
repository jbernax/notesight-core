<script setup lang="ts">
import { ref } from 'vue'
import { isBannerOpen, acceptAll, acceptEssentialOnly, openCookiePreferences } from '../composables/useCookieConsent'
import { isMobileImmersiveMode } from '../composables/useNativePlatform'

const isMinimized = ref(false)
</script>

<template>
  <div v-if="isBannerOpen && !isMobileImmersiveMode" class="cookie-banner-wrapper">
      <!-- Minimized Floating Pill -->
      <aside
        v-if="isMinimized"
        class="cookie-minimized-pill"
        role="region"
        aria-label="Cookie Settings"
      >
        <button
          type="button"
          class="btn-expand-cookie"
          @click="isMinimized = false"
          :title="$t('cookies.reviewAdvice')"
        >
          <svg class="pill-shield-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            <path d="m9 12 2 2 4-4"></path>
          </svg>
          <span>{{ $t('cookies.cookieAdvice') }}</span>
        </button>
      </aside>

      <!-- Full Advice Banner -->
      <aside 
        v-else 
        class="cookie-advice-banner" 
        role="region" 
        aria-labelledby="cookie-banner-title"
      >
        <div class="banner-inner">
          <div class="banner-content">
            <div class="banner-icon-col">
              <div class="shield-badge">
                <svg class="shield-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                  <path d="m9 12 2 2 4-4"></path>
                </svg>
              </div>
            </div>
            <div class="banner-text-col">
              <div class="banner-title-row">
                <div class="banner-title" id="cookie-banner-title">{{ $t('cookies.bannerTitle') }}</div>
                <button
                  type="button"
                  class="btn-minimize-icon"
                  @click="isMinimized = true"
                  title="Minimize cookie advice to icon"
                  aria-label="Minimize cookie advice"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                  </svg>
                </button>
              </div>
              <p class="banner-desc">
                {{ $t('cookies.bannerText') }}
              </p>
            </div>
          </div>

          <div class="banner-actions">
            <button 
              type="button" 
              class="btn-customize" 
              @click="openCookiePreferences"
            >
              {{ $t('cookies.customize') }}
            </button>
            <button 
              type="button" 
              class="btn-essential" 
              @click="acceptEssentialOnly"
            >
              {{ $t('cookies.strictlyNecessary') }}
            </button>
            <button 
              type="button" 
              class="btn-accept-all" 
              @click="acceptAll"
            >
              {{ $t('cookies.acceptAll') }}
            </button>
          </div>
        </div>
      </aside>
    </div>
</template>

<style scoped>
.cookie-advice-banner {
  position: fixed;
  bottom: 1.25rem;
  left: 1.25rem;
  right: 1.25rem;
  max-width: 1040px;
  margin: 0 auto;
  z-index: 9999;
  background: rgba(18, 22, 34, 0.95);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(99, 102, 241, 0.15);
  color: #f1f5f9;
  padding: 1.15rem 1.5rem;
}

.banner-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
}

@media (max-width: 860px) {
  .banner-inner {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }
}

.banner-content {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  flex: 1;
}

.shield-badge {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(168, 85, 247, 0.2));
  border: 1px solid rgba(99, 102, 241, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #818cf8;
  flex-shrink: 0;
}

.shield-icon {
  width: 20px;
  height: 20px;
}

.banner-text-col {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.banner-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.banner-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #ffffff;
  letter-spacing: -0.01em;
}

.btn-minimize-icon {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.btn-minimize-icon:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

/* Minimized Floating Pill */
.cookie-minimized-pill {
  position: fixed;
  bottom: 1.25rem;
  right: 1.25rem;
  z-index: 9999;
}

.btn-expand-cookie {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(18, 22, 34, 0.95);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 20px;
  padding: 0.5rem 0.95rem;
  color: #e2e8f0;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(99, 102, 241, 0.2);
  transition: all 0.2s ease;
}

.btn-expand-cookie:hover {
  background: rgba(30, 36, 56, 0.98);
  border-color: rgba(99, 102, 241, 0.4);
  color: #ffffff;
  transform: translateY(-2px);
}

.pill-shield-icon {
  width: 15px;
  height: 15px;
  color: #818cf8;
}

.banner-desc {
  margin: 0;
  font-size: 0.82rem;
  line-height: 1.45;
  color: #94a3b8;
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-shrink: 0;
}

@media (max-width: 860px) {
  .banner-actions {
    justify-content: flex-end;
  }
}

@media (max-width: 768px) {
  .cookie-advice-banner {
    left: 0.75rem;
    right: 0.75rem;
    bottom: calc(var(--mobile-bottom-offset, 60px) + 0.75rem);
    padding: 1rem;
  }
}

@media (max-width: 480px) {
  .banner-actions {
    flex-direction: column;
    width: 100%;
    gap: 8px;
  }
  .btn-customize,
  .btn-essential,
  .btn-accept-all {
    width: 100%;
    min-height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
}

.btn-customize {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #cbd5e1;
  padding: 0.5rem 0.9rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-customize:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.25);
  color: #ffffff;
}

.btn-essential {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: #e2e8f0;
  padding: 0.5rem 0.95rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-essential:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.btn-accept-all {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  border: none;
  color: #ffffff;
  padding: 0.5rem 1.15rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.4);
  transition: all 0.15s ease;
}

.btn-accept-all:hover {
  filter: brightness(1.1);
  transform: translateY(-1px);
}

/* Pure CSS slide-up animation avoiding JS-triggered offsetHeight forced reflow */
.cookie-banner-wrapper {
  animation: cookieSlideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes cookieSlideUp {
  from {
    transform: translateY(100%);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}
</style>
