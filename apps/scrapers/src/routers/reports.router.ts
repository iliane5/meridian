import { Hono } from 'hono';
import { z } from 'zod';
import type { HonoEnv } from '../app';
import { $reports, desc, getDb } from '@meridian/database';
import { hasValidAuthToken } from '../lib/utils';
import { zValidator } from '@hono/zod-validator';
import { cors } from 'hono/cors';

const route = new Hono<HonoEnv>()
  // Enable CORS for API endpoints
  .use('/*', cors({
    origin: '*',
    allowHeaders: ['Authorization', 'Content-Type'],
    allowMethods: ['GET', 'POST', 'OPTIONS'],
    maxAge: 86400,
  }))
  .get('/all', async c => {
    try {
      const db = getDb(c.env.DATABASE_URL);
      const reports = await db.query.$reports.findMany();

      // Process reports to add date and slug
      const processedReports = reports
        .map(report => {
          // Ensure createdAt is a valid Date object and work with UTC
          const createdAt = report.createdAt ? new Date(report.createdAt) : new Date();

          // Use UTC methods to avoid timezone issues
          const monthNames = [
            'January',
            'February',
            'March',
            'April',
            'May',
            'June',
            'July',
            'August',
            'September',
            'October',
            'November',
            'December',
          ];
          const month = monthNames[createdAt.getUTCMonth()];
          const day = createdAt.getUTCDate();
          const year = createdAt.getUTCFullYear();

          return {
            ...report,
            date: { month, day, year },
            slug: `${month.toLowerCase()}-${day}-${year}`,
          };
        })
        .sort((a, b) => {
          const dateA = a.createdAt ? new Date(a.createdAt).getTime() : 0;
          const dateB = b.createdAt ? new Date(b.createdAt).getTime() : 0;
          return dateB - dateA;
        });

      return c.json(processedReports);
    } catch (error) {
      console.error('Error fetching reports', error);
      return c.json({ error: 'Failed to fetch reports' }, 500);
    }
  })
  .get('/last-report', async c => {
    // check auth token
    const hasValidToken = hasValidAuthToken(c);
    if (!hasValidToken) {
      return c.json({ error: 'Unauthorized' }, 401);
    }

    try {
      const report = await getDb(c.env.DATABASE_URL).query.$reports.findFirst({
        orderBy: desc($reports.createdAt),
      });
      if (report === undefined) {
        return c.json({ error: 'No report found' }, 404);
      }

      return c.json(report);
    } catch (error) {
      console.error('Error fetching last report', error);
      return c.json({ error: 'Failed to fetch last report' }, 500);
    }
  })
  .post(
    '/report',
    zValidator(
      'json',
      z.object({
        title: z.string(),
        content: z.string(),
        totalArticles: z.number(),
        totalSources: z.number(),
        usedArticles: z.number(),
        usedSources: z.number(),
        tldr: z.string(),
        createdAt: z.coerce.date(),
        model_author: z.string(),
        clustering_params: z.object({
          umap: z.object({
            n_neighbors: z.number(),
          }),
          hdbscan: z.object({
            min_cluster_size: z.number(),
            min_samples: z.number(),
            epsilon: z.number(),
          }),
        }),
      })
    ),
    async c => {
      // check auth token
      const hasValidToken = hasValidAuthToken(c);
      if (!hasValidToken) {
        return c.json({ error: 'Unauthorized' }, 401);
      }

      const body = c.req.valid('json');

      try {
        await getDb(c.env.DATABASE_URL).insert($reports).values(body);
      } catch (error) {
        console.error('Error inserting report', error);
        return c.json({ error: 'Failed to insert report' }, 500);
      }

      return c.json({ success: true });
    }
  );

export default route;
