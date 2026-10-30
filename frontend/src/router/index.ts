import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import HomeView from '../views/HomeView.vue'

const DEFAULT_TITLE = 'NoteSight - Sheet Music Digitization & Optical Music Recognition'
const DEFAULT_DESCRIPTION = 'Digitize sheet music with NoteSight. Instant Optical Music Recognition (OMR) converting PDF and image scores into MusicXML, MIDI, and interactive browser notation with synchronized audio playback.'

const routes: Array<RouteRecordRaw> = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: {
      guestOnly: true,
      title: 'Sign In | NoteSight - Sheet Music Digitization & Playback',
      description: 'Sign in to NoteSight to access your sheet music library, OMR transcription jobs, and interactive audio studio.',
    }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/RegisterView.vue'),
    meta: {
      guestOnly: true,
      title: 'Create Account | NoteSight - Sheet Music Digitization & Playback',
      description: 'Create a free NoteSight account to digitize sheet music, convert PDFs to MusicXML, and practice sight-reading with audio playback.',
    }
  },
  {
    path: '/forgot-password',
    name: 'ForgotPassword',
    component: () => import('../views/ForgotPasswordView.vue'),
    meta: {
      guestOnly: true,
      title: 'Forgot Password | NoteSight',
      description: 'Reset your NoteSight account password.',
    }
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('../views/ResetPasswordView.vue'),
    meta: {
      guestOnly: true,
      title: 'Reset Password | NoteSight',
      description: 'Choose a new password for your NoteSight account.',
    }
  },
  {
    path: '/verify-email',
    name: 'VerifyEmail',
    component: () => import('../views/VerifyEmailView.vue'),
    meta: {
      title: 'Verify Email | NoteSight',
      description: 'Confirm your email address to activate your NoteSight account.',
    }
  },
  {
    path: '/auth/google/callback',
    name: 'OAuthCallback',
    component: () => import('../views/OAuthCallbackView.vue'),
    meta: {
      title: 'Signing In... | NoteSight',
      description: 'Completing Google Single Sign-On authentication.',
    }
  },
  {
    path: '/score/share/:token',
    name: 'SharedScore',
    component: () => import('../views/SharedScoreView.vue'),
    meta: {
      title: 'Shared Sheet Music | NoteSight',
      description: 'View and listen to interactive sheet music digitized with NoteSight.',
    }
  },
  {
    path: '/score/embed/:token',
    name: 'ScoreEmbed',
    component: () => import('../views/ScoreEmbedView.vue'),
    meta: {
      title: 'NoteSight Score Embed',
      description: 'Interactive embedded sheet music player powered by NoteSight.',
    }
  },
  {
    path: '/terms',
    name: 'Terms',
    component: () => import('../views/TermsView.vue'),
    meta: {
      title: 'Terms of Service | NoteSight - Sheet Music Digitization',
      description: 'Terms of Service for NoteSight: Authorized sheet music transcription, copyright policies, and acceptable use.',
    }
  },
  {
    path: '/privacy',
    name: 'Privacy',
    component: () => import('../views/PrivacyView.vue'),
    meta: {
      title: 'Privacy Policy | NoteSight - Sheet Music Digitization',
      description: 'Privacy Policy for NoteSight: Data protection, sheet music confidentiality, cookie preferences, and GDPR/CCPA rights.',
    }
  },
  {
    path: '/',
    name: 'Home',
    component: HomeView,
    meta: {
      title: 'NoteSight - Sheet Music Digitization & Optical Music Recognition',
      description: 'Digitize sheet music with NoteSight. Instant Optical Music Recognition (OMR) converting PDF and image scores into MusicXML, MIDI, and interactive browser notation with synchronized audio playback.',
    }
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: {
      requiresAuth: true,
      title: 'Studio Dashboard | NoteSight',
      description: 'Your personal NoteSight score library, OMR transcription workbench, and playback studio.',
    }
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

import { isTokenExpiringSoon, refreshAuthToken, clearAuthSession } from '../services/apiClient'

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to, _from, next) => {
  let token = localStorage.getItem('token')
  const refreshToken = localStorage.getItem('refresh_token')

  if (token && isTokenExpiringSoon(token, 30)) {
    if (refreshToken) {
      token = await refreshAuthToken()
    } else {
      clearAuthSession()
      token = null
    }
  }

  if (to.meta.requiresAuth && !token) {
    clearAuthSession()
    next({ name: 'Login' })
  } else if (to.meta.guestOnly && token) {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

// Dynamic SEO meta tag & title management on route changes
router.afterEach((to) => {
  const title = (to.meta.title as string) || DEFAULT_TITLE
  const description = (to.meta.description as string) || DEFAULT_DESCRIPTION
  const canonicalPath = to.path === '/' ? '/' : to.path.replace(/\/+$/, '')
  const canonicalUrl = `${window.location.origin}${canonicalPath}`

  document.title = title

  // Update meta description
  const metaDesc = document.querySelector('meta[name="description"]')
  if (metaDesc) {
    metaDesc.setAttribute('content', description)
  }

  // Update canonical link
  let canonicalLink = document.querySelector('link[rel="canonical"]')
  if (!canonicalLink) {
    canonicalLink = document.createElement('link')
    canonicalLink.setAttribute('rel', 'canonical')
    document.head.appendChild(canonicalLink)
  }
  canonicalLink.setAttribute('href', canonicalUrl)

  // Update OpenGraph / Twitter tags
  const ogTitle = document.querySelector('meta[property="og:title"]')
  if (ogTitle) ogTitle.setAttribute('content', title)

  const ogDesc = document.querySelector('meta[property="og:description"]')
  if (ogDesc) ogDesc.setAttribute('content', description)

  const ogUrl = document.querySelector('meta[property="og:url"]')
  if (ogUrl) ogUrl.setAttribute('content', canonicalUrl)

  const twTitle = document.querySelector('meta[name="twitter:title"]')
  if (twTitle) twTitle.setAttribute('content', title)

  const twDesc = document.querySelector('meta[name="twitter:description"]')
  if (twDesc) twDesc.setAttribute('content', description)

  const twUrl = document.querySelector('meta[name="twitter:url"]')
  if (twUrl) twUrl.setAttribute('content', canonicalUrl)
})

export default router
