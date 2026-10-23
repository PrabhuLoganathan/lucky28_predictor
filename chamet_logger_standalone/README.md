# Chamet Lucky Number logger

This folder is part of the root Lucky28 project. Start both components with:

```bash
python3 run.py
```

Run that command from the repository root. Configuration comes from the root
`.env`, and the browser profile and event queue live under root `.local/`.
See [the project README](../README.md) for setup, the API contract, signal feedback,
and verification commands.

For development in this directory:

```bash
npm run build
npm test
npm start
```

`npm test` runs local unit tests. `npm start` opens only the logger and expects
Django to be running. The logger joins the first available party and selects
Lucky Number automatically, reusing the saved login. It waits for sign-in if
needed and reopens the game after two minutes without Number Game progress.
Use `CHAMET_AUTO_OPEN=false` for manual navigation. Lucky Race automation is not
run; the copied `src/tests/chamet_logger.spec.ts` is excluded from the build.
