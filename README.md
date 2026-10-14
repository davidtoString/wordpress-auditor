# 🔍 WP Auditor

<p align="center">
  <img src="https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/globe.svg" width="80" height="80" alt="WP Auditor Logo" />
</p>

<p align="center">
  <b>Automated, site-wide WordPress audit platform powered by Docker, Unlighthouse, Advertools, and AI.</b><br>
  Built for WordPress agencies, SEO consultants, and multi-site operators running Elementor Pro, RankMath Pro, and custom setups.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/Node.js-22_LTS-339933?logo=nodedotjs&logoColor=white" alt="Node.js 22" />
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL 16" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT" />
</p>

---

## 🌟 Key Highlights

- **12 Comprehensive Audit Engines:** Tests SEO, site-wide performance, technical architecture, security, and WordPress health in one concurrent run.
- **Site-Wide Unlighthouse Engine:** Crawls all routes across the entire domain using headless Chromium, generating interactive Lighthouse reports.
- **Deep Technical SEO via Advertools:** Advanced robots.txt user-agent simulation (`Googlebot`, `Bingbot`), recursive sitemap index parsing, and SERP snippet validation.
- **AI Executive Action Plans:** Transforms audit findings into prioritized developer checklists using your own **OpenAI (GPT-4o)** or **Google Gemini (1.5 Pro)** API keys.
- **Scheduled Automated Audits:** Built-in APScheduler cron engine per site (e.g., `0 6 * * *` daily at 6 AM).
- **Transactional Email Alerts:** Branded HTML alert emails via **Resend** triggered whenever site health drops below thresholds.
- **JWT Multi-User Authentication:** Role-based access control (Admin & Viewer) with self-service password updates.
- **Zero-Config Docker Deployment:** Single `docker compose up -d` boots PostgreSQL, FastAPI, Chromium, Node 22, and the React dashboard.

---

## 🔬 Audit Modules & Scoring Breakdown

| Module | Weight | Core Checks & Capabilities |
| :--- | :---: | :--- |
| **Unlighthouse (Site-Wide)** | **20%** | Full-site multi-page crawl running Google Lighthouse across all routes (Performance, Accessibility, Best Practices, SEO). |
| **Technical SEO (Advertools)** | **15%** | Recursive XML sitemap parsing (`sitemap_index.xml`, `wp-sitemap.xml`), robots.txt Googlebot rule testing, SERP title length truncation check, and Elementor template leaks. |
| **On-Page SEO** | **15%** | Title tag & meta description length, OpenGraph tags, canonical tags, single H1 hierarchy, and indexing directives. |
| **PageSpeed & Web Vitals** | **15%** | Mobile (60%) & Desktop (40%) Google PageSpeed Insights API check: LCP, CLS, FCP, TTFB, and Speed Index. |
| **Security & Hardening** | **15%** | HTTPS redirect verification, HSTS, CSP, X-Frame-Options, XML-RPC exposure, and WP version leakage. |
| **Broken Links** | **10%** | Internal and external link crawl (up to 200 URLs), detecting 4xx/5xx errors, redirect chains (>2 hops), and loops. |
| **Schema & Structured Data** | **5%** | JSON-LD schema parsing for `LocalBusiness`, `WebSite`, `BreadcrumbList`, and `Article` entities. |
| **Cookie Consent & Privacy** | **5%** | Playwright headless browser check verifying if analytics or tracking cookies are set *before* user consent is given. |
| **NAP Consistency** | *Tracked* | Name, Address, and Phone number consistency cross-checked across Header, Footer, Contact page, and Schema. |
| **Image Optimization** | *Tracked* | Detection of oversized images (>500KB), missing alt tags, modern format usage (WebP/AVIF), and lazy loading. |
| **WordPress Health** | *Tracked* | WP REST API namespace exposure, user enumeration via `/?author=1`, readme.html visibility, and debug errors. |
| **Redirects & Canonical** | *Tracked* | WWW vs non-WWW canonical resolution, trailing slash consistency, and 301 vs 302 permanent redirect evaluation. |

---

## 🚀 Quick Start (1 Minute)

### 1. Clone the repository
```bash
git clone https://github.com/your-username/wordpress-auditor.git
cd wordpress-auditor
```

### 2. Configure environment
```bash
cp .env.example .env
```
*(Optionally paste your OpenAI, Gemini, or Resend keys in `.env`, or configure them later directly in the web UI).*

### 3. Start with Docker Compose
```bash
docker compose up -d
```

### 4. Access the Dashboard
* **Web UI:** [`http://localhost:3001`](http://localhost:3001)
* **FastAPI Docs (Swagger):** [`http://localhost:8000/docs`](http://localhost:8000/docs)
* **Alternative API Docs (ReDoc):** [`http://localhost:8000/redoc`](http://localhost:8000/redoc)

#### Default Admin Credentials:
* **Email:** `admin@localhost`
* **Password:** `Admin@1234`
> ⚠️ **Important:** Change the default admin password immediately under **Settings → Profile**.

---

## ⚙️ Environment Configuration (`.env`)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `POSTGRES_USER` | `auditor` | PostgreSQL database user |
| `POSTGRES_PASSWORD` | `secret` | PostgreSQL database password |
| `POSTGRES_DB` | `wp_audits` | Database name |
| `SECRET_KEY` | *(Generate a random string)* | JWT signing secret |
| `AI_PROVIDER` | `openai` | Default AI provider (`openai` or `gemini`) |
| `OPENAI_API_KEY` | *(Optional)* | OpenAI key for GPT-4o action plans |
| `GEMINI_API_KEY` | *(Optional)* | Google AI Studio key for Gemini 1.5 Pro |
| `GOOGLE_PAGESPEED_API_KEY` | *(Optional)* | Google Cloud key for PageSpeed Insights API |
| `RESEND_API_KEY` | *(Optional)* | Resend transactional email key |
| `RESEND_FROM_EMAIL` | `audits@yourdomain.com`| Verified sender address for alerts |
| `ALERT_EMAIL` | `alerts@yourdomain.com` | Primary inbox for score-drop alerts |

> 💡 **Tip:** All API keys can be managed and tested live in the **Settings** view of the web UI with sensitive value masking.

---

## 🏗️ Architecture

```
wordpress-auditor/
├── docker-compose.yml           # Multi-container orchestration
├── .env.example                 # Configuration template
├── backend/                     # Python 3.12 + Node 22 + Chromium
│   ├── Dockerfile               # Dual-runtime container
│   ├── requirements.txt         # FastAPI, Advertools, Playwright, Scrapy
│   └── app/
│       ├── main.py              # Application entrypoint
│       ├── config.py            # Pydantic settings management
│       ├── database.py          # SQLAlchemy PostgreSQL engine
│       ├── models.py            # Database schemas
│       ├── scheduler.py         # APScheduler background runner
│       ├── auth/                # JWT auth, password hashing, RBAC
│       ├── api/                 # REST endpoints (sites, audits, users, settings)
│       ├── auditors/            # 12 concurrent audit modules
│       │   ├── unlighthouse.py  # Multi-page Lighthouse runner
│       │   ├── advertools_auditor.py # Technical SEO & sitemaps
│       │   └── ...
│       ├── ai/                  # OpenAI & Gemini summarizers
│       └── email/               # Resend transactional email client
├── frontend/                    # React 18 + Vite + Tailwind CSS
│   ├── Dockerfile
│   └── src/
│       ├── pages/               # Dashboard, Sites, Audits, Settings, Users
│       ├── components/          # ModuleCards, ScoreBadges, Charts
│       └── lib/                 # API client, Auth Context, utilities
└── postgres/
    └── init.sql                 # Initial schema setup
```

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!
Feel free to check out the [issues page](https://github.com/your-username/wordpress-auditor/issues) and read [`CONTRIBUTING.md`](CONTRIBUTING.md) to get started.
