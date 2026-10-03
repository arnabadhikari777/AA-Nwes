-- AA News migration 001 (additive only: no DROP, no DELETE, no renames).
-- Run ONLY through tools/migrate.py, which backs up first and verifies row counts.
ALTER TABLE news ADD COLUMN description TEXT;
ALTER TABLE news ADD COLUMN author TEXT;
ALTER TABLE news ADD COLUMN external_id TEXT;
ALTER TABLE news ADD COLUMN published_at TEXT;
ALTER TABLE news ADD COLUMN created_at TEXT;
ALTER TABLE news ADD COLUMN updated_at TEXT;
ALTER TABLE news ADD COLUMN publish_at TEXT;
ALTER TABLE news ADD COLUMN status TEXT NOT NULL DEFAULT 'published';
ALTER TABLE news ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0;
ALTER TABLE news ADD COLUMN is_breaking INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_news_category ON news(category, id DESC);
CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);
CREATE INDEX IF NOT EXISTS idx_news_url ON news(url);
CREATE INDEX IF NOT EXISTS idx_news_external_id ON news(external_id);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);
CREATE INDEX IF NOT EXISTS idx_news_flags ON news(is_featured, is_breaking);
CREATE TABLE IF NOT EXISTS article_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    viewed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_views_time ON article_views(viewed_at);
CREATE INDEX IF NOT EXISTS idx_views_article ON article_views(article_id, viewed_at);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT,
    trigger TEXT, status TEXT,
    api_calls INTEGER DEFAULT 0, fetched INTEGER DEFAULT 0,
    new_saved INTEGER DEFAULT 0, duplicates INTEGER DEFAULT 0, invalid INTEGER DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, action TEXT NOT NULL, detail TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
    title, description, content, content='news', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS news_ai AFTER INSERT ON news BEGIN
  INSERT INTO news_fts(rowid,title,description,content) VALUES (new.id,new.title,new.description,new.content);
END;
CREATE TRIGGER IF NOT EXISTS news_ad AFTER DELETE ON news BEGIN
  INSERT INTO news_fts(news_fts,rowid,title,description,content) VALUES('delete',old.id,old.title,old.description,old.content);
END;
CREATE TRIGGER IF NOT EXISTS news_au AFTER UPDATE ON news BEGIN
  INSERT INTO news_fts(news_fts,rowid,title,description,content) VALUES('delete',old.id,old.title,old.description,old.content);
  INSERT INTO news_fts(rowid,title,description,content) VALUES (new.id,new.title,new.description,new.content);
END;
INSERT INTO news_fts(news_fts) VALUES('rebuild');
