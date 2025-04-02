<script lang="ts" setup>
const config = useRuntimeConfig();
const { $md } = useNuxtApp();

// Constants
const WORDS_PER_MINUTE = 300;
const STORAGE_KEY = 'meridian_subscribed';

// Route and brief data extraction
const route = useRoute();
const slug = route.path.split('/').pop()?.replaceAll('_', '/');
const isLoading = ref(true);
const notFound = ref(false);

// Use ref for briefData instead of toRef from getReportBySlug
const briefData = ref(null);

// Load brief data on client side
onMounted(async () => {
  if (slug === undefined) {
    notFound.value = true;
    isLoading.value = false;
    return;
  }

  // Wait for reports to be loaded
  await nextTick();
  const reports = useReports();

  // Try to find the report by slug
  if (reports.value.length > 0) {
    const match = reports.value.find(report => report.slug === slug);
    if (match) {
      briefData.value = match;
    } else {
      notFound.value = true;
    }
  } else {
    // If no reports yet, wait a bit and try again
    setTimeout(() => {
      const match = reports.value.find(report => report.slug === slug);
      if (match) {
        briefData.value = match;
      } else {
        notFound.value = true;
      }
      isLoading.value = false;
    }, 2000);
    return;
  }

  isLoading.value = false;
});

const url = ref(`/`);

// Reading progress state
const readingProgress = ref(0);
let scrollListener: () => void;

// Subscription state
const email = ref('');
const isSubmitting = ref(false);
const hasSubscribed = ref(false);

/**
 * Calculates estimated reading time in minutes
 */
const estimateReadingTime = (content?: string): number => {
  if (!content) return 0;
  const wordCount = content.trim().split(/\s+/).length;
  return Math.ceil(wordCount / WORDS_PER_MINUTE);
};

// SEO metadata
const formatDate = computed(() => {
  if (!briefData.value || !briefData.value.date) return '';
  const date = briefData.value.date;
  return `${date.month.toLowerCase()} ${date.day}, ${date.year}`;
});

// Update SEO when brief data is loaded
watchEffect(() => {
  if (briefData.value) {
    useSEO({
      title: `${briefData.value.title.toLowerCase()} | meridian`,
      description: `brief for ${formatDate.value}`,
      ogImage: `${config.public.WORKER_API}/openGraph/brief?title=${encodeURIComponent(briefData.value.title)}&date=${encodeURIComponent(briefData.value.createdAt.getTime())}&articles=${briefData.value.usedArticles}&sources=${briefData.value.usedSources}`,
      ogUrl: `https://news.iliane.xyz/briefs/${slug}`,
    });
  } else {
    useSEO({
      title: `brief | meridian`,
      description: `daily brief of everything important happening`,
      ogImage: `${config.public.WORKER_API}/openGraph/default`,
      ogUrl: `https://news.iliane.xyz/briefs/${slug || ''}`,
    });
  }
});

// Lifecycle hooks
onMounted(() => {
  // Check subscription status
  hasSubscribed.value = localStorage.getItem(STORAGE_KEY) === 'true';

  // Initialize scroll progress tracking
  scrollListener = () => {
    const scrollTop = document.documentElement.scrollTop;
    const scrollHeight = document.documentElement.scrollHeight - document.documentElement.clientHeight;
    readingProgress.value = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;
  };

  window.addEventListener('scroll', scrollListener);
});

onUnmounted(() => {
  window.removeEventListener('scroll', scrollListener);
});

/**
 * Subscription form handlers
 */
const handleSubmit = async () => {
  isSubmitting.value = true;

  try {
    const response = await $fetch(`${config.public.WORKER_API}/api/subscribe`, {
      method: 'POST',
      body: { email: email.value },
    });

    if (!response.success) {
      throw new Error(response.message || 'Failed to subscribe');
    }

    email.value = '';
    hasSubscribed.value = true;
    localStorage.setItem(STORAGE_KEY, 'true');
  } catch (error) {
    alert('Something went wrong, please try again.');
    console.error('Subscription error:', error);
  } finally {
    isSubmitting.value = false;
  }
};

const handleChangeEmail = () => {
  hasSubscribed.value = false;
  localStorage.removeItem(STORAGE_KEY);
};
</script>

<template>
  <!-- Loading state -->
  <div v-if="isLoading" class="py-12 text-center">
    <p class="text-xl">Loading brief...</p>
  </div>

  <!-- Not found state -->
  <div v-else-if="notFound" class="py-12 text-center">
    <h2 class="text-2xl font-bold mb-4">Brief not found</h2>
    <p class="mb-6">We couldn't find the brief you're looking for.</p>
    <NuxtLink to="/briefs" class="underline">View all briefs</NuxtLink>
  </div>

  <!-- Brief content -->
  <template v-else-if="briefData">
    <!-- Reading progress bar -->
    <div class="fixed top-0 left-0 w-full h-1 z-50">
      <div class="h-full bg-black transition-all duration-150 ease-out" :style="{ width: `${readingProgress}%` }" />
    </div>

    <div>
      <header class="mb-8">
        <h1 class="text-4xl font-bold mb-3">
          {{ briefData.title.toLowerCase() }}
        </h1>
        <div class="flex text-sm text-gray-600 items-center space-x-2">
          <time>{{ briefData.date?.month.toLowerCase() }} {{ briefData.date?.day }}, {{ briefData.date?.year }}</time>
          <span>•</span>
          <p>{{ estimateReadingTime(briefData.content) }} min read</p>
        </div>
      </header>

      <article class="prose" v-html="$md.render(briefData.content)" />

    <div class="mt-16 mb-8">
      <div class="h-px w-full bg-gray-300 mb-8" />
      <div class="flex flex-col text-center gap-8">
        <!-- Brief stats -->
        <div class="grid grid-cols-2 gap-y-6 gap-x-12 text-sm">
          <div>
            <p class="text-gray-600 mb-1">total articles</p>
            <p class="font-bold text-base">{{ briefData.totalArticles || '-' }}</p>
          </div>
          <div>
            <p class="text-gray-600 mb-1">total sources</p>
            <p class="font-bold text-base">{{ briefData.totalSources || '-' }}</p>
          </div>
          <div>
            <p class="text-gray-600 mb-1">used articles</p>
            <p class="font-bold text-base">{{ briefData.usedArticles || '-' }}</p>
          </div>
          <div>
            <p class="text-gray-600 mb-1">used sources</p>
            <p class="font-bold text-base">{{ briefData.usedSources || '-' }}</p>
          </div>
        </div>

        <div class="text-sm">
          <p class="text-gray-600 mb-1">final brief generated by</p>
          <p class="font-bold text-base">{{ briefData.model_author }}</p>
        </div>

        <!-- Subscription area -->
        <div v-if="!hasSubscribed" class="mt-4 pt-8 border-t border-gray-300">
          <p class="text-gray-800 mb-4">Want this brief in your inbox? Sign up for updates</p>
          <form @submit.prevent="handleSubmit" class="flex max-w-md mx-auto">
            <input
              v-model="email"
              type="email"
              placeholder="your@email.com"
              required
              class="flex-grow px-4 py-2 border border-r-0 border-gray-300 focus:outline-none focus:ring-1 focus:ring-black"
            />
            <button
              type="submit"
              class="bg-black text-white px-4 py-2 font-medium hover:bg-gray-800 transition-colors"
              :disabled="isSubmitting"
            >
              {{ isSubmitting ? 'Sending...' : 'Subscribe' }}
            </button>
          </form>
        </div>
        <div v-else class="mt-4 pt-8 border-t border-gray-300 text-sm">
          <p class="text-gray-800">You're subscribed to our updates!</p>
          <button @click="handleChangeEmail" class="text-gray-500 underline mt-2 text-xs">Change email</button>
        </div>
      </div>
    </div>
  </div>
  </template>
</template>
