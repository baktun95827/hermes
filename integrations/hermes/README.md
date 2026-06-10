# Hermes Adapter

This directory contains the optional Hermes adapter for Signal Radar. The Next.js product is the main runtime; this adapter is only a thin command wrapper for an external Hermes installation.

Product runtime:

```text
npm run dev
npm run signal-radar -- ingest-text ...
```

Adapter location:

```text
integrations/hermes/skills/signal-radar/
```

The adapter must stay thin:

- expose `SKILL.md`
- call `npm run signal-radar`
- read/write standard artifacts through TypeScript contracts
- avoid carrying runtime credentials, memory, cookies, cron jobs, or gateway state inside the product repo

Install it into Hermes by copying or symlinking only the adapter directory into the external Hermes skill path. Do not copy the old repository-level `skills/` catalog back into this product.

Do not put Hermes runtime state here:

- sessions
- gateway state
- OAuth/Codex credentials
- runtime logs and caches
