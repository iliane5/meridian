<script setup lang="ts">
const config = useRuntimeConfig();
const reports = useReports();
const isLoading = ref(true);
const error = ref(false);

// Handle redirection on client side
onMounted(async () => {
  // Wait a moment for reports to be loaded
  await nextTick();

  // Check if reports are loaded
  if (reports.value.length > 0) {
    const latestReport = reports.value[0];
    navigateTo(`/briefs/${latestReport.slug}`);
  } else {
    // If no reports yet, wait a bit and try again
    setTimeout(() => {
      if (reports.value.length > 0) {
        const latestReport = reports.value[0];
        navigateTo(`/briefs/${latestReport.slug}`);
      } else {
        error.value = true;
      }
      isLoading.value = false;
    }, 2000);
  }
});

useSEO({
  title: 'latest report | meridian',
  description:
    'a daily brief of everything important happening that i care about, with actual analysis beyond headlines',
  ogImage: `${config.public.WORKER_API}/openGraph/default`,
  ogUrl: `https://news.iliane.xyz/latest`,
});
</script>

<template>
  <div>
    <p v-if="isLoading">Redirecting to the latest report...</p>
    <div v-else-if="error" class="text-center py-8">
      <h2 class="text-xl font-bold mb-2">No reports found</h2>
      <p class="mb-4">Unable to find any reports at this time.</p>
      <NuxtLink to="/briefs" class="underline">View all briefs</NuxtLink>
    </div>
  </div>
</template>
