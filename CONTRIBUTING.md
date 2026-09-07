# Contributing

1. Pull the latest `main`.
2. Create a branch for one feature or bug fix.
3. Keep credentials and runtime data out of commits.
4. Run `python -m py_compile app.py chrome_bridge.py chrome_profile.py stable_extension.py modules/*.py` before committing.
5. Open a Pull Request describing reproduction, root cause, fix and validation.

Never commit API credentials, browser profiles/cookies, `data/studio.db`, upload history, personal registry, diagnostics or generated media.
