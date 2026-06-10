# Design

## Overview

Signal Radar uses a restrained product interface for research operations. The visual system should support repeated scanning of job state, summaries, JSON artifacts, and audit results.

## Color

Strategy: restrained, with deep moss as the primary action and status anchor.

```css
:root {
  --bg: oklch(1.000 0.000 0);
  --surface: oklch(0.973 0.006 145);
  --surface-strong: oklch(0.936 0.010 145);
  --ink: oklch(0.180 0.018 150);
  --muted: oklch(0.455 0.020 150);
  --primary: oklch(0.350 0.110 140);
  --primary-strong: oklch(0.285 0.105 140);
  --accent: oklch(0.620 0.150 32);
  --line: oklch(0.880 0.010 145);
  --danger: oklch(0.530 0.170 25);
  --warning: oklch(0.700 0.145 75);
  --success: oklch(0.500 0.125 150);
}
```

## Typography

Use a system sans stack for all product UI. Use fixed rem sizes, not fluid viewport scaling. Reserve monospace for job IDs, paths, logs, JSON, and schema labels.

## Layout

Use a persistent top bar, a constrained main workspace, and responsive two-column layouts for input plus run status. Detail pages should prioritize summary, memory update, audit, and logs in clearly separated sections.

## Components

- Primary buttons use moss fill with white text.
- Secondary buttons use white background, line border, and ink text.
- Forms use standard inputs, visible labels, and clear validation messages.
- Artifact panels use monospace pre blocks with horizontal overflow when needed.
- Status pills use semantic colors and plain labels.

## Motion

Motion is limited to state feedback and hover/focus transitions under 180 ms. No page-load choreography. Respect `prefers-reduced-motion`.
