# Frontend architecture

The TierForge frontend is a single-page React app over the backend's REST API. It lets a user upload a CSV, follow a job's progress, score the job, and browse its stores. What it must do: [REQUIREMENTS.md](REQUIREMENTS.md#frontend-requirements). The API it calls: [architecture.md](architecture.md).

## Stack

| Concern | Choice | Notes |
| --- | --- | --- |
| Language | **TypeScript** (strict) | |
| Framework | **React 19**, function components and hooks | |
| Scaffolding | **Vite's `react-ts` template** (`npm create vite@latest frontend -- --template react-ts`) | not Create React App, which is deprecated |
| Build and dev server | **Vite 8**, with `@vitejs/plugin-react` | dev server on `http://localhost:5173` |
| UI components | **Mantine 9**: `core`, `hooks`, `form`, `dropzone`, `notifications` | |
| Styling | **CSS Modules** (`*.module.css`), plain CSS | plus Mantine's PostCSS preset for its breakpoints and functions |
| Routing | **React Router 8** | |
| Server state | **TanStack Query 5** | fetching, caching, polling, cache invalidation |
| HTTP | **axios** | one configured client |
| API types | **openapi-typescript** | generated from the backend's `/openapi.json` |
| Packages | **npm**, with `package-lock.json` committed | Node 22 |
| Lint | **oxlint** | Vite's template default |
| Tests | **Vitest**, **React Testing Library**, **MSW** | every API call mocked (see Testing) |

No Redux or other global store. Nearly all state comes from the API and lives in TanStack Query's cache. The rest is local component state, or URL search params for filters and paging.

## Layers

The core rule: **API calls, server state and UI are separate layers, and each only talks to the one below it.**

```
pages/        compose a screen: read route params, call hooks, lay out components
   │
components/   reusable UI: props in, callbacks out; no fetching
   │  (receive data from pages)
hooks/        TanStack Query hooks: caching, polling, invalidation; no axios
   │
api/          HTTP only: axios client + one typed function per endpoint; no React
   │
backend       http://localhost:8001/api
```

| Layer | Knows about | Never does |
| --- | --- | --- |
| `api/` | axios, URLs, request and response types | import React or TanStack Query |
| `hooks/` | `api/` functions, query keys, polling rules | import axios, or render anything |
| `components/` | props, Mantine, CSS Modules | fetch data, or read the URL |
| `pages/` | hooks, components, route params | call axios or `api/` functions directly |

So a change in how something is fetched (a URL, a header, polling) stays in `api/` or `hooks/`, and a change in how it looks stays in `components/`.

## Directory structure

```
frontend/
├── index.html
├── package.json             scripts: dev, build, preview, lint, typecheck, api:types
├── package-lock.json
├── vite.config.ts           dev server; "@/…" import alias for src/; Vitest settings
├── postcss.config.cjs       Mantine's PostCSS preset
├── tsconfig.app.json        strict mode; "@/*" path alias
├── .env.example             VITE_API_BASE_URL=http://localhost:8001 (copy to .env)
├── .env.test                the API URL used by tests (committed)
└── src/
    ├── main.tsx             global styles; mounts <App/>
    ├── App.tsx              <Providers> around the router
    ├── Providers.tsx        MantineProvider, Notifications, QueryClientProvider (shared with tests)
    ├── queryClient.ts       TanStack Query defaults; ApiError as the error type
    ├── theme.ts             Mantine theme
    ├── router.tsx           route table (shared with tests)
    │
    ├── api/                 ── HTTP layer ──
    │   ├── client.ts        the axios instance and its interceptors
    │   ├── errors.ts        ApiError: every failed call becomes one
    │   ├── schema.d.ts      generated from /openapi.json (never edited by hand)
    │   ├── types.ts         readable aliases: Job, JobSummary, JobStoreItem, ScoringConfig, …
    │   ├── uploads.ts       uploadStores(file)
    │   └── jobs.ts          listJobs, getJob, getJobSummary, listJobStores, scoreJob
    │
    ├── hooks/               ── server-state layer ──
    │   ├── queryKeys.ts     every query key, in one place
    │   ├── useJobs.ts       useJobs(page)
    │   ├── useJob.ts        useJob(jobId): polls while the job is pending or running
    │   ├── useJobSummary.ts
    │   ├── useJobStores.ts  useJobStores(jobId, filters, page)
    │   ├── useUploadStores.ts   mutation
    │   └── useScoreJob.ts   mutation; refreshes summary and stores on success
    │
    ├── components/          ── reusable UI ──
    │   ├── AppLayout/        header, navigation, page container
    │   ├── ApiErrorAlert/    shows an ApiError's detail and its list of problems
    │   ├── StatusBadge/      job or task status as a coloured badge
    │   ├── TierBadge/
    │   ├── JobProgress/      progress bar and counts per status
    │   ├── CsvDropzone/      drag-and-drop or pick a .csv
    │   ├── ScoringForm/      bars, weights, thresholds; client- and server-side errors
    │   ├── TierSummary/      Large / Medium / Small counts, when scored
    │   ├── StoreTable/       store rows with metrics, score, tier, reason
    │   ├── StoreFilters/     status and tier filters
    │   └── TablePagination/
    │       (each folder: Component.tsx, Component.module.css when it has styles, index.ts)
    │
    ├── pages/               ── screens ──
    │   ├── UploadPage/      /upload
    │   ├── JobsPage/        /jobs
    │   ├── JobPage/         /jobs/:jobId
    │   └── NotFoundPage/
    │
    ├── utils/               small classes with static methods
    │   ├── format.ts        Format: numbers, revenue (string → number), dates, durations
    │   ├── scoring.ts       ScoringRules: the API's checks, in the browser; default settings
    │   ├── status.ts        JobStatusRules: running / scorable; status and tier colours
    │   └── searchParams.ts  SearchParams: page and filters in the URL
    │
    ├── styles/
    │   └── global.css       the few global rules
    │
    └── test/                test setup: MSW server, fixtures, render helpers
```

## Screens and routes

| Route | Page | Uses | Shows |
| --- | --- | --- | --- |
| `/` | — | | redirects to `/jobs` |
| `/upload` | UploadPage | `useUploadStores` | `CsvDropzone`; on success, go to `/jobs/{job_id}`; on failure, `ApiErrorAlert` lists every CSV problem |
| `/jobs` | JobsPage | `useJobs` | table of jobs, newest first, with `StatusBadge`; paginated |
| `/jobs/:jobId` | JobPage | `useJob`, `useJobSummary`, `useJobStores`, `useScoreJob` | `JobProgress` → `ScoringForm` (once enrichment has finished) → `TierSummary` → `StoreFilters` + `StoreTable` + `TablePagination` |

On the job page, the store list's filters and page live in the URL (`/jobs/7?status=failed&page=2`). Refreshing or sharing the link keeps the view, and the back button works.

## The API layer

### Client (`api/client.ts`)

One axios instance:
- `baseURL` = `${VITE_API_BASE_URL}/api`, from `.env` (default `http://localhost:8001`).
- `timeout`: 15 s, which is plenty: every call except the upload returns in well under a second.
- The **upload** overrides the timeout per request (60 s), and sends `multipart/form-data`.
- **A response interceptor** turns every failure into one `ApiError`, so the rest of the app never handles raw axios errors:

```ts
class ApiError extends Error {
  status: number | null;        // null: network error or timeout (no response)
  detail: string;               // the backend's "detail", or a generic message
  errors: ErrorItem[];          // the backend's [{ field, message }]
  fieldErrors(): Record<string, string>;   // { "weights": "...", "bars.revenue": "..." } for forms
}
```

A second instance would only be needed for another server; the upload's differences are per-request settings.

### Endpoint functions (`api/jobs.ts`, `api/uploads.ts`)

Plain typed async functions, one per endpoint, that return `data`:

```ts
export async function getJob(jobId: number): Promise<Job> {
  const { data } = await apiClient.get<Job>(`/jobs/${jobId}`);
  return data;
}
```

### Types (`api/schema.d.ts` + `api/types.ts`)

- **Generated, not written by hand.** `npm run api:types` runs `openapi-typescript` against `http://localhost:8001/openapi.json` (the backend must be running) and writes `schema.d.ts`. Both files are committed, so a normal build doesn't need the backend.
- `types.ts` re-exports readable names, e.g. `export type Job = components["schemas"]["JobResponse"]`.
- When the backend's API changes, regenerating makes the TypeScript compiler point at every place that needs updating.
- `estimated_monthly_revenue` arrives as a string (exact decimal). It's turned into a number only for display, in `utils/format.ts`.

## The server-state layer (`hooks/`)

Each hook wraps one endpoint in TanStack Query:

```ts
export function useJob(jobId: number) {
  return useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () => getJob(jobId),
    // Poll every 3 s while the job is still running; stop once it's finished.
    refetchInterval: (query) =>
      isActive(query.state.data?.status) ? 3000 : false,
  });
}
```

| Hook | Behaviour |
| --- | --- |
| `useJob` | polls every 3 s while `pending` or `running`; stops when finished |
| `useJobStores` | polls while the job runs, so rows change state live; keeps the previous page on screen while the next one loads |
| `useJobSummary` | refetched when the job finishes, and after scoring |
| `useUploadStores` | mutation; on success, the page navigates to the new job |
| `useScoreJob` | mutation; on success, refreshes the summary and the store list, and shows a notification |

All query keys are built in `queryKeys.ts` (`["jobs", page]`, `["job", id]`, `["job", id, "stores", filters, page]`, …), so invalidation never depends on hand-typed arrays.

## Components

**Reusable components are presentational:** typed props in, callbacks out, no fetching and no routing. Examples:
- `StatusBadge({ status })`
- `StoreTable({ items, loading })`
- `ScoringForm({ initialConfig, onSubmit, submitting, serverError })`

They can be reused anywhere and tested without the API.

**The scoring form** uses `@mantine/form`:
- it **checks the same rules as the API in the browser** (weights add up to 100, Medium ≤ Large, values ≥ 0), so most mistakes never reach the server;
- it **shows server errors next to their inputs:** it awaits the submit, and if the API rejects it, puts `ApiError.fieldErrors()` (`weights`, `bars.revenue`, …) on the matching inputs. Other problems appear in an alert;
- it's **prefilled** with the job's last-used settings from the summary, or with the brief's example values for a job that hasn't been scored.

## Styling

- **Mantine's components and props do most of the layout:** `Stack`, `Group`, `Grid`, spacing props. A small app should need little CSS.
- **Component-specific styles** live next to the component in `Component.module.css`, so class names are scoped and can't clash.
- **Global CSS** is limited to `styles/global.css`.
- **Theme:** Mantine's default theme, light only, with one primary colour, set in `App.tsx`.

## Errors, loading and empty states

| Situation | UI |
| --- | --- |
| Loading | Mantine `Loader` or skeleton rows |
| An API error | `ApiErrorAlert`, with the detail and each problem |
| Form errors | messages next to their inputs |
| A successful upload or scoring | a toast notification |
| Job not found (404) | a "Job not found" message with a link to `/jobs` |
| Backend unreachable | an alert ("Can't reach the API at …") |
| No stores for a filter | an empty-state message in the table |

## Configuration and scripts

| Variable / script | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | backend URL; default `http://localhost:8001` (`.env.example` → `.env`) |
| `npm run dev` | dev server on port 5173 (allowed by the backend's CORS default `*`) |
| `npm run build` / `npm run preview` | production build in `dist/`, and a local preview of it |
| `npm run typecheck` / `npm run lint` | `tsc -b` / oxlint |
| `npm test` / `npm run test:watch` | run the tests once / in watch mode |
| `npm run api:types` | regenerate `src/api/schema.d.ts` from the running backend (`npx openapi-typescript`, pinned; not a project dependency because it doesn't support TypeScript 6 yet) |

## Testing

**Vitest**, **React Testing Library** and **Mock Service Worker (MSW)**. `npm test` runs them all in about 3 s.

- **Every API call is mocked.** MSW intercepts the real axios requests and answers with fixtures, so tests exercise the real client, interceptor and error handling. A request with no mock fails the test (`onUnhandledFrame: 'error'`).
- **Tests don't need a running backend:** `.env.test` points the API URL at the test page's own origin, so the browser's CORS rules (the backend's concern) don't apply.
- **What's covered:**

  | Area | Tests |
  | --- | --- |
  | `utils/` | formatting and revenue parsing, the scoring rules, URL params |
  | `api/` | each endpoint's URL, query params and body; `ApiError` from 404, 422 (field errors) and network failures |
  | `hooks/` | polling stops when the job finishes; the summary is refreshed then; scoring refreshes summary and stores, and exposes a 409 |
  | `ScoringForm` | submits; blocks weights ≠ 100 and Medium > Large without calling the API; shows the API's field errors on their inputs |
  | Pages (full app, real routes) | job page: progress, stores, status filter (URL and request), scoring end to end, no scoring while running, 404; upload: success opens the job, rejection lists every problem; jobs list, empty state, `/` redirect |

- **Not covered:** end-to-end tests in a real browser against the real backend.

## Decisions

1. **API types are generated** from the backend's OpenAPI schema (`openapi-typescript`), not written by hand.
2. **`@mantine/form`** for the scoring form, rather than React Hook Form.
3. **Polling every 3 s** while a job runs; none once it has finished.
4. **The store list's filters and page live in the URL.**
5. **Routes:** `/upload`, `/jobs`, `/jobs/:jobId`; `/` redirects to `/jobs`.
6. **Tests mock every API call** with MSW.
7. **Light theme only,** Mantine's defaults with an indigo primary colour.
