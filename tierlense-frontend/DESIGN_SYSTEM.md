# TierLense design system

A minimal, enterprise interface. One neutral palette, black primary actions, and structure carried by borders and spacing rather than shadows, tints or decoration.

## Principles

- **Neutral first.** Whites and grays for every surface. Colour appears only where a state needs attention (warning, failure, success dots).
- **Black primary actions.** Primary buttons are black with white text. Secondary buttons are white with a gray border. Ghost buttons are for low-emphasis row actions.
- **Separation through lines.** Page header, card header, table header and modal footer are each divided by a 1px border. Cards have no shadow.
- **Readable by default.** 14px body text, 12px minimum anywhere. Labels are sentence case, never all caps.

## Tokens (see `src/styles.css`)

| Role | Token | Value |
| --- | --- | --- |
| Page background | `--canvas` | `#f5f5f5` |
| Card surface | `--surface` | `#ffffff` |
| Inset / table header | `--surface-2` | `#fafafa` |
| Hover / chip | `--surface-3` | `#f1f1f1` |
| Border | `--line` / `--line-strong` | `#e6e6e6` / `#d1d1d1` |
| Text | `--ink` / `--ink-2` / `--ink-3` | `#171717` / `#404040` / `#6b6b6b` |
| Primary action | `--black` | `#000000` (hover `#262626`) |

## Typography

- Family: Inter, falling back to the system stack (no remote font loading). Monospace is used only for IDs and hashes.
- Page title 28px / 650 · card title 16px / 600 · modal title 18px / 600
- Body and controls 14px · helper text 12–13px · table headers 12px / 500
- Metric values 32px, tabular numerals

## Layout

- Sidebar 248px, top bar 64px, content max-width 1480px with 40px gutters (24px below 980px, 16px below 700px).
- Cards: 8px radius, 1px border, 24px padding. Modals: 12px radius.
- Controls: 40px tall (38px in table toolbars, 32px for small buttons).
- Sidebar becomes a drawer below 980px. Two-column layouts collapse to one below 1180px.

## Status colour

Status badges are gray with a coloured dot. Only states that demand attention (needs review, queued, failed, critical) get a tinted background. Severity chips follow the same rule: levels 1–2 neutral, 3 amber, 4–5 red.

## Data visualization

Charts are computed from API records, never seeded values. Empty or unavailable data renders an empty state.

- Supply network map from returned entities and relationships (full width on the overview)
- Disruption counts by severity
- Investigation counts by status
- Entity composition by type
- Evidence pipeline counts from the latest investigation summary
