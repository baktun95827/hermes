# Hermes Integration

Hermes is now an optional integration for the TypeScript Signal Radar product, not the product core.

Current product runtime:

```text
npm run dev
npm run signal-radar -- ingest-text ...
```

Future Hermes adapter location:

```text
integrations/hermes/skills/signal-radar/
```

The adapter should stay thin:

- expose `SKILL.md`
- call `npm run signal-radar`
- read/write standard artifacts through TypeScript contracts
- avoid carrying runtime credentials inside the product repo

Do not put Hermes runtime state here:

- sessions
- gateway state
- OAuth/Codex credentials
- runtime logs and caches
