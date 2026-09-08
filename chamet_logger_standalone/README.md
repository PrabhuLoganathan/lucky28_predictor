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
Django to be running. Lucky Race automation is not part of this package.
