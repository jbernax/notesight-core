<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, ShieldCheck, FileText, ExternalLink } from 'lucide-vue-next'
import { t } from '../i18n'

const router = useRouter()
const termsVersion = ref('2026.1-copyright')
const effectiveDate = ref('October 2026')

interface LegalSection {
  title: string
  content: string
}

const sections = ref<LegalSection[]>([
  {
    title: '1. Lawful Use & Sheet Music Copyright Authorization',
    content: 'You affirm, represent, and warrant that you either own the copyright, possess an explicit license from the copyright owner, or are transcribing musical scores that reside in the public domain or qualify under statutory fair use in your jurisdiction. NoteSight strictly prohibits unauthorized copying, digitization, or reproduction of copyrighted sheet music without authorization.'
  },
  {
    title: '2. Acceptable Use Policy & Prevention of Piracy',
    content: 'You agree not to use NoteSight to digitize, upload, export, or distribute sheet music in any manner that infringes on third-party intellectual property rights. Any attempt to use NoteSight to bypass digital rights management (DRM), mass-scrape protected score catalogs, or facilitate illegal score sharing will result in immediate termination of the account and potential reporting to rightsholders.'
  },
  {
    title: '3. User Representations & Age Requirement',
    content: 'You must be at least 13 years of age (or the applicable age of digital consent in your jurisdiction) to register an account. You agree to provide accurate, current, and complete registration information.'
  },
  {
    title: '4. Optional Billing & Subscription Tiers',
    content: 'Access to basic NoteSight OMR processing is available under our free Starter plan without requiring billing or payment information. Should you choose to upgrade to a paid tier (Virtuoso or Maestro), payments are processed securely via Stripe. Billing information is optional until a paid subscription is selected.'
  },
  {
    title: '5. Disclaimer of Warranties & AI Transcription Limitations',
    content: 'Neural optical music recognition produces algorithmic estimations of musical notation. NoteSight provides score transcription on an "as is" and "as available" basis. Users are advised to review and verify transcribed notation before performance, publishing, or commercial use.'
  },
  {
    title: '6. Open-Source Attribution & OMR Engine Source Availability',
    content: 'NoteSight\'s optical music recognition inference is powered by the standalone open-source package notesight-omr-engine (built on homr), licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-or-later) and executed as an isolated CLI subprocess. In accordance with AGPL-3.0 Section 13, the complete Corresponding Source code for notesight-omr-engine is publicly available at packages/notesight-omr-engine. Server-side PDF rendering and engraving utilize pypdfium2 (Apache-2.0/BSD-3-Clause), pypdf (BSD-3-Clause), Verovio (LGPL-3.0), and CairoSVG (LGPL-3.0); browser notation rendering uses OpenSheetMusicDisplay (BSD-3-Clause).'
  }
])

onMounted(async () => {
  try {
    const res = await fetch('/api/legal/terms')
    if (res.ok) {
      const data = await res.json()
      if (data.sections && data.sections.length > 0) {
        sections.value = data.sections
        termsVersion.value = data.version
        effectiveDate.value = data.effective_date
      }
    }
  } catch {
    // Keep fallback copy
  }
})
</script>

<template>
  <div class="legal-page-container">
    <div class="legal-card">
      <nav class="breadcrumb-bar" aria-label="Breadcrumb">
        <button class="back-btn" @click="router.push('/')">
          <ArrowLeft :size="16" />
          <span>{{ t('common.back') || 'Back to Home' }}</span>
        </button>
      </nav>

      <header class="legal-header">
        <div class="header-icon-wrapper">
          <FileText :size="28" class="text-indigo-400" />
        </div>
        <div>
          <h1 class="legal-title">Terms of Service</h1>
          <p class="legal-meta">Effective {{ effectiveDate }} • Version {{ termsVersion }}</p>
        </div>
      </header>

      <div class="callout-box">
        <ShieldCheck :size="20" class="callout-icon" />
        <p>
          <strong>Notice on Music Copyright:</strong> NoteSight is designed for authorized sheet music transcription, personal practice, sight-reading, and public domain digitization. Unauthorized copying of copyrighted musical compositions is strictly prohibited.
        </p>
      </div>

      <div class="sections-wrapper">
        <article v-for="(sec, idx) in sections" :key="idx" class="legal-section-block">
          <h2 class="section-heading">{{ sec.title }}</h2>
          <p class="section-body">{{ sec.content }}</p>
        </article>
      </div>

      <footer class="legal-footer">
        <p>
          Questions about these terms? Please contact your system administrator.
        </p>
        <div class="footer-nav-links">
          <router-link to="/privacy" class="footer-route-link">Privacy Policy</router-link>
          <span>•</span>
          <router-link to="/register" class="footer-route-link">Create Account</router-link>
          <span>•</span>
          <a href="/api/docs" class="footer-route-link" target="_blank" rel="noopener">
            API Docs <ExternalLink :size="12" />
          </a>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.legal-page-container {
  min-height: calc(100vh - 120px);
  padding: 40px 20px;
  background: var(--bg-canvas, #090d16);
  display: flex;
  justify-content: center;
}

.legal-card {
  width: 100%;
  max-width: 840px;
  background: var(--bg-card, #131926);
  border: 1px solid var(--border, #26334d);
  border-radius: 16px;
  padding: 36px 40px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  color: var(--text-primary, #e2e8f0);
}

.breadcrumb-bar {
  margin-bottom: 24px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  color: var(--color-primary, #6366f1);
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.back-btn:hover {
  background: rgba(99, 102, 241, 0.1);
}

.legal-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border, #26334d);
}

.header-icon-wrapper {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.legal-title {
  font-size: 1.85rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin: 0;
  color: var(--text-primary, #f8fafc);
}

.legal-meta {
  font-size: 0.85rem;
  color: var(--text-secondary, #94a3b8);
  margin-top: 4px;
}

.callout-box {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  padding: 16px 20px;
  border-radius: 10px;
  font-size: 0.9rem;
  line-height: 1.5;
  color: #fbbf24;
  margin-bottom: 28px;
}

.callout-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.sections-wrapper {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.legal-section-block {
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
}

.legal-section-block:last-child {
  border-bottom: none;
}

.section-heading {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text-primary, #f1f5f9);
  margin: 0 0 10px;
}

.section-body {
  font-size: 0.94rem;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.65;
  margin: 0;
}

.legal-footer {
  margin-top: 36px;
  padding-top: 24px;
  border-top: 1px solid var(--border, #26334d);
  font-size: 0.9rem;
  color: var(--text-secondary, #94a3b8);
}

.contact-link {
  color: var(--color-primary, #6366f1);
  text-decoration: underline;
}

.footer-nav-links {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  font-size: 0.85rem;
}

.footer-route-link {
  color: var(--text-secondary, #94a3b8);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: color 0.15s ease;
}

.footer-route-link:hover {
  color: var(--color-primary, #818cf8);
}

@media (max-width: 640px) {
  .legal-card {
    padding: 24px 20px;
    border-radius: 12px;
  }

  .legal-title {
    font-size: 1.5rem;
  }
}
</style>
