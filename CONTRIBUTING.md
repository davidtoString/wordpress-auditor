# Contributing to WP Auditor

Thank you for considering contributing to WP Auditor! Here are guidelines to get you set up quickly and cleanly.

---

## 🛠️ Development Setup

WP Auditor uses Docker Compose for full local development.

1. **Fork and Clone the repository:**
   ```bash
   git clone https://github.com/your-username/wordpress-auditor.git
   cd wordpress-auditor
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   ```

3. **Start services:**
   ```bash
   docker compose up --build
   ```

   - **Frontend:** `http://localhost:3001` (hot-reloaded Vite server)
   - **Backend API:** `http://localhost:8000` (auto-reloaded FastAPI server)
   - **Interactive API Docs (Swagger):** `http://localhost:8000/docs`

---

## 🧩 Adding a New Audit Module

To add a new audit check:

1. Create a new auditor in `backend/app/auditors/your_module.py` extending `BaseAuditor`.
2. Implement the `async def run(self) -> AuditModuleResult:` method.
3. Register the auditor in `backend/app/scheduler.py` (`auditors` array and `MODULE_WEIGHTS`).
4. Register the module title and Lucide icon in `frontend/src/lib/utils.ts` (`moduleDisplayName` & `moduleIcon`).

---

## 🧪 Testing

Run backend tests or module imports:
```bash
docker exec wp_auditor_backend python -m pytest
```

Check frontend TypeScript compilation:
```bash
docker exec wp_auditor_frontend npm run build
```

---

## 🚀 Submitting a Pull Request

1. Create a feature branch: `git checkout -b feature/my-new-feature`
2. Commit your changes: `git commit -m 'Add awesome new auditor'`
3. Push to your branch: `git push origin feature/my-new-feature`
4. Open a Pull Request on GitHub with a description of the changes.
