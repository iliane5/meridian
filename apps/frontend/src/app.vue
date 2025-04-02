<script lang="ts" setup>
// Use onMounted to fetch data on the client side
onMounted(async () => {
  try {
    const reports = await fetchReports();
    useReports().value = reports || [];
  } catch (error) {
    console.error('Failed to fetch articles', error);
  }
});
</script>

<template>
  <div class="min-h-screen bg-white flex flex-col">
    <NuxtRouteAnnouncer />
    <div class="max-w-3xl mx-auto px-6 w-full flex-1">
      <nav class="py-4">
        <ul class="flex space-x-4 font-medium">
          <li>
            <NuxtLink class="hover:underline" :class="$route.path === '/' ? 'underline' : ''" to="/"> home </NuxtLink>
          </li>
          <li>
            <NuxtLink class="hover:underline" :class="$route.path === '/briefs' ? 'underline' : ''" to="/briefs">
              briefs
            </NuxtLink>
          </li>
        </ul>
      </nav>
      <div class="h-px w-full bg-gray-300 mb-4" />
      <NuxtPage />
    </div>
    <footer>
      <div class="max-w-3xl mx-auto px-6 py-4">
        <div class="h-px w-full bg-gray-300 mb-4" />
        <p class="text-sm text-center">
          built by
          <strong class="underline"><NuxtLink :to="`https://iliane.xyz`">iliane</NuxtLink></strong>
          ·
          <span
            >open source on
            <strong class="underline"
              ><NuxtLink to="https://github.com/iliane5/meridian" target="_blank">github</NuxtLink></strong
            ></span
          >
        </p>
      </div>
    </footer>
  </div>
</template>
