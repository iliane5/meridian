import tailwindcss from '@tailwindcss/vite';

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
      WORKER_API: 'http://localhost:8787',
    },
    DATABASE_URL: '',
  },

  devServer: {
    host: '0.0.0.0',
  },

  srcDir: 'src',

  nitro: {
    prerender: {
      autoSubfolderIndex: false,
    },
    output: {
      publicDir: './dist'
    }
  },
});
