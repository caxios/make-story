# Phase 2: Frontend Foundation & Design System

## 1. Goal

Bootstrap a modern **Vite + React + TypeScript** single-page application (SPA) under `frontend/` with a curated dark-mode writer's studio design system, comprehensive TypeScript models matching the Python Pydantic backend, a typed REST client, and Server-Sent Events (SSE) streaming integration.

---

## 2. Project Bootstrap

Initialize the React + TypeScript application with Vite:
```bash
npx -y create-vite@latest frontend --template react-ts
cd frontend
npm install
npm install lucide-react clsx tailwind-merge
npm install -D tailwindcss @tailwindcss/vite
```

Configure `frontend/vite.config.ts`:
- Enable `@tailwindcss/vite` plugin (or standard PostCSS setup).
- Configure API proxy:
  ```typescript
  export default defineConfig({
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  });
  ```

---

## 3. Design System & Aesthetics

Create a sleek, distraction-free **dark-mode-first aesthetic** suitable for novelists:
- **Palette**: Deep slate canvas (`#0b0f17`), elevated card panels (`#131b2e`), indigo accents (`#6366f1`), violet highlights (`#8b5cf6`), emerald status green (`#10b981`), amber alerts (`#f59e0b`).
- **Typography**: Clean sans-serif for controls and UI metadata (`Inter` / system-ui); warm serif typography option for novel reading room (`Merriweather` / `Lora`).
- **Micro-interactions**: Subtle border glows on active inputs, glassmorphic dropdowns, buttery smooth tab transitions.

---

## 4. TypeScript Domain Models (`src/types/storyweaver.ts`)

Mirror Python Pydantic models into strict TypeScript types:

```typescript
export interface Rule {
  id: string;
  category: string;
  statement: string;
  exceptions: string[];
}

export interface Location {
  id: string;
  name: string;
  description: string;
  parent_location_id: string | null;
  notable_features: string[];
}

export interface WorldLore {
  title: string;
  genre: string;
  tone: string;
  era: string;
  overview: string;
  rules: Rule[];
  locations: Location[];
  factions: Array<{ name: string; description: string }>;
}

export interface Relationship {
  target_character_id: string;
  relationship_type: string;
  sentiment: number; // -1.0 to 1.0
  description: string;
}

export interface CharacterProfile {
  id: string;
  name: string;
  role: string;
  one_line_summary: string;
  personality_traits: Record<string, number>;
  speech_style: {
    formality: string;
    tone: string;
    quirks: string[];
    example_dialogue: string[];
  };
  relationships: Relationship[];
  secrets: string[];
}

export type EpisodeStatus = 'queued' | 'in_progress' | 'completed';

export interface Episode {
  episode_number: number;
  title: string;
  author_storyline: string;
  status: EpisodeStatus;
  pacing: string;
  final_text: string;
}

export interface ProjectStats {
  episodes_total: number;
  episodes_completed: number;
  episodes_queued: number;
  total_words: number;
  character_count: number;
  open_thread_count: number;
}
```

---

## 5. API Client & SSE Hook

### 5.1 Typed REST Client (`src/api/client.ts`)
- Wrap standard `fetch` with error handling, JSON serialization, and toast error notifications.
- Typed functions for:
  - `getProject()`, `saveProject(project)`
  - `getStats()`
  - `getCharacters()`, `upsertCharacter(char)`, `deleteCharacter(id)`
  - `getEpisodes()`, `addEpisode(storyline, title)`, `updateEpisode(ep)`, `deleteEpisode(num)`, `moveEpisode(num, offset)`
  - `getPlotThreads()`

### 5.2 SSE Live Generation Hook (`src/api/useGenerationStream.ts`)
- Custom React hook managing the `EventSource` connection to `/api/generation/stream/{episode_number}`:
  - Tracks connection status (`idle`, `connecting`, `generating`, `complete`, `error`).
  - Stores incoming scene progression, node update messages, and live checklist lines.
  - Automatically handles disconnection and state cleanup.

---

## 6. Global Shell Components

1. **`AppLayout.tsx`**:
   - Collapsible sidebar with navigation items:
     - 🏠 Dashboard
     - 🌍 World Builder
     - 👤 Character Workshop
     - 📝 Episode Queue
     - 📖 Reading Room
     - 🧠 Memory Inspector
     - ⚙️ Settings
   - Header with current story title, episode count pills, and quick status.
2. **`ToastContext.tsx`**:
   - Lightweight floating toast system for non-blocking success, error, and info alerts.

---

## 7. Verification

- Run `npm run build` in `frontend/` to confirm zero TypeScript compilation errors.
- Run `npm run dev` and ensure the base layout renders smoothly on `http://localhost:5173`.
