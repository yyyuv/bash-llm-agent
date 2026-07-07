# Environment incident log — PATH corruption in ~/.zshrc — 2026-07-07

Referenced from DECISIONS.md P2e/P2f. Raw evidence for the report's
limitations chapter (PATH/env setup friction).

## What was in ~/.zshrc

Working (set during Phase 1 setup):
```bash
# doit (Assignment 3) entry point lives here
export PATH="$HOME/.local/bin:$PATH"
```

Broken (after a manual edit, before this fix):
```bash
# doit (Assignment 3) entry point lives here
export PATH="$/Users/yuvalreuveni/Documents/Claude/Projects/assingment3/bash-llm-agent/doit$HOME/.local/bin:$PATH"
```

Symptom: `doit "tell me a joke"` → `zsh: command not found: doit`, same
symptom as the original missing-PATH problem, but this time the PATH
variable itself was malformed rather than simply lacking the entry.

## Verification after the fix

```
$ zsh -lc 'source ~/.zshrc && which doit && doit "tell me a joke"'
/Users/yuvalreuveni/.local/bin/doit
doit: error: litellm.AuthenticationError: ... OPENAI_API_KEY ...
```
`which doit` resolving confirms the PATH fix; the AuthenticationError is
expected and unrelated — that test shell never sourced `.env`.

## Side observation (P2f)

`~/.zshrc` lines 3–16 (the `conda init` managed block) are fully
commented out, so a `(base)`-prompted terminal does not actually run
conda's PATH-prepending hook on startup. Not caused by or related to
doit; recorded so it isn't re-diagnosed from scratch in a later session.
