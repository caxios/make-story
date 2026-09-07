# Phase 3: World & Character Studio

## 1. Goal

Implement the authoring views for world-building, character creation, and relationship visualization in the React frontend, replacing the clunky Streamlit forms with responsive, instant-feedback UI components.

---

## 2. Dashboard Page (`src/pages/Dashboard.tsx`)

### 2.1 Metrics Grid
- Cards displaying key novel statistics:
  - **Total Episodes**: Completed vs. Queued with progress ring.
  - **Total Word Count**: Cumulative words across all finished chapters.
  - **Cast Size**: Total active characters.
  - **Open Plot Threads**: Unresolved foreshadowing items (떡밥).

### 2.2 Quick Action Panel
- Direct shortcuts: "Generate Next Queued Episode", "Add New Episode", "Open Character Workshop".
- **Recent Episodes List**: Mini-feed showing the latest 3 episodes with quick jump buttons to the Reading Room.

---

## 3. World Builder (`src/pages/WorldBuilder.tsx`)

Organized into tabs:

### 3.1 Overview Tab
- Form fields: Title, Genre dropdown (Fantasy, Sci-Fi, Mystery, Modern, etc.), Tone, Era, and Synopsis/Overview rich textarea.
- Auto-save or explicit "Save Changes" with dirty-state indicator.

### 3.2 Rules Tab
- Interactive card/table list of world rules.
- Rule modal with:
  - Category (Magic System, Physics, Society, Taboo, etc.)
  - Rule Statement
  - Exceptions list with add/remove tags.
- Inline delete button with confirmation tooltip.

### 3.3 Locations Hierarchy Tab
- Visual Tree / Indented List representing nested locations (e.g. *Continent -> Capital City -> Magic Academy -> Headmaster's Office*).
- "Add Sub-location" button directly on each location node.
- Automatic orphan re-parenting when a parent location is removed.

---

## 4. Character Workshop (`src/pages/CharacterWorkshop.tsx`)

### 4.1 Character Cards Grid
- Grid of character cards showing:
  - Character Name & Role badge (`Protagonist`, `Antagonist`, `Supporting`, etc.)
  - Explicit Character ID badge (e.g., `#harry`, `#ron`)
  - One-line summary
  - Quick action buttons: Edit, Clone, Delete.

### 4.2 Character Edit Drawer / Modal
- Comprehensive editing drawer:
  - **Basic Info**: Name, ID, Role, Core Archetype.
  - **Personality Traits**: Interactive range sliders (0.0 to 1.0) for traits (e.g., Courage, Pragmatism, Loyalty, Cynicism).
  - **Speech Style**: Formality selector, Tone, Dialogue Quirks, Example Lines preview.
  - **Secrets**: Collapsible system-only notes for hidden character motivations.
  - **Relationships List**: Target character selector, relationship type, sentiment slider (-1.0 hostile to +1.0 intimate), and notes.

### 4.3 Interactive Character Relationship Network Graph
- Visual node-link diagram rendered with SVG / HTML5 Canvas:
  - **Nodes**: Circles representing characters with avatar/initials, name, and role.
  - **Edges**: Directed arrows between related characters.
  - **Sentiment Coloring**:
    - Emerald Green: Positive / Allied / Romantic (> 0.3)
    - Slate Gray: Neutral (0.3 to -0.3)
    - Rose / Crimson: Antagonistic / Rivalry (< -0.3)
  - **Interactivity**: Click a node to view character details or highlight connected edges.

---

## 5. Verification

1. Create a character and adjust personality sliders; confirm instant state updates without re-renders.
2. Verify that deleting a character removes all dangling relationship edges in the visual graph.
3. Test location hierarchy creation up to 4 levels deep.
