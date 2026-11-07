# Frontend (Person 1)

Manager UI: exception queue, review screen (diff, clauses, validator badges, Approve/Edit/Reject), audit view.

## Phase 0 setup

```bash
# from repo root
npm create vite@latest frontend -- --template react-ts   # choose "Ignore files and continue" if prompted
cd frontend
npm install
npm install -D tailwindcss @tailwindcss/vite vitest @playwright/test openapi-typescript
npx shadcn@latest init
```

## API client and mock (needs `backend/openapi.json` from Person 2, due H3)

```bash
npx openapi-typescript ../backend/openapi.json -o src/api/schema.d.ts
npx @stoplight/prism-cli mock ../backend/openapi.json -p 4010   # fake API
```

Point the base URL at `http://localhost:4010` (mock) until the real API is ready (~H10), then `http://localhost:8000`.

## Phase checklist

- [ ] P0 app scaffold, client generation, Prism mock
- [ ] P1 queue page with filters (type, status)
- [ ] P2 review screen (diff, clauses, validator badges, actions)
- [ ] P3 audit timeline, retried/fallback/escalated badges, escalated tab
- [ ] P4 Vitest component tests, Playwright end-to-end test
- [ ] P5 slide 2, demo recording
