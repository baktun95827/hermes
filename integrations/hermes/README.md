# Hermes Integration

Hermes is a worker/runtime integration for Signal Radar, not the product core.

Current active skill:

```text
skills/signal-radar/
```

Future active adapter:

```text
integrations/hermes/skills/signal-radar/
```

The adapter should stay thin:

- expose `SKILL.md`
- provide Hermes-compatible CLI entrypoints
- call `packages/signal-radar-core`
- write/read artifacts through the standard contracts

For now, do not duplicate the active skill here. Once `packages/signal-radar-core` is extracted, move or recreate a thin Hermes adapter under `integrations/hermes/skills/signal-radar` and install it with:

```bash
ln -s /opt/xradar/integrations/hermes/skills/signal-radar \
      ~/.hermes/skills/signal-radar
```

Do not put Hermes runtime state here:

- sessions
- gateway state
- OAuth/Codex credentials
- runtime memory stores
- logs and caches
