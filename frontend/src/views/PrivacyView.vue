<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Lock, Shield, ExternalLink } from 'lucide-vue-next'
import { t } from '../i18n'

const router = useRouter()
const privacyVersion = ref('2026.1')
const effectiveDate = ref('October 2026')

interface PrivacySection {
  title: string
  content: string
}

const sections = ref<PrivacySection[]>([
  {
    title: '1. Information We Collect',
    content: 'We collect minimal personal information necessary to deliver NoteSight services: your email address and encrypted password hash upon account registration, optional billing credentials managed securely via Stripe, and upload file payloads (PDFs, images) submitted for optical music recognition processing.'
  },
  {
    title: '2. Sheet Music Processing & Storage Privacy',
    content: 'All sheet music uploaded to NoteSight remains private to your account by default. Score documents and resulting MusicXML, MIDI, and PDF outputs are stored securely in Google Cloud Storage with AES-256 encryption at rest. NoteSight does not share your scores with public directories or third-party datasets unless you explicitly generate a public share link.'
  },
  {
    title: '3. Cookies & Client-Side Storage',
    content: 'NoteSight uses strictly necessary session storage and HTTP cookies for authentication and CSRF protection. Functional preferences (such as audio player BPM, synthesized instrument timbre, zoom scale, and UI dark/light theme) are stored locally in your browser storage. We do not use third-party behavioral advertising trackers.'
  },
  {
    title: '4. Subprocessors & Cloud Infrastructure',
    content: 'Our cloud architecture runs on enterprise infrastructure hosted in Google Cloud Platform (GCP) Europe-West regions. Payment processing is tokenized directly through Stripe (PCI-DSS Level 1 compliant). Transactional communications are routed securely via Cloudflare and verified mail relays.'
  },
  {
    title: '5. Your Rights & Data Erasure (GDPR & CCPA)',
    content: 'Under applicable data privacy laws including the GDPR and CCPA, you have the right to inspect, export, or permanently delete your account and all associated score files at any time. Account deletion immediately purges your library files and database records across our systems.'
  },
  {
    title: '6. Security & Encryption Standards',
    content: 'All traffic between your browser and NoteSight is encrypted using TLS 1.3 with strict HTTP Strict Transport Security (HSTS). API endpoints require cryptographically signed Bearer JWTs and employ automated rate limiting and brute-force safeguards.'
  }
])
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
          <Lock :size="28" class="text-emerald-400" />
        </div>
        <div>
          <h1 class="legal-title">Privacy Policy</h1>
          <p class="legal-meta">Effective {{ effectiveDate }} • Version {{ privacyVersion }}</p>
        </div>
      </header>

      <div class="callout-box">
        <Shield :size="20" class="callout-icon" />
        <p>
          <strong>Privacy Commitment:</strong> We believe in privacy by design. Your uploaded scores are private to you, encrypted at rest and in transit, and never monetized or sold to third parties.
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
          To exercise your data privacy rights or request information, contact your system administrator.
        </p>
        <div class="footer-nav-links">
          <router-link to="/terms" class="footer-route-link">Terms of Service</router-link>
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
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
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
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 16px 20px;
  border-radius: 10px;
  font-size: 0.9rem;
  line-height: 1.5;
  color: #34d399;
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
