<div align="center">

# 📰 A.A. News

### Your Trusted News Source

**Live Indian headlines · Category filters · Admin panel**

<br>

[![Live Demo](https://img.shields.io/badge/Live_Demo-PythonAnywhere-1D9FD7?style=for-the-badge&logo=python&logoColor=white)](https://arnabadhikari125117y.pythonanywhere.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)

</div>

---

## Overview

**A.A. News** is a full-featured news portal that brings the latest **Indian headlines** to one clean, modern website.

It automatically pulls live stories from the **NewsData.io** API, stores them in **SQLite**, and serves them with category filters, infinite scroll, and a beautiful newspaper-inspired UI. An admin panel lets the team publish original articles, manage categories, and keep the feed fresh.

> This project is a **joint effort** by two friends who love building things together.

**Live site:** [arnabadhikari125117y.pythonanywhere.com](https://arnabadhikari125117y.pythonanywhere.com)

---

## Authors

| Name | Role | GitHub |
|------|------|--------|
| **Arnab Adhikari** | Co-creator & Developer | [arnabadhikari777](https://github.com/arnabadhikari777) |
| **Anubhab Dutta** | Co-creator & Developer | [duttaanubhab777-code](https://github.com/duttaanubhab777-code) |

Made with friendship, late-night debugging, and a shared love for clean code.

---

## Features

- **Live Indian news** fetched from NewsData.io (`country=in`)
- **Category filters** — All, Business, Technology, Sports, Entertainment, Health, Science
- **Infinite scroll** — load more headlines as you scroll
- **Auto-refresh** — background pull from the API so the feed stays current
- **Admin panel** — login, add / edit / delete custom articles
- **Custom categories** — create or remove categories from the dashboard
- Image support + clean card layout
- Mobile-friendly, newspaper-style design
- Session-based admin authentication
- SQLite database with de-duplication of articles

---

## Tech Stack

| Layer       | Technology                          |
|-------------|-------------------------------------|
| Backend     | Python, Flask                       |
| Database    | SQLite                              |
| News API    | [NewsData.io](https://newsdata.io)  |
| Translation | deep-translator (GoogleTranslator)  |
| Frontend    | HTML5, CSS3, Vanilla JavaScript     |
| Hosting     | PythonAnywhere                      |

---

## Project Structure

```text
AA_News/
└── mysite/
    ├── app.py                          # Main Flask application
    ├── news.db                         # SQLite database
    └── templates/
        ├── news_portal_frontend.html   # Public homepage
        ├── read_news.html              # Full article view
        ├── admin_dashboard.html        # Admin panel
        ├── add_news.html               # Add custom news
        ├── edit_news.html              # Edit existing news
        ├── login.html                  # Admin login
        ├── about.html                  # About page
        └── privacy.html                # Privacy policy
```

---

## Getting Started (Local)

### Prerequisites

- Python **3.10+**
- A free [NewsData.io](https://newsdata.io) API key

### 1. Clone & enter the project

```bash
git clone https://github.com/arnabadhikari777/AA_News.git
cd AA_News/mysite
```

### 2. Install dependencies

```bash
pip install -r ../requirements.txt
```

### 3. Create your private .env file

```bash
cp .env.example .env
# then open .env and fill in SECRET_KEY, NEWSDATA_API_KEY and ADMIN_PASSWORD
```

The `.env` file is private and is never uploaded to GitHub.

### 4. Run the app

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## Admin Access

1. Visit `/login`
2. Log in with the `ADMIN_PASSWORD` you set in your `.env` file
3. From the dashboard you can:
   - Publish original articles
   - Edit or delete any news item
   - Add / remove categories

---

## How it works

1. On startup the app creates the SQLite tables and seeds default categories.
2. It calls the NewsData.io API for India (`country=in`) and stores unique articles.
3. The frontend requests `/get_news` (or `/category/<name>`) with `offset` & `limit` for infinite scroll.
4. Every so often the server automatically refreshes the "All" feed from the API.
5. Admins can inject their own stories which appear alongside the live feed.

---

## Roadmap

- [ ] Dark mode toggle
- [ ] Bookmark / save articles (localStorage)
- [ ] Search bar across all headlines
- [ ] Multi-language support expansion
- [ ] Better image fallback & lazy loading

---

## License

This project is open source. Feel free to fork, learn from, and improve it.

---

<div align="center">

**Built with ❤️ by Arnab Adhikari & Anubhab Dutta**

[Live Demo](https://arnabadhikari125117y.pythonanywhere.com) · [Arnab's GitHub](https://github.com/arnabadhikari777) · [Anubhab's GitHub](https://github.com/duttaanubhab777-code)

</div>
