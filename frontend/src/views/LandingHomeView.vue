<script setup lang="ts">
import { defineAsyncComponent } from 'vue'
import { t } from '../i18n'

const GuestScoreSandbox = defineAsyncComponent({
  loader: () => import('../components/landing/GuestScoreSandbox.vue'),
  delay: 200,
})
import {
  Sparkles,
  ArrowRight,
  CheckCircle,
  FileMusic,
  Headphones,
  Sliders,
  ShieldCheck,
  Smartphone,
  Camera,
  Sun,
  Maximize
} from 'lucide-vue-next'

</script>

<template>
  <div class="landing-page">
    <!-- Hero Section -->
    <section class="hero-section">
      <div class="hero-container">
        <div class="hero-pill">
          <Sparkles :size="15" class="text-indigo-400" />
          <span>{{ t('landing.heroPill') }}</span>
        </div>

        <h1 class="hero-title">
          {{ t('landing.heroTitle') }}
        </h1>

        <p class="hero-subtitle">
          {{ t('landing.heroSubtitle') }}
        </p>

        <div class="hero-cta-group">
          <router-link to="/register" class="hero-btn primary">
            <span>{{ t('landing.createFreeAccount') }}</span>
            <ArrowRight :size="16" />
          </router-link>

          <router-link to="/login" class="hero-btn secondary">
            <span>{{ t('landing.ctaSignIn') }}</span>
          </router-link>
        </div>

        <div class="hero-social-proof">
          <div class="proof-item">
            <CheckCircle :size="16" class="text-emerald-400" />
            <span>{{ t('landing.instantPlayback') }}</span>
          </div>
          <div class="proof-item">
            <CheckCircle :size="16" class="text-emerald-400" />
            <span>{{ t('landing.feat3Title') }}</span>
          </div>
          <div class="proof-item">
            <CheckCircle :size="16" class="text-emerald-400" />
            <span>{{ t('landing.feat1Title') }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Guest Test Sandbox Section -->
    <section class="sandbox-section">
      <GuestScoreSandbox />
    </section>

    <!-- How It Works (3 Steps) -->
    <section class="how-it-works-section">
      <div class="section-container">
        <div class="section-header">
          <span class="section-tag">{{ t('landing.howItWorksTag') }}</span>
          <h2 class="section-title">{{ t('landing.howItWorksTitle') }}</h2>
          <p class="section-subtitle">{{ t('landing.howItWorksSubtitle') }}</p>
        </div>

        <div class="steps-grid">
          <div class="step-card">
            <div class="step-number">1</div>
            <div class="step-icon-wrapper">
              <FileMusic :size="28" class="text-indigo-400" />
            </div>
            <h3 class="step-title">{{ t('landing.step1Title') }}</h3>
            <p class="step-desc">
              {{ t('landing.step1Desc') }}
            </p>
          </div>

          <div class="step-card">
            <div class="step-number">2</div>
            <div class="step-icon-wrapper">
              <Sparkles :size="28" class="text-indigo-400" />
            </div>
            <h3 class="step-title">{{ t('landing.step2Title') }}</h3>
            <p class="step-desc">
              {{ t('landing.step2Desc') }}
            </p>
          </div>

          <div class="step-card">
            <div class="step-number">3</div>
            <div class="step-icon-wrapper">
              <Headphones :size="28" class="text-indigo-400" />
            </div>
            <h3 class="step-title">{{ t('landing.step3Title') }}</h3>
            <p class="step-desc">
              {{ t('landing.step3Desc') }}
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- Feature Highlights Grid -->
    <section class="features-section">
      <div class="section-container">
        <div class="section-header">
          <span class="section-tag">{{ t('landing.featuresTag') }}</span>
          <h2 class="section-title">{{ t('landing.featuresTitle') }}</h2>
        </div>

        <div class="features-grid">
          <div class="feature-card">
            <div class="feature-icon"><Sliders :size="22" class="text-indigo-400" /></div>
            <h3>{{ t('landing.feat1Title') }}</h3>
            <p>{{ t('landing.feat1Desc') }}</p>
          </div>

          <div class="feature-card">
            <div class="feature-icon"><Headphones :size="22" class="text-indigo-400" /></div>
            <h3>{{ t('landing.feat2Title') }}</h3>
            <p>{{ t('landing.feat2Desc') }}</p>
          </div>

          <div class="feature-card">
            <div class="feature-icon"><FileMusic :size="22" class="text-indigo-400" /></div>
            <h3>{{ t('landing.feat3Title') }}</h3>
            <p>{{ t('landing.feat3Desc') }}</p>
          </div>

          <div class="feature-card">
            <div class="feature-icon"><Smartphone :size="22" class="text-indigo-400" /></div>
            <h3>{{ t('landing.feat4Title') }}</h3>
            <p>{{ t('landing.feat4Desc') }}</p>
          </div>

          <div class="feature-card">
            <div class="feature-icon"><ShieldCheck :size="22" class="text-indigo-400" /></div>
            <h3>{{ t('landing.feat5Title') }}</h3>
            <p>{{ t('landing.feat5Desc') }}</p>
          </div>

          <div class="feature-card">
            <div class="feature-icon"><Sparkles :size="22" class="text-indigo-400" /></div>
            <h3>{{ t('landing.feat6Title') }}</h3>
            <p>{{ t('landing.feat6Desc') }}</p>
          </div>
        </div>
      </div>
    </section>


    <!-- Scanning Tips for Best OMR Accuracy -->
    <section class="tips-section">
      <div class="section-container">
        <div class="section-header">
          <span class="section-tag">{{ t('landing.tipsTag') }}</span>
          <h2 class="section-title">{{ t('landing.tipsTitle') }}</h2>
        </div>

        <div class="tips-grid">
          <div class="tip-card">
            <div class="tip-icon"><Sun :size="24" class="text-amber-400" /></div>
            <h3>{{ t('landing.tip1Title') }}</h3>
            <p>{{ t('landing.tip1Desc') }}</p>
          </div>

          <div class="tip-card">
            <div class="tip-icon"><Maximize :size="24" class="text-indigo-400" /></div>
            <h3>{{ t('landing.tip2Title') }}</h3>
            <p>{{ t('landing.tip2Desc') }}</p>
          </div>

          <div class="tip-card">
            <div class="tip-icon"><Camera :size="24" class="text-emerald-400" /></div>
            <h3>{{ t('landing.tip3Title') }}</h3>
            <p>{{ t('landing.tip3Desc') }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Bottom CTA Banner -->
    <section class="bottom-cta-section">
      <div class="section-container">
        <div class="cta-box">
          <h2>{{ t('landing.ctaTitle') }}</h2>
          <p>{{ t('landing.ctaSubtitle') }}</p>
          <div class="cta-actions">
            <router-link to="/register" class="hero-btn primary">
              <span>{{ t('landing.createFreeAccount') }}</span>
              <ArrowRight :size="16" />
            </router-link>
            <router-link to="/login" class="hero-btn secondary">
              <span>{{ t('landing.ctaSignIn') }}</span>
            </router-link>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.landing-page {
  display: flex;
  flex-direction: column;
  background: var(--bg-canvas);
  color: var(--text-primary);
  min-height: 100vh;
}

/* Hero */
.hero-section {
  padding: 4.5rem 1.5rem 2.5rem;
  background: radial-gradient(circle at 50% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 70%);
  text-align: center;
  min-height: calc(100vh - var(--app-header-height, 65px));
  display: flex;
  flex-direction: column;
  justify-content: center;
  box-sizing: border-box;
}

.sandbox-section {
  min-height: 480px;
  width: 100%;
}

.hero-container {
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.hero-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.28);
  padding: 0.35rem 0.9rem;
  border-radius: 9999px;
  font-size: 0.825rem;
  font-weight: 600;
  color: #818cf8;
  margin-bottom: 1.5rem;
}

.hero-title {
  font-size: 3.25rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.15;
  margin: 0 0 1.25rem;
  color: var(--text-primary);
}

.hero-subtitle {
  font-size: 1.2rem;
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 680px;
  margin: 0 0 2rem;
}

.hero-cta-group {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: 2rem;
}

.hero-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.6rem;
  border-radius: 0.5rem;
  font-weight: 600;
  font-size: 0.95rem;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s ease;
  border: none;
}

.hero-btn.primary {
  background: #4f46e5;
  color: #ffffff;
  box-shadow: 0 4px 18px rgba(79, 70, 229, 0.45);
}

.hero-btn.primary:hover {
  background: #4338ca;
  transform: translateY(-2px);
}

.hero-btn.secondary {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border);
}

.hero-btn.secondary:hover {
  background: var(--bg-hover);
  border-color: #6366f1;
}

.hero-social-proof {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  flex-wrap: wrap;
  justify-content: center;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.proof-item {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

/* Sections */
.section-container {
  max-width: 1040px;
  margin: 0 auto;
  padding: 4.5rem 1.5rem;
}

.section-header {
  text-align: center;
  margin-bottom: 3rem;
}

.section-tag {
  display: inline-block;
  font-size: 0.8rem;
  font-weight: 700;
  color: #818cf8;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 0.5rem;
}

.section-title {
  font-size: 2.25rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
}

.section-subtitle {
  font-size: 1.05rem;
  color: var(--text-secondary);
  max-width: 600px;
  margin: 0 auto;
}

/* Steps Grid */
.steps-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.step-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 1rem;
  padding: 2.25rem 1.5rem;
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.step-number {
  position: absolute;
  top: 1.25rem;
  right: 1.25rem;
  font-size: 2.5rem;
  font-weight: 800;
  color: rgba(99, 102, 241, 0.12);
  line-height: 1;
}

.step-icon-wrapper {
  width: 3.25rem;
  height: 3.25rem;
  border-radius: 0.75rem;
  background: rgba(99, 102, 241, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 0.5rem;
}

.step-title {
  font-size: 1.2rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.step-desc {
  font-size: 0.9rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

/* Features Grid */
.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.feature-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0.85rem;
  padding: 1.75rem;
  transition: all 0.2s ease;
}

.feature-card:hover {
  border-color: rgba(99, 102, 241, 0.4);
  transform: translateY(-2px);
}

.feature-icon {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.5rem;
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1rem;
}

.feature-card h3 {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
}

.feature-card p {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}


/* Scanning Tips */
.tips-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.tip-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 0.85rem;
  padding: 1.75rem;
}

.tip-icon {
  margin-bottom: 0.75rem;
}

.tip-card h3,
.tip-card h4 {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 0.5rem;
}

.tip-card p {
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin: 0;
}

/* Bottom CTA */
.bottom-cta-section {
  padding-bottom: 5rem;
}

.cta-box {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.18), rgba(16, 185, 129, 0.12));
  border: 1px solid rgba(99, 102, 241, 0.35);
  border-radius: 1.25rem;
  padding: 4rem 2rem;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

.cta-box h2 {
  font-size: 2.25rem;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.02em;
}

.cta-box p {
  font-size: 1.1rem;
  color: var(--text-secondary);
  max-width: 600px;
  margin: 0 0 1rem;
}

.cta-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
}

@media (max-width: 900px) {
  .steps-grid, .features-grid, .tips-grid {
    grid-template-columns: 1fr;
  }
  .hero-title {
    font-size: 2.25rem;
  }
}
</style>
