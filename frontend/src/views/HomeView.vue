<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import LandingHomeView from './LandingHomeView.vue'

const isAuthenticated = computed(() => Boolean(localStorage.getItem('token')))

const DashboardView = defineAsyncComponent(() => import('./DashboardView.vue'))
</script>

<template>
  <component :is="isAuthenticated ? DashboardView : LandingHomeView" />
</template>
