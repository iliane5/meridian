import tailwindcss from '@tailwindcss/vite';
import { env } from 'node:process';

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  app: {
    head: {
      htmlAttrs: { lang: 'en' },
      link: [
        {
          rel: 'icon',
          type: 'image/png',
          href: '/favicon.ico',
        },
      ],
    },
  },

  compatibilityDate: '2024-11-01',
  devtools: { enabled: true },
  css: ['~/assets/css/main.css'],

  vite: {
    plugins: [tailwindcss()],
  },

  runtimeConfig: {
    public: {
      WORKER_API: 'https://meridian-production.alexandrenf.workers.dev/',
    },
  },

  devServer: {
    host: '0.0.0.0',
  },

  srcDir: 'src',

  // Configure for client-side rendering with static HTML
  ssr: false,
  nitro: {
    output: {
      publicDir: './dist',
    },
  },
});
