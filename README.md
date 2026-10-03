<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0e1a30,50:e6314b,100:f2a71b&height=220&section=header&text=A.A.%20News&fontSize=64&fontColor=ffffff&animation=fadeIn&fontAlignY=38&desc=Your%20Trusted%20News%20Source%20%E2%80%94%20India%20Headlines%20%C2%B7%20Categories%20%C2%B7%20Admin%20Panel&descAlignY=58&descSize=18" width="100%" alt="A.A. News banner"/>

[![Typing SVG](https://readme-typing-svg.demolab.com/?font=Fira+Code&weight=600&size=20&duration=3000&pause=900&color=E6314B&center=true&vCenter=true&multiline=true&repeat=true&width=720&height=90&lines=Live+Indian+headlines+from+NewsData.io;Category+filters+%C2%B7+Infinite+scroll;Admin+panel+for+custom+articles;Built+together+by+two+friends)](https://git.io/typing-svg)

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask"/>
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite"/>
  <img src="https://img.shields.io/badge/NewsData.io-API-E6314B?style=for-the-badge" alt="NewsData.io"/>
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white" alt="HTML5"/>
  <img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white" alt="CSS3"/>
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript"/>
</p>

<p>
  <a href="https://arnabadhikari125117y.pythonanywhere.com">
    <img src="https://img.shields.io/badge/Live_Demo-PythonAnywhere-1D9FD7?style=for-the-badge&logo=pythonanywhere&logoColor=white" alt="Live Demo"/>
  </a>
</p>

</div>

---

## 📖 Overview

**A.A. News** (AA_News) is a full-featured news portal that brings the latest **Indian headlines** to one clean, modern website.

It automatically pulls live stories from the **NewsData.io** API, stores them in **SQLite**, and serves them with category filters, infinite scroll, and a beautiful newspaper-inspired UI. An admin panel lets the team publish original articles, manage categories, and keep the feed fresh.

> This project is a **joint effort** by two friends who love building things together.

**Live site:** [arnabadhikari125117y.pythonanywhere.com](https://arnabadhikari125117y.pythonanywhere.com)

---

## 👥 Authors

| | Name | Role | GitHub |
|:---:|:---|:---|:---|
| 🧑‍💻 | **Arnab Adhikari** | Co-creator & Developer | [arnabadhikari777](https://github.com/arnabadhikari777) |
| 🧑‍💻 | **Anubhab Dutta** | Co-creator & Developer | [duttaanubhab777-code](https://github.com/duttaanubhab777-code) |

Made with friendship, late-night debugging, and a shared love for clean code.

---

## ✨ Features

- 📰 **Live Indian news** fetched from NewsData.io (country = `in`)
- 🗂️ **Category filters** — All, Business, Technology, Sports, Entertainment, Health, Science
- ♾️ **Infinite scroll** — load more headlines as you scroll
- 🔄 **Auto-refresh** — background pull from the API so the feed stays current
- ✍️ **Admin panel** — login, add / edit / delete custom articles
- 🏷️ **Custom categories** — create or remove categories from the dashboard
- 🖼️ Image support + clean card layout
- 📱 Mobile-friendly, newspaper-style design
- 🔐 Session-based admin authentication
- 🗄️ SQLite database with de-duplication of articles

---

## 🛠️ Tech Stack

| Layer       | Technology                          |
|-------------|-------------------------------------|
| Backend     | Python, Flask                       |
| Database    | SQLite                              |
| News API    | [NewsData.io](https://newsdata.io)  |
| Translation | deep-translator (GoogleTranslator)  |
| Frontend    | HTML5, CSS3, Vanilla JavaScript     |
| Hosting     | PythonAnywhere                      |

---

## 📁 Project Structure

```
AA_News/
└── mysite/
    ├── app.py                      # Main Flask application
    ├── news.db                     # SQLite database
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

## 🚀 Getting Started (Local)

### Prerequisites

- Python **3.10+**
- A free [NewsData.io](https://newsdata.io) API key

### 1 · Clone & enter the project

```bash
git clone https://github.com/arnabadhikari777/AA_News.git
cd AA_News/mysite
```

### 2 · Install dependencies

```bash
pip install flask requests deep-translator
```

### 3 · Set environment variables (recommended)

```bash
export NEWSDATA_API_KEY="your_newsdata_api_key"
export SECRET_KEY="a_strong_random_secret"
```

### 4 · Run the app

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## 🔐 Admin Access

- Visit `/login`
- Use the credentials configured in the app (or environment)
- From the dashboard you can:
  - Publish original articles
  - Edit or delete any news item
  - Add / remove categories

---

## 🌐 How it works

1. On startup the app creates the SQLite tables and seeds default categories.
2. It calls the NewsData.io API for India (`country=in`) and stores unique articles.
3. The frontend requests `/get_news` (or `/category/<name>`) with `offset` & `limit` for infinite scroll.
4. Every so often the server automatically refreshes the “All” feed from the API.
5. Admins can inject their own stories which appear alongside the live feed.

---

## 🗺️ Roadmap

- [ ] Dark mode toggle
- [ ] Bookmark / save articles (localStorage)
- [ ] Search bar across all headlines
- [ ] Multi-language support expansion
- [ ] Better image fallback & lazy loading

---

## 📄 License

This project is open source. Feel free to fork, learn from, and improve it.

---

<div align="center">

**Built with ❤️ by Arnab Adhikari & Anubhab Dutta**

[Live Demo](https://arnabadhikari125117y.pythonanywhere.com) · [Arnab’s GitHub](https://github.com/arnabadhikari777) · [Anubhab’s GitHub](https://github.com/duttaanubhab777-code)

</div>
