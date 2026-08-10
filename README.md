# doit — an agentic shell assistant

`doit` turns a plain-English request into shell commands and runs them for you.
You type what you want; an LLM decides which tool to use (run a command, answer
in text, ask a clarifying question, remember a fact, change directory, …) and
the Python controller carries it out with safety checks.

```bash
$ doit "show me all files here, including hidden ones"
$ ls -la
...
```

The full design, examples, and model comparison are in
[report/report.pdf](report/report.pdf).

---

## Requirements

- **Python 3.8+**
- **[LiteLLM](https://github.com/BerriAI/litellm)** — the only external dependency:
  ```bash
  pip install litellm
  ```
- **An API key** for the default model (`openai/gpt-4o-mini`):
  ```bash
  export OPENAI_API_KEY="sk-..."
  ```
  LiteLLM reads the key from the environment. Put the `export` line in your
  shell profile so it persists.
- **[Ollama](https://ollama.com)** — only if you want to run the local models
  (`qwen3:4b-instruct`, `gemma3:4b`). Not needed for the default API model.

---

## Setup

### 1. Put `doit` on your PATH

`doit` imports `doitlib/` from its own directory, so keep the two together and
symlink the launcher onto your PATH:

```bash
mkdir -p ~/.local/bin
ln -s "$(pwd)/doit" ~/.local/bin/doit      # run from the repo root
```

Make sure `~/.local/bin` is on your PATH (add to `~/.zshrc` / `~/.bashrc` if not):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 2. Create the config file

`doit` reads `~/doit.cfg`. Copy the example and edit if needed:

```bash
cp doit.cfg.example ~/doit.cfg
```

It runs with sensible defaults even without this file; the config is how you
switch models (see below).

### 3. (Recommended) Install the shell integration

The basic single-command behavior works without this, but three features need a
small shell snippet: **`change_dir`** (a subprocess can't `cd` its parent
shell), **user-awareness** (logging the commands you type manually), and
**per-terminal session isolation** (`DOIT_SESSION`).

Append the snippet for your shell and re-source it:

```bash
# zsh
cat shell/zshrc_snippet.sh >> ~/.zshrc && source ~/.zshrc

# bash
cat shell/bashrc_snippet.sh >> ~/.bashrc && source ~/.bashrc
```

The snippet sets a per-terminal `DOIT_SESSION` id, logs your manual commands to
`~/.doit/shell_hist/`, and wraps `doit` so `change_dir` can move the parent
shell. It is documented in [report/report.pdf](report/report.pdf) (User
awareness / Changing directories sections).

---

## Usage

```bash
doit "how much disk space is left?"
doit "delete junk.txt"                 # destructive -> asks for confirmation
doit "tell me a joke"                  # off-topic  -> polite in-role refusal
doit "remember that ~/proj is my project folder"
doit "now sort them by date"           # follow-up, resolved from history
```

Set `DOIT_DEBUG=1` to see a full traceback instead of a clean error message.

---

## Switching models

Edit the `[doit]` section of `~/doit.cfg`. The three models used in the report:

| model | adapter | needs |
|---|---|---|
| `openai/gpt-4o-mini` | `native` | `OPENAI_API_KEY` |
| `ollama/qwen3:4b-instruct` | `native` | Ollama running the model |
| `ollama/gemma3:4b` | `prompted` | Ollama running the model |

For the local models, pull them first and keep Ollama running:

```bash
ollama pull qwen3:4b-instruct
ollama pull gemma3:4b
```

Set `enable_plans = false` for the ~4B local models (they plan poorly over
several steps; see the report's Further extensions section).

---

## Where state and logs live

All runtime state is under `~/.doit/`, keyed by the per-terminal `DOIT_SESSION`:

```
~/.doit/
  sessions/<id>.jsonl    # one record per turn (request, steps, outputs, answer)
  memories.json          # global facts, shared across all sessions
  shell_hist/<id>        # your manual shell commands (user awareness)
  cd_target_<id>         # change_dir hand-off, read by the shell wrapper
  logs/                  # full raw LLM requests/responses
```

The curated interaction logs cited in the report are committed under
[logs/](logs/) in this repository.

---

## Repository layout

```
doit                 # entry point (Python, no extension; symlink this onto PATH)
doitlib/             # config, llm (native + prompted adapters), context,
                     #   controller (the loop), tools, safety, state
prompts/             # system prompt + context-block templates
shell/               # zsh / bash integration snippets
acdl/                # ACDL context specs (one per version)
tests/               # offline unit suites + tests/cases.md (the case suite)
logs/                # curated interaction logs (report evidence)
report/              # the report (report.pdf) and its sources
```
