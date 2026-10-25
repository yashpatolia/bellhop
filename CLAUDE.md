# Bellhop project notes

Bellhop is an autonomous robot fleet that answers the non-urgent call bells in care homes, saving nurse time. Plan and research live in `artifacts/`. The nurse dashboard lives in `frontend/` (Vite, React, TypeScript, Motion).

## Working rules

- Build top down: get a working MVP first, then refine.
- The dashboard has no mock data of its own. It reads the backend only (`frontend/src/data/store.ts`, wire format mapped in `adapt.ts`). Example data lives in `simulator/`, which feeds the backend over its API; run `scripts/dev.sh mock` or `scripts/dev.sh empty`.
- NEVER use em dashes (or en dashes) in code, copy, comments or docs.
- Fill the whole page width. No narrow centred max-width layouts.

## Design rules for the dashboard

- The audience is nurses and caretakers, so it must stay readable and calm: large type, strong contrast, not overwhelming. Urgency is always shown with words as well as colour.
- Prefer neutral soft or pastel palettes. Amber is off limits (it reads as AI slop). Modern sans is fine, a serif accent is fine for some themes, but body text and numbers stay highly legible.
- Do not default to blueprint or newspaper themes. Think outside the box.
- Every component reads theme tokens from `frontend/src/theme/themes.css`. A theme is just a block of CSS variables.

<frontend_aesthetics>

You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight. Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration.

Motion: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, or add contextual effects that match the overall aesthetic.

Avoid generic AI-generated aesthetics:

- Overused font families (Inter, Roboto, Arial, system fonts)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

Interpret creatively and make unexpected choices that feel genuinely designed for the context. Vary between light and dark themes, different fonts, different aesthetics. You still tend to converge on common choices (Space Grotesk, for example) across generations. Avoid this: it is critical that you think outside the box!

</frontend_aesthetics>
