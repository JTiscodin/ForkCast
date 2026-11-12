# Forkcast — Design System

Premium, dark-first meal-planning UI. Swiggy orange accent over warm-charcoal
surfaces. Tailwind v4 (CSS-first, `@theme` in `globals.css`) + shadcn/ui.

**Source of truth:** `src/app/globals.css` (tokens) · `src/lib/design.ts` (typed
helpers) · `src/app/layout.tsx` (fonts + theme). Never hard-code a hex or hue —
use a token or a `design.ts` export.

---

## Themes

Dark is primary and the default (`defaultTheme="dark"`, next-themes with
`attribute="class"`). Both themes are defined; the toggle stamps `.dark` /
`data-theme`. OS `prefers-color-scheme` covers first paint.

## Color tokens

Semantic (theme-flipping) — use these in components, not raw scale steps:

| Token | Utility | Use |
|---|---|---|
| `--background` / `--foreground` | `bg-background` / `text-foreground` | Page base |
| `--surface` | `bg-surface` | Panels one step above background |
| `--surface-elevated` | `bg-surface-elevated` | Floating / featured cards |
| `--muted-foreground` | `text-muted-foreground` | Secondary text |
| `--border` | `border-border` | All hairlines |
| `--accent-brand` | `text-accent-brand` | Small brand-tinted text/icons |
| `--success` | `text-success` | Veg green, confirmed |
| `--warning` | `text-warning` | Rescheduled |
| `--danger` | `text-danger` | Non-veg, skipped, destructive |

Brand scale: `brand-50 … brand-900` (`brand-500` = Swiggy `#FF5200`). Warm
partner: `amber-300 … amber-600`. Meal accents: `meal-breakfast` (amber),
`meal-lunch` (orange), `meal-dinner` (violet), `meal-snack` (teal).

shadcn's contract (`--primary`, `--ring`, `--card`, `--sidebar-*`, …) is intact
and remapped to this palette, so all shadcn components inherit the theme.
`--primary` = brand orange, `--ring` = brand orange.

## Gradients — when to use each

Via `gradients.*` in `design.ts` (or the `bg-gradient-*` utilities directly):

- **`brand`** (orange→amber) — primary CTAs, brand marks, active states. High energy; one per view.
- **`surface`** — subtle top-down elevation on cards/headers. Almost invisible; adds depth without noise.
- **`glow`** — radial accent bloom from the top, behind a hero or featured block. Atmosphere, not a fill.
- **`mesh`** — full-bleed multi-stop hero background. **Hero only** — never behind body text.
- **`text-gradient-brand`** (`gradientText`) — orange→amber clipped to text. **One** hero headline, max.

## Typography

- **Display / headings:** Space Grotesk (`font-display`, auto-applied to h1–h4).
- **Body:** Inter (`font-sans`, the default).
- **Data / numerals / code:** Geist Mono (`font-mono`) — use for prices, calories, counts.

Scale (`text-xs … text-5xl`) ships tuned line-heights and negative tracking on
large sizes. `text-5xl`/`4xl` for heroes, `2xl`/`3xl` for section titles,
`base` for body, `sm` for meta, `xs` for labels/eyebrows.

## Spacing, radius, elevation

- **Spacing:** Tailwind's default 4px scale. Cards pad `p-5`/`p-6`; section rhythm `gap-6`/`gap-8`; page gutters `px-4 md:px-6 lg:px-8`.
- **Radius:** `rounded-lg` (default control, `--radius` 0.75rem) · `rounded-xl` (cards) · `rounded-2xl` (elevated/glass) · `rounded-full` (badges, dots, avatars).
- **Elevation:** `shadow-soft` (resting cards) · `shadow-layered` (floating/featured) · `shadow-glow` (brand emphasis) · `glass-panel` (frosted sticky nav/overlay).

## design.ts helpers (import verbatim)

```ts
import { cn } from "@/lib/utils"
import {
  gradients, gradientText, surfaces, focusRing,
  mealTypes, planStatus, dietDot,
  gradient, mealStyle, statusStyle,
} from "@/lib/design"
```

- `surfaces.card | cardElevated | glass | well | brandPanel`
- `gradients.brand | surface | glow | mesh`, `gradientText`, `focusRing`
- `mealTypes[type]` → `{ text, bg, soft, border, label, cssVar }`
- `planStatus[status]` → `{ text, dot, badge, label }`
- `dietDot.veg | dietDot.nonveg`
- helpers: `gradient(name, ...classes)`, `mealStyle(type)`, `statusStyle(status)`

## Do / Don't

**Do**
- Reach for a semantic token or `design.ts` export first.
- Keep the mesh/glow gradients to hero regions; keep the rest of the page quiet.
- Use mono for every number the user reads as data (₹, kcal, counts).
- Respect focus: apply `focusRing` on custom interactive elements.

**Don't**
- Hard-code hex/oklch or reach for arbitrary `[#…]` colors in components.
- Stack multiple brand gradients or gradient-text in one view.
- Put `mesh`/`glow` behind body copy (contrast + noise).
- Introduce new fonts or type sizes outside the scale.
- Edit shadcn's CSS variable names — remap in `globals.css` if a value must change.
