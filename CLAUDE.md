# CLAUDE.md

See [READNE.md](READNE.md).

## Language Server And Formatting

Pyright/basedpyright language server:

```bash
pyright-langserver --stdio
```

Type check:

```bash
pyright .
```

Format and lint with Ruff:

```bash
ruff format .
ruff check .
```

`pyproject.toml` contains `tool.basedpyright` and `tool.ruff` settings.

## Conventions

Code:
- Prefer simple flow and short names.
- Prefer less code when behavior stays clear.
- Use comments for non-obvious behavior only.
- Keep hardware, audio, and manual tests opt-in.

Docs:
- Use short phrases over descriptive sentences.
- Use examples over long descriptions.
- Keep facts current with the code.
- Avoid speculative EVO 8 claims unless they are marked as validation notes.
