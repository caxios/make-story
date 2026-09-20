# Phase 1 (Frontend): Natural Language Character & World Setup UI

**Depends on:** Phase 1 Backend (`/api/parse/character` and `/api/parse/world` must be live).  
**Goal:** Add a "describe in natural language" entry path to `CharacterWorkshop` and a "Quick Setup" tab to `WorldBuilder`.

---

## Files to Modify

| # | File | Change |
|---|---|---|
| 1 | `frontend/src/api/client.ts` | Add `parseCharacter()` and `parseWorld()` functions |
| 2 | `frontend/src/pages/CharacterWorkshop.tsx` | Add parse modal before the existing drawer |
| 3 | `frontend/src/pages/WorldBuilder.tsx` | Add "Quick Setup" tab with free-text input |

---

## Change 1: `frontend/src/api/client.ts`

Add two new exported functions **at the end of the file**, after the last existing function.

```typescript
// ── Parse endpoints (Phase 1) ──────────────────────────────────────────────

export async function parseCharacter(
  text: string,
  existingCharacterIds: string[],
): Promise<CharacterProfile> {
  return request<CharacterProfile>('/api/parse/character', {
    method: 'POST',
    body: { text, existing_character_ids: existingCharacterIds },
  })
}

export async function parseWorld(text: string): Promise<WorldLore> {
  return request<WorldLore>('/api/parse/world', {
    method: 'POST',
    body: { text },
  })
}
```

No new imports needed — `CharacterProfile` and `WorldLore` are already imported from `@/types/storyweaver` at the top of this file.

---

## Change 2: `frontend/src/pages/CharacterWorkshop.tsx`

### 2a — Add three new state variables

Find the block of `useState` calls near line 190–199. Add three new variables **after** the existing ones:

```typescript
// --- existing state ---
const [tab, setTab] = useState<TabId>('cast')
const [editing, setEditing] = useState<CharacterProfile | null>(null)
const [isNew, setIsNew] = useState(false)
const [deleting, setDeleting] = useState<CharacterProfile | null>(null)
const [cloning, setCloning] = useState<CharacterProfile | null>(null)
const [graph, setGraph] = useState<GraphData | null>(null)

// --- ADD these three ---
const [parseModalOpen, setParseModalOpen] = useState(false)
const [parseText, setParseText] = useState('')
const [parsePending, setParsePending] = useState(false)
```

### 2b — Add the parse handler function

Add this function directly after the existing handler functions (e.g., after `handleSave`, `handleDelete`):

```typescript
async function handleParseCharacter() {
  if (!parseText.trim()) return
  setParsePending(true)
  try {
    const existingIds = (project?.characters ?? []).map((c) => c.id)
    const parsed = await api.parseCharacter(parseText.trim(), existingIds)
    // Open the existing drawer pre-filled with the parsed data.
    // The author can review and edit every field before saving.
    setEditing(parsed)
    setIsNew(true)
    setParseModalOpen(false)
    setParseText('')
  } catch (err) {
    fromError(err)
  } finally {
    setParsePending(false)
  }
}
```

### 2c — Replace the "Add Character" button behavior

Find the current button that opens the blank drawer (it calls something like `setEditing(blankCharacter()); setIsNew(true)`).

**Current button (approximate):**
```tsx
<Button onClick={() => { setEditing(blankCharacter()); setIsNew(true) }}>
  <Plus size={16} /> Add Character
</Button>
```

**Replace with:**
```tsx
<Button onClick={() => setParseModalOpen(true)}>
  <Plus size={16} /> Add Character
</Button>
```

### 2d — Add the parse modal

Add the following JSX **before** the existing character drawer `<Drawer>` component (i.e., at the bottom of the component's return statement, alongside the other modals):

```tsx
{/* ── Parse Modal ─────────────────────────────────────────────────────── */}
<Modal
  open={parseModalOpen}
  onClose={() => { setParseModalOpen(false); setParseText('') }}
  title="Add Character"
>
  <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
    <p style={{ color: 'var(--color-muted)', fontSize: '0.9rem', margin: 0 }}>
      Describe your character freely — name, age, appearance, personality,
      relationships, goals, secrets. The AI will extract the details and
      pre-fill the character sheet for you to review.
    </p>
    <TextArea
      label="Character description"
      placeholder={
        '예시: "해리는 17세 남학생으로, 검은 머리카락과 둥근 안경이 특징이다. ' +
        '용감하고 직관적이지만 충동적인 면이 있다. 론과는 절친한 친구 사이로, ' +
        '서로를 형제처럼 여긴다. 볼드모트를 물리치는 것이 목표다."'
      }
      rows={8}
      value={parseText}
      onChange={(e) => setParseText(e.target.value)}
    />
    <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
      <Button
        variant="ghost"
        onClick={() => {
          setEditing(blankCharacter())
          setIsNew(true)
          setParseModalOpen(false)
          setParseText('')
        }}
      >
        Fill out form manually
      </Button>
      <Button
        disabled={!parseText.trim() || parsePending}
        onClick={handleParseCharacter}
      >
        {parsePending ? 'Parsing…' : 'Parse with AI →'}
      </Button>
    </div>
  </div>
</Modal>
```

> **Note on the `loading` prop:** If `Button` in this codebase accepts a `loading` prop that shows a spinner, use `loading={parsePending}` instead of `disabled={parsePending}`. Check `frontend/src/components/ui/` for the `Button` component's props.

### 2e — Resulting UX flow

```
Author clicks "Add Character"
  └→ Parse Modal opens
       ├─ Author writes free-text description
       │    └→ clicks "Parse with AI →"
       │         └→ API call to POST /api/parse/character
       │              └→ Drawer opens pre-filled with parsed CharacterProfile
       │                   └→ Author edits any field → clicks Save
       │                        └→ POST /api/characters (existing endpoint)
       └─ Author clicks "Fill out form manually"
            └→ Drawer opens blank (existing behavior)
```

---

## Change 3: `frontend/src/pages/WorldBuilder.tsx`

### 3a — Add two new state variables

Find the component's `useState` declarations and add:

```typescript
const [quickSetupText, setQuickSetupText] = useState('')
const [quickSetupPending, setQuickSetupPending] = useState(false)
```

### 3b — Add the parse handler

```typescript
async function handleQuickSetup() {
  if (!quickSetupText.trim()) return
  setQuickSetupPending(true)
  try {
    const parsed = await api.parseWorld(quickSetupText.trim())
    // Save directly — the author can refine in the other tabs.
    await api.updateWorld(parsed)
    await refresh()
    success('World settings updated from your description.')
    setQuickSetupText('')
  } catch (err) {
    fromError(err)
  } finally {
    setQuickSetupPending(false)
  }
}
```

> **Find `api.updateWorld`:** This is the existing function that calls `PUT /api/world`. Verify the exact function name in `client.ts` — it may be `updateWorld`, `saveWorld`, or `putWorld`.

### 3c — Add "Quick Setup" as the first tab

Find where the tab identifiers are defined. Currently the tabs are `'overview' | 'rules' | 'locations'`. Add `'quick-setup'` as the first option:

**Current tab type (approximate):**
```typescript
type TabId = 'overview' | 'rules' | 'locations'
```

**Replace with:**
```typescript
type TabId = 'quick-setup' | 'overview' | 'rules' | 'locations'
```

Find the `<Tabs>` component call and add the new tab. The `Tabs` component in this codebase takes a `tabs` prop (array of `{ id, label }`). Add the quick-setup entry first:

```tsx
<Tabs
  tabs={[
    { id: 'quick-setup', label: '⚡ Quick Setup' },
    { id: 'overview', label: 'Overview' },
    { id: 'rules', label: 'Rules' },
    { id: 'locations', label: 'Locations' },
  ]}
  active={tab}
  onChange={setTab}
/>
```

### 3d — Add the Quick Setup tab panel content

Find the section that renders tab content (a chain of `{tab === 'overview' && ...}` conditionals). Add the quick-setup panel **before** the overview panel:

```tsx
{tab === 'quick-setup' && (
  <Panel>
    <p style={{ color: 'var(--color-muted)', fontSize: '0.9rem', marginBottom: '1rem' }}>
      Describe your world freely. The AI will extract the title, genre, tone, era,
      overview, rules, and locations. You can refine everything in the other tabs afterwards.
    </p>

    {/* Warning if the world already has content */}
    {(world?.overview || (world?.rules?.length ?? 0) > 0) && (
      <div style={{ 
        background: 'var(--color-warning-subtle)', 
        border: '1px solid var(--color-warning)', 
        borderRadius: '6px', 
        padding: '0.75rem 1rem', 
        marginBottom: '1rem',
        fontSize: '0.875rem'
      }}>
        ⚠️ Your world already has content. Running Quick Setup will overwrite the current
        overview, rules, and locations with what the AI extracts from your description.
      </div>
    )}

    <TextArea
      label="World description"
      placeholder={
        '예시: "마법사와 머글이 공존하는 현대 영국. 호그와트는 스코틀랜드 산중의 마법 학교로, ' +
        '9¾ 승강장을 통해서만 접근 가능하다. 마법의 존재는 머글에게 비밀이며, ' +
        '어둠의 마법사 볼드모트의 부활이 이야기의 주요 위협이다. ' +
        '금지된 저주(아바다 케다브라, 크루키아투스, 임페리우스)는 사용이 금지된다."'
      }
      rows={12}
      value={quickSetupText}
      onChange={(e) => setQuickSetupText(e.target.value)}
    />

    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
      <Button
        disabled={!quickSetupText.trim() || quickSetupPending}
        onClick={handleQuickSetup}
      >
        {quickSetupPending ? 'Parsing…' : 'Parse with AI →'}
      </Button>
    </div>
  </Panel>
)}
```

### 3e — Auto-select Quick Setup for new projects

Add this effect to automatically open the Quick Setup tab when the world is empty:

```typescript
// Show Quick Setup tab first when there's no world content yet.
useEffect(() => {
  if (!world?.overview && !world?.title) {
    setTab('quick-setup')
  }
}, [world])
```

---

## Verification Checklist

### CharacterWorkshop
1. Click **"+ Add Character"** → Parse Modal opens (not the drawer).
2. Type a character description → click **"Parse with AI →"** → spinner appears.
3. After ~5 seconds, the modal closes and the **character drawer opens pre-filled**.
4. Verify that `age`, `traits`, `relationships`, etc. are populated from the description.
5. Edit one field → click **Save** → character appears in the cast list.
6. In the modal, click **"Fill out form manually"** → the drawer opens with a blank character (existing behavior preserved).

### WorldBuilder
1. On a fresh project, the **Quick Setup** tab is pre-selected.
2. Type a world description → click **"Parse with AI →"** → spinner appears.
3. After completion, switch to the **Overview** tab → the parsed world content is visible.
4. The **Rules** and **Locations** tabs show extracted rules and locations.

---

## Notes for the Implementer

- **Do not remove the existing drawer**. The parse modal is an *additional* entry path; the drawer is reused for editing and for the "fill out manually" fallback.
- If `Button` does not accept a `loading` prop and you need to show a spinner during the API call, use `disabled={parsePending}` and change the label text to `"Parsing…"` as shown above.
- The Quick Setup flow **saves immediately** after parsing (calls `updateWorld`). The character parse flow does NOT save automatically — it only pre-fills the drawer, and the author must click Save. This asymmetry is intentional: world setup is a wholesale replacement, while character creation is a reviewed addition.
- The overwrite warning in the WorldBuilder Quick Setup panel should be shown whenever `world.overview` is non-empty OR `world.rules.length > 0`. This prevents accidentally wiping a fully configured world.
