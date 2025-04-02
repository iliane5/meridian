import { date, z } from 'zod';

const reportValidator = z.object({
  id: z.number(),
  title: z.string(),
  content: z.string(),
  slug: z.string(),
  createdAt: z.coerce.date(),
  date: z.object({ month: z.string(), day: z.number(), year: z.number() }),
  totalArticles: z.number(),
  usedArticles: z.number(),
  totalSources: z.number(),
  usedSources: z.number(),
  model_author: z.string(),
});

export async function fetchReports() {
  const config = useRuntimeConfig();
  const response = await $fetch(`${config.public.WORKER_API}/api/reports/all`);
  const reports = z.array(reportValidator).parse(response);
  return reports;
}

export const useReports = () => useState('reports', () => [] as z.infer<typeof reportValidator>[]);

export const useReport = (id: number) => {
  const reports = useReports();
  return computed(() => reports.value.find(report => report.id === id));
};

export function getReportBySlug(slug: string) {
  const reports = useReports();
  const match = reports.value.find(report => report.slug === slug);
  if (match === undefined) {
    throw createError({
      statusCode: 404,
      statusMessage: 'Report not found',
    });
  }
  return toRef(match);
}
