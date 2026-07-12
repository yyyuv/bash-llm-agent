# Output awareness — follow-up-command evidence (report-ready)

Paste-ready snippets matching `report.tex` style (`lstlisting`, named sections).
Do **not** edit `report.tex` from here — this is source material only.
Model: `openai/gpt-4o-mini`, native adapter, real zsh, 2026-07-12.
Sandbox: six files with uninformative names (`backup.tmp` 3 MB binary,
`cache.bin` 2 MB binary, `core`/`data`/`notes`/`output` small ASCII text).
Full transcript: `logs/phase9/live_output_awareness_followup_gpt4omini.txt`.

---

## For the "Output awareness" section — Example Interaction

The existing example shows the agent *answering directly* from prior output. This
second example shows the stronger case: a question the agent cannot answer from
what it already sees, so it issues a new command to inspect first.

```latex
\begin{lstlisting}[language=bash, caption={Answering via a follow-up command, not a guess.}]
$ doit "list the files here"
$ ls
backup.tmp  cache.bin  core  data  notes  output

$ doit "which of these files look safe to delete? check their types and sizes if you're unsure"
$ file backup.tmp cache.bin core data notes output    <- ran a follow-up command, did not answer blind
backup.tmp: data
cache.bin:  data
core:       ASCII text
data:       ASCII text
notes:      ASCII text
output:     ASCII text

$ doit "so based on that, which are safe to delete?"
Based on the file types and sizes: backup.tmp and cache.bin are data files ...
core, data, notes, and output are ASCII text files ...
\end{lstlisting}
```

## For the "Output awareness" section — a short Limitations note

The agent reliably reaches for an inspection command, but two weaknesses surface:

1. In single-command mode the choice to inspect all files in one command versus
   one file per turn is non-deterministic; in one run the agent checked files one
   at a time, lost track of its own progress ("No, I have not checked all files
   yet"), and only batched after an explicit "do them all at once" instruction.
2. Gathering the right facts does not guarantee the right conclusion. The delete
   verdict was inconsistent across runs and reasoned only from file type and byte
   size, ignoring obvious name cues — `backup.tmp` and `cache.bin` are the
   disposable files, yet the agent repeatedly proposed keeping them.

---

## For the "Further extensions" section — Example Interaction

When the request is genuinely multi-step, the same task triggers the `plan` tool,
which raises the per-turn command budget above the single-command default: several
`run_command` steps then run in one turn, each reading the previous command's real
output. Confirmed against the session JSONL (one turn's tool sequence shown).

```latex
\begin{lstlisting}[language=bash, caption={A single turn where plan lifts the one-command-per-turn limit.}]
$ doit "use a plan to list all files, sort them and investigate them to decide which is the safest to delete"
Plan:
  1. list all files in the current directory
  2. sort the files by size
  3. check the types and sizes of the files to determine which are safe to delete
$ ls -l                                               <- one turn, tools = [plan,
$ ls -lS                                                 run_command, run_command,
$ file backup.tmp cache.bin core data notes output       run_command, answer]
backup.tmp: data
cache.bin:  data
core:       ASCII text ...
Based on the file types and sizes: backup.tmp (3,000,000 bytes) and cache.bin ...
\end{lstlisting}
```

A second run composed `plan`, the three inspection commands, and an `ask_user`
clarification in one turn, ending on the user's reply.
