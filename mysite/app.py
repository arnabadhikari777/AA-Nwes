from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import requests
import sqlite3
import os
import time
from deep_translator import GoogleTranslator

app = Flask(__name__)
# Secret key for session (required for the login system)
# Uses an environment variable if set (recommended on PythonAnywhere),
# otherwise falls back to the original default so nothing breaks locally.
app.secret_key = os.environ.get("SECRET_KEY", "my_super_secret_key_for_admin")

# Your NewsData.io API KEY (the previous one is kept)
api_key = os.environ.get("NEWSDATA_API_KEY", "pub_1b0ed4a2b36d465c8c4d51b3f3161029")

# Absolute path to the database file, so the app works correctly
# no matter what the current working directory is (important on PythonAnywhere).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'news.db')

# 1. Function to create the database and tables
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # url is not kept UNIQUE here, and a content column has been added
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source TEXT,
            image_url TEXT,
            url TEXT,
            category TEXT,
            content TEXT
        )
    ''')

    # Categories table, so the admin can create/manage categories from the panel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE,
            label TEXT
        )
    ''')

    # Seed the default categories only if the table is empty (first run),
    # so existing sites keep exactly the same categories as before.
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        default_categories = [
            ('all', 'All / Home'),
            ('business', 'Business'),
            ('technology', 'Technology'),
            ('sports', 'Sports'),
            ('entertainment', 'Entertainment'),
            ('health', 'Health'),
            ('science', 'Science'),
        ]
        cursor.executemany("INSERT INTO categories (slug, label) VALUES (?, ?)", default_categories)

    conn.commit()
    conn.close()

    # Remove any duplicate news that may already be in the database
    # (e.g. from before this fix), keeping the oldest copy of each title.
    dedupe_existing_news()

    # Enforce uniqueness by title (case-insensitive) at the database level.
    # This is the real fix for duplicates: even if the dedup check in the
    # fetch functions is somehow bypassed (e.g. two server workers running
    # at the same time), SQLite itself will now refuse a second copy.
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_news_title_unique
            ON news (title COLLATE NOCASE)
        ''')
        conn.commit()
    except sqlite3.IntegrityError:
        # In case dedupe_existing_news() missed something, don't crash the app;
        # duplicates just won't be fully blocked until the next cleanup pass.
        pass
    conn.close()

# Removes duplicate news rows (same title, case-insensitive), keeping the
# earliest one (lowest id) of each. Safe to run every time the app starts.
def dedupe_existing_news():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM news ORDER BY id ASC")
    rows = cursor.fetchall()

    seen_titles = set()
    duplicate_ids = []
    for news_id, title in rows:
        key = (title or '').strip().lower()
        if key in seen_titles:
            duplicate_ids.append(news_id)
        else:
            seen_titles.add(key)

    if duplicate_ids:
        cursor.executemany("DELETE FROM news WHERE id=?", [(i,) for i in duplicate_ids])
        conn.commit()
        print(f"Removed {len(duplicate_ids)} duplicate news rows.")

    conn.close()
def get_all_categories():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT slug, label FROM categories ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{"slug": r[0], "label": r[1]} for r in rows]

# 2. Function to fetch general news and save it to the database when the server starts
def update_news_in_db():
    url = f"https://newsdata.io/api/1/news?apikey={api_key}&country=in"
    try:
        response = requests.get(url)
        data = response.json()
        print("Total General News from API:", len(data.get('results', [])))

        if data.get('status') == 'success':
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            for article in data.get('results', []):
                title = article.get('title')
                source = article.get('source_id')
                image_url = article.get('image_url')
                news_url = article.get('link')

               # Logic to translate the title into English
                # New code:
                if title:
                    try:
                        title = GoogleTranslator(source='auto', target='en').translate(title)
                    except:
                        pass

                if title and news_url:
                    normalized_title = title.strip().lower()
                    cursor.execute(
                        "SELECT id FROM news WHERE url=? OR LOWER(TRIM(title))=?",
                        (news_url, normalized_title)
                    )
                    if not cursor.fetchone():
                        # INSERT OR IGNORE: if the title already exists (caught by the
                        # unique index) this quietly does nothing instead of erroring out
                        cursor.execute('''
                            INSERT OR IGNORE INTO news (title, source, image_url, url, category, content)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (title, source, image_url, news_url, 'all', ''))
            conn.commit()
            conn.close()
            print("Updated 'all' news in database successfully.")
        else:
            print("API Error:", data.get('results'))
    except Exception as e:
        print("There was a problem updating the database:", e)

# The database will be created and updated as soon as the server starts
init_db()
update_news_in_db()

# Tracks when 'all' news was last pulled from the API, so /get_news can
# auto-refresh itself once an hour has passed, without needing a server restart.
last_all_update_time = time.time()

# 3. Route to display the main website
@app.route('/')
def home():
    return render_template('news_portal_frontend.html')

# 4. Route to fetch news from the database and send it to the website (for All / Home)
# Supports infinite scrolling via ?offset= and ?limit=, and auto-refreshes
# from the API on its own once an hour has passed (no server restart needed).
@app.route('/get_news')
def get_news():
    global last_all_update_time

    # If it's been more than an hour since the last automatic pull, fetch fresh
    # news from the API now, right here in the request, before answering.
    if time.time() - last_all_update_time > 3600:
        update_news_in_db()
        last_all_update_time = time.time()

    limit = request.args.get('limit', default=20, type=int)
    offset = request.args.get('offset', default=0, type=int)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, source, image_url, url, content FROM news WHERE category='all' ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    rows = cursor.fetchall()
    conn.close()

    news_list = []
    for row in rows:
        news_list.append({
            "id": row[0],
            "title": row[1],
            "source": {"name": row[2]},
            "urlToImage": row[3],
            "url": row[4]
        })

    return jsonify(news_list)

# 5. Route to fetch news by category (will fetch from API and save to database)
# Supports infinite scrolling via ?offset= and ?limit=
@app.route('/category/<cat_name>')
def get_category_news(cat_name):
    limit = request.args.get('limit', default=20, type=int)
    offset = request.args.get('offset', default=0, type=int)

    # Only hit the external API on the first page of a category (offset 0),
    # so scrolling further down doesn't re-fetch from the internet every time.
    if offset == 0:
        url = f"https://newsdata.io/api/1/news?apikey={api_key}&country=in&category={cat_name}"

        try:
            response = requests.get(url)
            data = response.json()
            print(f"Total {cat_name} News from API:", len(data.get('results', [])))

            if data.get('status') == 'success':
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()

                for article in data.get('results', []):
                    title = article.get('title')
                    source = article.get('source_id')
                    image_url = article.get('image_url')
                    news_url = article.get('link')
# Code to translate the title into English
                    # New code:
                    if title:
                        try:
                            title = GoogleTranslator(source='auto', target='en').translate(title)
                        except:
                            pass

                    if title and news_url:
                        normalized_title = title.strip().lower()
                        cursor.execute(
                            "SELECT id FROM news WHERE url=? OR LOWER(TRIM(title))=?",
                            (news_url, normalized_title)
                        )
                        if not cursor.fetchone():
                            cursor.execute('''
                                INSERT OR IGNORE INTO news (title, source, image_url, url, category, content)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (title, source, image_url, news_url, cat_name, ''))
                conn.commit()
                conn.close()
        except Exception as e:
            print("Problem fetching category news from API:", e)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, title, source, image_url, url, content FROM news WHERE category=? ORDER BY id DESC LIMIT ? OFFSET ?',
        (cat_name, limit, offset)
    )
    rows = cursor.fetchall()
    conn.close()

    news_list = []
    for row in rows:
        news_list.append({
            "id": row[0],
            "title": row[1],
            "source": {"name": row[2]},
            "urlToImage": row[3],
            "url": row[4]
        })

    return jsonify(news_list)

# Public route: returns all categories as JSON, used by the frontend to build the menu
@app.route('/get_categories')
def get_categories():
    return jsonify(get_all_categories())

# 6. Login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'ceo@2026':  # Your password is here
            session['is_admin'] = True
            return redirect(url_for('add_news'))
        else:
            error = "Wrong password! Please try again."
    return render_template('login.html', error=error)

# 7. Logout
@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('home'))

# 8. Admin panel (for manually writing news)
@app.route('/add_news', methods=['GET', 'POST'])
def add_news():
    # Login check: if not logged in, redirect straight to the login page
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    message = ""
    if request.method == 'POST':
        title = request.form.get('title')
        source = request.form.get('source')
        image_url = request.form.get('image_url')
        content = request.form.get('content')
        category = request.form.get('category')

        # If no image is given, a default image will be used
        if not image_url:
            image_url = "https://dummyimage.com/600x300/131921/ff9d00.png&text=A.A.News"

        if title and content:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                # URL is being kept empty, because we will show the content
                cursor.execute('''
                    INSERT INTO news (title, source, image_url, url, category, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (title, source, image_url, "", category, content))
                conn.commit()
                conn.close()
                message = "The news has been successfully published on the website!"
            except Exception as e:
                message = f"An error occurred: {e}"
        else:
            message = "News title and detailed content are mandatory!"

    return render_template('add_news.html', message=message, categories=get_all_categories())

# 8b. Admin Dashboard - shows every news item with Edit / Delete buttons,
# plus category management (add / delete categories)
@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, source, category FROM news ORDER BY id DESC')
    news_rows = cursor.fetchall()
    conn.close()

    news_items = [
        {"id": r[0], "title": r[1], "source": r[2], "category": r[3]}
        for r in news_rows
    ]

    return render_template(
        'admin_dashboard.html',
        news_items=news_items,
        categories=get_all_categories()
    )

# 8c. Edit an existing news item
@app.route('/admin/edit/<int:news_id>', methods=['GET', 'POST'])
def edit_news(news_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if request.method == 'POST':
        title = request.form.get('title')
        source = request.form.get('source')
        image_url = request.form.get('image_url')
        content = request.form.get('content')
        category = request.form.get('category')

        if not image_url:
            image_url = "https://dummyimage.com/600x300/131921/ff9d00.png&text=A.A.News"

        try:
            cursor.execute('''
                UPDATE news
                SET title=?, source=?, image_url=?, content=?, category=?
                WHERE id=?
            ''', (title, source, image_url, content, category, news_id))
            conn.commit()
            conn.close()
            return redirect(url_for('admin_dashboard'))
        except sqlite3.IntegrityError:
            conn.close()
            # Happens if the new title matches another existing news item's title
            error = "A news item with this exact title already exists. Please change the title slightly."
            news_item = {
                "id": news_id, "title": title, "source": source,
                "image_url": image_url, "url": "", "category": category, "content": content
            }
            return render_template('edit_news.html', news=news_item, categories=get_all_categories(), error=error)

    cursor.execute('SELECT id, title, source, image_url, url, category, content FROM news WHERE id=?', (news_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "News not found!", 404

    news_item = {
        "id": row[0], "title": row[1], "source": row[2],
        "image_url": row[3], "url": row[4], "category": row[5], "content": row[6]
    }

    return render_template('edit_news.html', news=news_item, categories=get_all_categories())

# 8d. Delete a news item
@app.route('/admin/delete/<int:news_id>', methods=['POST'])
def delete_news(news_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM news WHERE id=?', (news_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

# 8e. Add a new category
@app.route('/admin/add_category', methods=['POST'])
def add_category():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    label = (request.form.get('label') or '').strip()
    if label:
        # Build a simple slug: lowercase, spaces -> hyphens, only letters/numbers/hyphens kept
        slug = ''.join(c if c.isalnum() else '-' for c in label.lower()).strip('-')
        while '--' in slug:
            slug = slug.replace('--', '-')

        if slug:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO categories (slug, label) VALUES (?, ?)", (slug, label))
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # category with this slug already exists, ignore silently
            conn.close()

    return redirect(url_for('admin_dashboard'))

# 8f. Delete a category (any news in it is moved back to 'all' so nothing is lost)
@app.route('/admin/delete_category/<slug>', methods=['POST'])
def delete_category(slug):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    # The 'all' category is the site's default feed and cannot be removed
    if slug != 'all':
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE news SET category='all' WHERE category=?", (slug,))
        cursor.execute("DELETE FROM categories WHERE slug=?", (slug,))
        conn.commit()
        conn.close()

    return redirect(url_for('admin_dashboard'))

# 9. Page for reading self-written news
@app.route('/read/<int:news_id>')
def read_news(news_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT title, source, image_url, content FROM news WHERE id=?', (news_id,))
    news = cursor.fetchone()
    conn.close()

    if news:
        return render_template('read_news.html', news=news)
    else:
        return "News not found!", 404

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy.html')

if __name__ == '__main__':
    # This block only runs when you start the app locally with `python app.py`.
    # PythonAnywhere does NOT use this block — it imports the `app` object
    # directly through the WSGI configuration file instead.
    app.run(debug=True)