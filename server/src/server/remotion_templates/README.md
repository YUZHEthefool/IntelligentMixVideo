# Remotion Preset → Sprite

This focused module supports one workflow only: create an immutable Preset, compose one or more Preset instances into a Sprite, save that exact Sprite, and publish an isolated Player preview.

The public business tools are `preset.create`, `sprite.compose`, and `sprite.create`. `tools.inspect` exposes their schemas. Image processing, semantic Preset search, Preset modification and model-authored validation tools are intentionally outside this change. The host still performs the code, parameter and browser checks required to build a preview.

The Agent keeps the existing Outer → Plan → Executor handoff, but the Executor receives only the creation tools. Creation-only mode avoids ChromaDB and embedding downloads. The preview is built from the saved Sprite's exact code, schema, defaults and 1080×1920/30 FPS composition.

For Linux renderer validation, install the locked Bun dependencies in `server/src/server/remotion`, then run:

```sh
IMV_TEST_RENDERER=1 uv run --locked --project server pytest server/tests/test_remotion_creation_flow.py -q
```

The browser path requires Chromium, Noto CJK fonts, bubblewrap and util-linux. Offline tests cover tool registration, immutable storage and source consistency without a model or semantic index.
