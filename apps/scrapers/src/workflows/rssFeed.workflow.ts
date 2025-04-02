import { $articles, $sources, inArray } from '@meridian/database';
import { DomainRateLimiter } from '../lib/rateLimiter';
import { Env } from '../index';
import { getDb } from '../lib/utils';
import { parseRSSFeed } from '../lib/parsers';
import { WorkflowEntrypoint, WorkflowStep, WorkflowEvent, WorkflowStepConfig } from 'cloudflare:workers';
import { getRssFeedWithFetch } from '../lib/puppeteer';
import { startProcessArticleWorkflow } from './processArticles.workflow';
import { err, ok, ResultAsync } from 'neverthrow';

type Params = { force?: boolean };

const tierIntervals = {
  1: 60 * 60 * 1000, // Tier 1: Check every hour
  2: 4 * 60 * 60 * 1000, // Tier 2: Check every 4 hours
  3: 6 * 60 * 60 * 1000, // Tier 3: Check every 6 hours
  4: 24 * 60 * 60 * 1000, // Tier 4: Check every 24 hours
};

const dbStepConfig: WorkflowStepConfig = {
  retries: { limit: 3, delay: '1 second', backoff: 'linear' },
  timeout: '5 seconds',
};

// Takes in a rss feed URL, parses the feed & stores the data in our database.
export class ScrapeRssFeed extends WorkflowEntrypoint<Env, Params> {
  async run(_event: WorkflowEvent<Params>, step: WorkflowStep) {
    const db = getDb(this.env.DATABASE_URL);

    // Fetch all sources
    const feeds = await step.do('get feeds', dbStepConfig, async () => {
      let feeds = await db
        .select({
          id: $sources.id,
          lastChecked: $sources.lastChecked,
          scrape_frequency: $sources.scrape_frequency,
          url: $sources.url,
        })
        .from($sources);
      if (_event.payload.force === undefined || _event.payload.force === false) {
        feeds = feeds.filter(feed => {
          if (feed.lastChecked === null) {
            return true;
          }
          const lastCheckedTime =
            feed.lastChecked instanceof Date ? feed.lastChecked.getTime() : new Date(feed.lastChecked).getTime();
          const interval = tierIntervals[feed.scrape_frequency as keyof typeof tierIntervals] || tierIntervals[2];
          return Date.now() - lastCheckedTime >= interval;
        });
      }

      return feeds.map(e => ({ id: e.id, url: e.url }));
    });

    if (feeds.length === 0) {
      console.log('All feeds are up to date, exiting early...');
      return;
    }

    // Process feeds with rate limiting
    const now = Date.now();
    const oneWeekAgo = new Date(now - 7 * 24 * 60 * 60 * 1000);
    const allArticles: Array<{ sourceId: number; link: string; pubDate: Date | null; title: string }> = [];

    // Create rate limiter with RSS feed specific settings
    const rateLimiter = new DomainRateLimiter<{ id: number; url: string }>({
      maxConcurrent: 10,
      globalCooldownMs: 500,
      domainCooldownMs: 2000,
    });

    // Process feeds with rate limiting
    const feedResults = await rateLimiter.processBatch(feeds, step, async (feed, _domain) => {
      try {
        return await step.do(
          `scrape feed ${feed.id}`,
          {
            retries: { limit: 3, delay: '2 seconds', backoff: 'exponential' },
          },
          async () => {
            const feedPage = await getRssFeedWithFetch(feed.url);
            if (feedPage.isErr()) {
              console.error(`Error fetching feed ${feed.url}: ${feedPage.error.type}`);
              throw feedPage.error;
            }

            const feedArticles = await parseRSSFeed(feedPage.value);
            if (feedArticles.isErr()) {
              console.error(`Error parsing feed ${feed.url}: ${feedArticles.error.type}`);
              throw feedArticles.error;
            }

            return feedArticles.value
              .filter(({ pubDate }) => pubDate === null || pubDate > oneWeekAgo)
              .map(e => ({ ...e, sourceId: feed.id }));
          }
        );
      } catch (error) {
        console.error(`Error processing feed ${feed.id}: ${error}`);
        return [];
      }
    });

    // Flatten the results into allArticles
    feedResults.forEach(articles => {
      allArticles.push(...articles);
    });

    // Insert articles and update sources
    if (allArticles.length > 0) {
      await step.do('insert new articles', dbStepConfig, async () =>
        db
          .insert($articles)
          .values(
            allArticles.map(({ sourceId, link, pubDate, title }) => ({
              sourceId,
              url: link,
              title,
              publishDate: pubDate,
            }))
          )
          .onConflictDoNothing()
      );

      await step.do('update sources', dbStepConfig, async () =>
        db
          .update($sources)
          .set({ lastChecked: new Date() })
          .where(inArray($sources.id, Array.from(new Set(allArticles.map(({ sourceId }) => sourceId)))))
      );
    } else {
      // If no articles were found but we processed feeds, still update the lastChecked
      await step.do('update sources with no articles', dbStepConfig, async () =>
        db
          .update($sources)
          .set({ lastChecked: new Date() })
          .where(
            inArray(
              $sources.id,
              feeds.map(feed => feed.id)
            )
          )
      );
    }

    await step.do('trigger_article_processor', dbStepConfig, async () => {
      const workflow = await startProcessArticleWorkflow(this.env);
      if (workflow.isErr()) throw workflow.error;
      return workflow.value.id;
    });
  }
}

export async function startRssFeedScraperWorkflow(env: Env, params?: Params) {
  const workflow = await ResultAsync.fromPromise(env.SCRAPE_RSS_FEED.create({ id: crypto.randomUUID(), params }), e =>
    e instanceof Error ? e : new Error(String(e))
  );
  if (workflow.isErr()) {
    return err(workflow.error);
  }
  return ok(workflow.value);
}
