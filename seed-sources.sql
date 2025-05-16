INSERT INTO sources (url, name, scrape_frequency, paywall, category) VALUES
('https://www.theverge.com/rss/index.xml', 'The Verge', 2, false, 'tech'),
('https://rss.nytimes.com/services/xml/rss/nyt/World.xml', 'NYTimes World', 1, true, 'news'),
('https://feeds.nbcnews.com/nbcnews/public/world', 'NBC News World', 1, false, 'news'),
('https://feeds.bbci.co.uk/news/world/rss.xml', 'BBC News World', 1, false, 'news'),
('https://www.aljazeera.com/xml/rss/all.xml', 'Al Jazeera', 1, false, 'news'),
('https://www.ft.com/world?format=rss', 'Financial Times World', 2, true, 'finance'),
('https://feeds.skynews.com/feeds/rss/world.xml', 'Sky News World', 2, false, 'news'),
('https://www.economist.com/international/rss.xml', 'The Economist International', 3, true, 'finance'),
('https://www.reuters.com/world/rss/', 'Reuters World', 1, false, 'news'),
('https://www.cnbc.com/id/100727362/device/rss/rss.html', 'CNBC World', 2, false, 'finance')
ON CONFLICT (url) DO NOTHING;