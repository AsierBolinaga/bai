# B.A.I — Boli Artificial Intelligence

B.A.I. is a modular, private, and autonomous personal assistant. Its goal is to act as a natural, contextual, and extensible artificial intelligence system. B.A.I. operates offline by default, protecting the user's privacy, and offers online capabilities under explicit control. Its architecture enables the integration of multiple LLM engines, natural commands, personalized memory, and control over day-to-day tasks—both technical and personal.

This README documents the architecture and structure of the B.A.I system, with a modular focus for language engines and a controlled fallback to OpenAI.

---

## 🧠 General architecture

```mermaid
graph LR
    A[User (CLI)] --> B[bai.py]
    B --> C[assistant.py]
    C --> D[ai_engine.py]
    D --> S[model_selector.py]
    S --> R[motors/registry.py]
    R --> G[motors/openai_engine.py → OpenAI]
    R --> H[motors/llama_cpp_engine.py]
    R --> H2[motors/gpt4all_engine.py]
    S --> K[config/motors_config.yaml]
    D --> M[memory_commands.py]
    D --> I[memory_engine.py]
    M --> I
    I --> J[facts.yaml + user_profile.yaml + JSON history]
```

### Model selection workflow

`ai_engine.py` builds the **same** message list (system prompt + personal memory +
history + user input) for both modes and hands it to `ModelSelector`, which
resolves the motor/model from `config/motors_config.yaml`:

| Mode / policy                        | Candidate order                                                        |
|--------------------------------------|------------------------------------------------------------------------|
| `offline` (default)                  | `offline.motor` → `offline.fallback[...]` — local motors only          |
| `online`, `prioridad: local` (default) | offline candidates → `online.motor` → `online.fallback[...]`          |
| `online`, `prioridad: online`        | `online.motor` → `online.fallback[...]` → *(if `fallback_offline`)* offline candidates |

**Mode policy**

- B.A.I starts in `offline` mode. Offline means *this machine only*, enforced at the
  level described in "Network isolation" below (kernel namespace by default).
- B.A.I **never switches from offline to online on its own**. Online inference is
  only possible after explicit authorization: `python bai.py --online` at launch,
  the command *"pasa a modo online"* (only when the session is not process-isolated),
  or `modo_por_defecto: online` set by the user. When no local motor can answer
  in offline mode, the assistant says so and explains how to authorize online use.
- Online inference is considered necessary only when no local motor is available
  or able to answer (`prioridad: local`), or when the user asks for it in a single
  turn with the prefix `online: <message>` (refused while in offline mode). Set
  `prioridad: online` to prefer the cloud model whenever online mode is active.
- Degrading from online to local never needs authorization (it is more private).

For every candidate the selector checks, without loading anything: registered &
implemented → `disponible()` (library installed, model file present, API key set)
→ connectivity (online motors only) → `responder()`. The first valid answer wins;
if a motor fails while generating, the next one is tried. If none can answer, the
assistant explains why for each motor (`estado` command shows the same diagnosis).

Motors never see credentials in config: the OpenAI key is read from the
`OPENAI_API_KEY` environment variable (or `.env`).

Every answer ends with a tag showing which backend produced it
(`[llama_cpp · mistral-7b-instruct-v0.1.Q4_0.gguf · offline · fallback]`);
disable with `mostrar_motor: false`. Switching mode also reports the motor that
will be used.

### Network isolation in offline mode (what is guaranteed, and by whom)

| Level (`aislamiento_offline`) | Mechanism | Guarantee | Limits |
|---|---|---|---|
| `proceso` (default, Linux) | At startup in offline mode B.A.I moves itself into a private user+network namespace (`os.unshare`, no root, no extra binaries) and brings `lo` up. | **Kernel-enforced**: no external TCP/UDP/DNS/raw traffic for the process, its subprocesses and native libraries. Loopback (IPv4/IPv6, TCP/UDP) and UNIX sockets keep working. | Irreversible for the session: *"pasa a modo online"* is refused and explains to restart with `python bai.py --online`. Local services running *outside* the namespace (e.g. a system-wide Ollama on 127.0.0.1) are unreachable. Needs Python ≥ 3.12 and unprivileged user namespaces; otherwise B.A.I falls back to `python` and says so. |
| `python` (fallback / `--aislamiento python`) | `core/network_guard.py` intercepts `socket.connect/connect_ex/sendto/sendmsg/send/sendall/sendfile`, the TLS writes `ssl.SSLSocket.send/sendall/write/sendfile/do_handshake` and the DNS functions `getaddrinfo/gethostbyname[_ex]/gethostbyaddr/getnameinfo`. Writes on sockets connected *before* activation are checked against `getpeername()`. Only loopback/UNIX destinations pass; active for the whole offline session and around every offline motor call, in every thread; blocked attempts are reported. | Covers Python code (http.client, urllib, requests, httpx, asyncio, ssl…). Allows switching to online in-session. | **Not** complete: subprocesses, native code opening sockets, direct `_socket` use, writes on the raw file descriptor (`os.write`/`os.sendfile`) and pre-saved references escape. It is process-global, so a concurrent "online" thread would also be blocked. |

`estado` always shows the level actually in force with this wording, and
`python -m core.diagnostico --probar --aislar --bloquear-red` demonstrates it.
Independently of the level: offline mode never checks connectivity, never
calls the online motor, and GPT4All always runs with `allow_download=False`
(a `true` in the yaml is ignored with a warning).

---

## ⚙️ Requirements

- Python 3.10+
- pip
- Dependencies:
  - `llama-cpp-python`
  - `openai`
  - `pyyaml`
  - `python-dotenv`
  - `unidecode`

---

## ▶️ Running

```bash
python bai.py                      # offline, process-isolated (default)
python bai.py --online             # explicitly authorize online services for this session
python bai.py --aislamiento python # offline with the Python guard (allows switching online in-session)
python bai.py --ui                 # tkinter chat window instead of the console
```

**Chat window (`--ui`)** — a tkinter window: conversation area, input
box, a short description of B.A.I and buttons for *Offline*, *Online*,
*Estado*, *Limpiar* and *Ayuda*. *Estado* displays the current mode and engine
availability in the chat. *Ayuda* displays a local guide to conversation, modes,
privacy, engines, persistent memory and session history, including how to switch
between offline and online and the limits imposed by process isolation.
Both the header description and the guide expand B.A.I as Boli Artificial Intelligence.
The same guide is
available by typing `ayuda`, `cómo funcionas` or `explícame cómo funcionas`
in the window or console, even without any available engine.
The dark theme includes rounded buttons and a rounded,
resizable input field with a focus indicator. It uses the same `ask()` as the console, so memory
requests, mode commands, offline guarantees and history behave identically; the
*Online* button is the same explicit authorization as typing *"pasa a modo
online"*. Messages are processed in a worker thread (the window never freezes),
engine fallback notices appear in the conversation, and closing the window saves
the history. The window connects to the display *before* the process isolation
is applied, so an already open connection keeps working inside the namespace.
Without a display, `--ui` exits with a message and the console keeps working.

---

## 🔧 Automatic installation

```bash
./setup_bai.sh
```

This script:
- Creates and activates a virtual environment (`venv/`)
- Installs `requirements.txt`
- Launches `bai.sh` (CLI interface)

It does **not** download a model: the download block for
`models/mistral-7b-instruct-v0.1.Q4_0.gguf` is present but commented out in
`setup_bai.sh`. Place a GGUF file in `models/` yourself (the URL is in the
script) or point `offline.motores.<motor>.model_path` to an existing file, then
check it with `python -m core.diagnostico`. `bai.sh` passes its arguments to
`bai.py` (e.g. `./bai.sh --online`). The CLI can be started from any working
directory: configuration, history and memory paths are resolved from the
project root.

---

## ✨ Useful commands (text mode)

- `Pasa a modo offline` / `Switch to offline mode`: local engines only (external connections blocked)
- `Pasa a modo online` / `Switch to online mode`: authorizes the online engine (local still preferred)
- `online: <message>`: use the online engine for this message only (requires online mode)
- `estado`: shows current mode, policy and which motors/models are available (and why not)

**Accepted syntax for mode commands** — the *whole* message must be the command
(case-insensitive; an optional `B.A.I,` vocative, `por favor`/`please`, and a
final `.`/`!` are allowed):

```
[B.A.I,] [por favor,] pasa|pasar|cambia|cambiar a[l] modo online|offline [por favor]
[B.A.I,] [please,] switch to online|offline mode [please]
```

Anything else is an ordinary message and **never** changes the mode: negations
("No quiero cambiar a modo online"), questions ("¿puedo pasar a modo online?",
"what does 'switch to online mode' do?"), quoted examples ("Explica qué significa
<<pasa a modo online>>") or a command embedded in a longer request.
- `salir`, `exit`, `quit`: exit the session
- `reset`: clears the conversation history
- `ver memoria`: shows the current history

**Memory requests (phase 7 — natural local learning)** — persistent
facts are managed with natural-language requests, in Spanish or English,
processed 100% locally (see "Memory and context" below for the guarantees):

| Operation | Example phrasings (many variants accepted) |
|---|---|
| Remember | `recuerda que mi furgoneta es una camper` · `no olvides que...` · `memoriza/aprende que...` · `ten en cuenta que...` · `remember that my van is a camper` · `don't forget that...` · `keep in mind that...` · `learn that...` · several facts at once: `recuerda que mi gato se llama Mishi y mi perro se llama Rex` |
| Retrieve | `¿qué sabes de mi furgoneta?` · `¿cuál es mi furgoneta?` · `¿recuerdas mi furgoneta?` · `¿qué recuerdas?` · `lista tus hechos` · `what is my van?` · `do you remember my van?` · `what do you remember?` · `show your facts` |
| Update | `recuerda que ahora mi furgoneta es un monovolumen` · `actualiza en tu memoria X: Y` · `actualiza/cambia/corrige en tu memoria X a Y` · `corrige tu memoria: X es Y` · `remember that now X is Y` · `update the fact X to Y` |
| Forget | `olvida mi furgoneta` · `olvídate de X` · `ya no recuerdes X` · `borra/elimina de tu memoria X` · `forget my van` · `remove X from your memory` · `olvida todo` / `forget everything` (asks for the confirmation phrase `olvida todo, confirmo` / `forget everything, confirm`) |

**Explicit memory intent is required.** Verbs that *mean* remembering or
forgetting (`recuerda`, `no olvides`, `memoriza`, `aprende`, `olvida`,
`remember`, `forget`…) work directly. Generic verbs (`guarda`, `anota`,
`apunta`, `actualiza`, `cambia`, `borra`, `elimina`, `save`, `note`, `set`,
`update`, `delete`, `remove`…) are memory requests **only** with an explicit
memory object (`en tu memoria`, `como hecho`, `el hecho X`, `in your memory`,
`the fact X`…); `guarda que mi talla es 44`, `set X to Y` or `borra X` are
ordinary messages that never save, change or delete a fact. The *whole*
message must be the request (optional `B.A.I,` vocative and `por favor`/
`please`); `online: recuerda que...` is also handled locally, in any mode.

Never written to memory: plain statements ("mi furgoneta es una camper"),
questions, assistant responses, general questions ("¿qué sabes de Python?" goes
to the model), requests containing quotation marks or example markers (`por
ejemplo`, `for example`, `e.g.`…), contradictory or chained instructions
(`recuerda que X es Y y olvídalo`, the same key with two values) and negations — `no recuerdes que...` /
`don't save...` get a local "I won't store that" reply, and a negated fact
(`recuerda que mi coche no es rojo`) gets a clarification instead of a wrong
value. Ownership is preserved: `mi coche` ≡ `el coche`, but `tu coche`,
`el coche de Ana` or `Ana's car` are different facts and partial matches never
cross owners. Ambiguous requests ("recuerda eso", several matching keys, a
value that conflicts with a stored one, "olvida todo") get a clarification/
confirmation instead of a guess.

**The complete key is resolved before any change.** With `viaje` and
`viaje a Roma` both stored, a request that could split either way
(`actualiza en tu memoria mi viaje a Roma a julio`) changes nothing and asks
for the full key; `recuerda que ahora mi viaje a Roma es en julio` or
`actualiza en tu memoria viaje a Roma: julio` only touch `viaje a Roma`.
Forgetting deletes exact keys only. A partial lookup (`¿cuál es mi número?`
with `número de la suerte` stored) is answered with key *suggestions*, never
with a value presented as confirmed. Recognizable but incomplete requests
(`recuerda`, `olvídalo`, `borra de tu memoria`, `¿recuerdas?`) are clarified
locally — also with the `online:` prefix — and never reach any backend.

---|---|
| Remember | `recuerda que mi furgoneta es una camper` · `no olvides que...` · `apunta/anota/memoriza que...` · `aprende: X es Y` · `remember that my van is a camper` · `don't forget that...` · `keep in mind that...` · `note down that...` |
| Retrieve | `¿qué sabes de mi furgoneta?` · `¿cuál es mi furgoneta?` · `¿recuerdas mi furgoneta?` · `¿qué recuerdas?` · `lista tus hechos` · `what is my van?` · `do you remember my van?` · `what do you remember?` · `show your facts` |
| Update | `actualiza mi furgoneta a un monovolumen` · `cambia X a/por Y` · `corrige: X es Y` · `recuerda que ahora X es Y` · `update X to Y` · `change/set X to Y` |
| Forget | `olvida mi furgoneta` · `olvídate de X` · `borra/elimina X` · `ya no recuerdes X` · `forget my van` · `delete/stop remembering X` · `olvida todo` / `forget everything` (asks for the confirmation phrase `olvida todo, confirmo` / `forget everything, confirm`) |

The *whole* message must be the request (optional `B.A.I,` vocative and
`por favor`/`please`). Everything else is ordinary conversation and **never**
writes to memory: plain statements ("mi furgoneta es una camper"), questions,
negations ("no recuerdes que..."), quoted examples and assistant responses.
Ambiguous requests ("recuerda eso", a value that conflicts with a stored one,
"olvida todo") get a clarification/confirmation instead of a guess.

---

## 🚀 How it works

- The starting mode is `modo_por_defecto` in `config/motors_config.yaml` (`offline` by default)
- In **offline** mode only local motors run, with all external connections blocked; B.A.I never leaves this mode by itself
- *"Pasa a modo online"* / *"Switch to online mode"* authorizes the online motor (OpenAI). With `prioridad: local` it is used only when no local motor answers, or per message with the prefix `online:`. If there is no connection/API key or the API fails, local motors answer
- *"Pasa a modo offline"* / *"Switch to offline mode"* returns to local-only
- `estado` shows the current mode, its policy and the availability of each motor/model
- The entire conversation is saved in `history/historial.json`
- The **personal memory context** is kept in `config/data/user_profile.yaml`

---

## 📁 Project structure

```
core/
├── ai_engine.py         # Builds the context, handles mode commands, calls the selector
├── ayuda.py             # Shared local description and help guide (no model required)
├── model_selector.py    # Chooses motor/model for the active mode, with fallback chain
├── network_guard.py     # Python-level guard: blocks non-local socket/DNS use in offline mode (fallback)
├── aislamiento.py       # Process-level isolation: private network namespace (kernel-enforced)
├── arranque.py          # bai.py options (--online / --offline / --ui / --aislamiento) and isolation at startup
├── diagnostico.py       # CLI diagnostics: python -m core.diagnostico [--probar] [--bloquear-red]
├── assistant.py         # Main CLI
├── ui_controlador.py    # Phase 8: window controller (no Tk): send, state, clear, save, worker thread
├── ui_tk.py             # Phase 8: tkinter chat window on top of the controller
├── memory_engine.py     # Fact store (atomic, validated) + history + memory context
├── memory_commands.py   # Phase 7: natural-language memory requests (local, deterministic)
├── offline_engine.py    # Compatibility facade: force offline motors
├── online_engine.py     # Compatibility facade: force online motors (no local fallback)
├── motors/              # Pluggable engines (online and offline)
│   ├── base.py          # Motor contract (disponible / responder), MotorError, helpers
│   ├── registry.py      # name -> module registry
│   ├── openai_engine.py
│   ├── llama_cpp_engine.py
│   ├── gpt4all_engine.py
│   └── ollama_engine.py # TODO (detected as "not implemented" by the registry)
config/
├── data/
│   ├── user_profile.yaml        # Static personal profile
│   ├── facts.yaml               # Persistent facts (created on first 'recuerda que...')
│   └── system_prompt.txt
├── motors_config.py     # Config loader (absolute paths, defaults, legacy format, validation)
├── motors_config.yaml   # Mode + online/offline motors configuration
tests/                   # pytest suite (no models, credentials or network required)
history/
└── historial.json       # Unified session history
```

---

## 🔌 Adding engines (online or offline)

The orchestrator (`ai_engine.py`, `model_selector.py`) is backend-agnostic: it
only knows the contract in `core/motors/base.py` and the registry. `llama_cpp`
is the initial local backend, not a requirement — switching to `gpt4all` (or a
new adapter) is a configuration change. Adding an adapter never touches the
orchestrator:

1. Create `core/motors/my_engine.py` implementing the contract in `core/motors/base.py`:
   ```python
   NOMBRE = "my_engine"
   TIPO = "offline"                      # or "online"
   def disponible(config) -> (bool, str) # library installed? model present? key set? (no model load, no network)
   def responder(messages, config) -> str  # raise MotorError on failure, never return error text
   ```
   Rules: import heavy libraries *inside* the functions; `messages` may contain
   several `system` entries (identity, personal memory, language instruction) —
   if your backend or its prompt formatter accepts a single system prompt, call
   `consolidar_sistema(messages)` (chat backends) or `separar_sistema(messages)`
   (plain-text backends) from `base.py` so the effective context is the same as
   for the other adapters; offline adapters must never open network connections
   (they run under the network guard and are discarded if they try).
2. Register it: `MOTORES["my_engine"] = "core.motors.my_engine"` in `core/motors/registry.py`
   (or `registry.registrar_motor(...)` at runtime).
3. Configure it in `motors_config.yaml`:
   ```yaml
   offline:
     motor: my_engine            # or add it to `fallback`
     motores:
       my_engine: {model_path: models/my-model.gguf, modelo: my-model}
   ```
`tests/test_backends.py` shows the pattern end-to-end (a fake adapter registered
and selected purely through configuration) and checks that `llama_cpp` and
`gpt4all` receive an equivalent effective context.

---

## 📋 Example `motors_config.yaml` configuration

```yaml
modo_por_defecto: offline         # offline | online
aislamiento_offline: proceso      # proceso (kernel namespace, default) | python (socket guard)

online:
  motor: openai
  prioridad: local                # local: cloud only if no local motor answers | online: cloud first
  fallback_offline: true          # (prioridad online) use local motors if no network / key / API error
  max_mensajes_contexto: 60       # history messages sent to the model
  motores:
    openai:
      modelo: gpt-4o
      temperature: 0.5
      max_tokens: 1024

offline:
  motor: llama_cpp
  fallback: [gpt4all]             # tried in order if the main motor fails
  max_mensajes_contexto: 20
  motores:
    llama_cpp:
      model_path: models/mistral-7b-instruct-v0.1.Q4_0.gguf
      n_ctx: 2048
    gpt4all:
      model_path: models/mistral-7b-instruct-v0.1.Q4_0.gguf
```

Relative paths are resolved from the project root. The old flat format
(`motor_offline` / `model_path` / `ruta_modelo`) is still accepted.

---

## 🩺 Diagnostics and real model execution

```bash
python -m core.diagnostico                         # libraries, GGUF file check, motor availability
python -m core.diagnostico --probar --bloquear-red # real offline generation with all sockets blocked
python -m core.diagnostico --modo online --probar  # online check (needs OPENAI_API_KEY)
```

Checklist for running the local model for real:

1. `pip install llama-cpp-python` (needs a C/C++ compiler + cmake, or a prebuilt wheel) and/or `pip install gpt4all`
2. Download the GGUF file to `models/` (see the URL in `setup_bai.sh`, ~4.1 GiB for Q4_0); relative paths resolve from the project root
3. Run `python -m core.diagnostico` – it validates the GGUF header (detects truncated downloads / HTML error pages saved as `.gguf`)
4. Keep `chat_format: llama-2` for Mistral-Instruct: llama-cpp-python's `mistral-instruct` format drops system messages (B.A.I's identity and memory)

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers configuration loading, the motor registry, the selection and
fallback logic for both modes, the `ai_engine` commands, memory side effects on
failed turns, the three motor adapters and the diagnostics tool. External
libraries (`openai`, `llama_cpp`, `gpt4all`) and the network are simulated, so no
model files, credentials or connection are needed.

`tests/test_real_models.py` additionally exercises the **real** llama.cpp and
GPT4All backends on a tiny GGUF model generated locally
(`tests/helpers/gguf_minimo.py`, needs `pip install gguf numpy`). These tests are
skipped automatically when the libraries are not installed.

---

## 🧠 Memory and context

Three separate stores, all injected into the context the same way for every
backend (online or offline):

- `config/data/facts.yaml` — **persistent facts** (phase 7). Written only by
  explicit natural-language requests (`recuerda que...`, `olvida...`, see the
  commands table above), interpreted locally and deterministically by
  `core/memory_commands.py` — this is memory *management*, not model training,
  and it never triggers any inference or connectivity check, in any mode.
- `config/data/user_profile.yaml` — static user profile (edited by hand).
- `history/historial.json` — conversation history, created on startup and
  continuously updated. Memory requests are control commands: they do not go
  through any motor and are not stored in the history.
- `system_prompt.txt` defines the assistant's base behavior.

**Guarantees of the fact store**

- Facts survive restarts and are injected as a system message on every turn;
  a forgotten fact is no longer injected.
- Success is reported **only after** the write to disk has completed. Writes
  are atomic (temp file + `os.replace`), so a failure mid-write never destroys
  the previous data.
- `facts.yaml` has a versioned schema (`version: 1`). A malformed file, an
  unknown schema/version or an unreadable file is reported and **never
  overwritten** (fix or rename it yourself); none of these crash a normal turn.
- Duplicates are detected ("Ya lo tenía guardado"); a conflicting value is
  **not** overwritten — B.A.I asks you to say `recuerda que ahora X es Y`.
  Updating or forgetting one fact never touches unrelated facts.
- A request with several facts is written in **one** atomic operation: either
  every accepted fact is saved or none is (and the reply says so); per-fact
  conflicts are reported line by line.
- `olvida todo` / `forget everything` requires an explicit confirmation phrase.
- **Legacy memory is migrated, not lost.** Data written by earlier phases into
  `user_profile.yaml` (`aprendido_durante_sesion` and the nested sections) is
  moved once into `facts.yaml` on first use — after a byte-for-byte backup
  `user_profile.yaml.legado-<timestamp>.bak` — so it becomes retrievable,
  editable and forgettable like any other fact. Each migrated profile entry
  is fingerprinted (`perfil_migrado` in `facts.yaml`, written atomically with
  the facts; `legado_migrado` is read as an alias), so a forgotten legacy fact
  is never re-imported or re-injected, even if emptying the profile fails or
  the old profile is restored later. Stores whose `perfil_migrado` was written
  by another version are honoured and their facts stay usable. If the marker
  identifies the current profile (a whole-profile digest), the profile counts
  as migrated. Any other marker — anything that is not one of B.A.I's own
  well-formed fingerprints (`hoja:`/`perfil:` + SHA-256), with or without a
  `:`, including unknown strings or lists inside a dictionary-shaped marker
  and a marker that is present but empty — is unrecognized and is preserved
  as such (never discarded; non-text contents reject the file as invalid
  without touching it): every profile entry that
  is not already a stored fact stays **pending reconciliation**: it is not
  imported, not injected into the context, and `user_profile.yaml` is left
  untouched — it might be a fact that was migrated and later forgotten. B.A.I
  explains this once per session and lists the pending keys; saying
  `recuerda que <clave> es <valor>` keeps an entry. A legacy value whose key
  collides with a different stored value is kept as `X (perfil anterior)`,
  `X (perfil anterior 2)`, … — never discarded. If the fact store is damaged
  or the write fails, nothing is imported, the profile is left untouched (and
  still reaches the context) and B.A.I says so.
- The conversation history is also protected: an unreadable or malformed
  `historial.json` is kept as `historial.json.corrupto-<timestamp>.bak`; if
  it cannot be moved it is left untouched and the session is saved to
  `historial-rescate-<timestamp>.json` instead of overwriting it; every start
  consolidates the previous rescue file into the current one (or into
  `historial.json` once it can be moved aside). Consolidation is idempotent:
  files that were absorbed but cannot be deleted are recorded by name and
  content hash in `<destination>.absorbidos` and skipped on later starts, so
  sessions are never duplicated. History writes are atomic.

---

## 🚀 Project phases (up to version 1.0.0)

1. **System initialization** – completed ✅  
2. **Modular offline/online architecture** – completed ✅  
3. **Identity customization** – completed ✅  
4. **Controlled online mode (OpenAI)** – completed ✅  
5. **Robust history and flow** – completed ✅  
6. **Local engine integration `llama_cpp` (mode-based model selection with fallback)** – completed ✅  
7. **Natural local learning (persistent facts managed by natural-language requests)** – completed ✅ (full suite, including the migrated `tests/test_memoria.py`, validated with controlled backends, temporary storage and fresh processes; real-model runs optional)
8. **Visual interface (UI)** – completed ✅ (dark responsive tkinter chat window with description, mode buttons, status command and local help, `python bai.py --ui`; full suite validated, window shown under a virtual display, real-screen and real-namespace runs are manual checks)
9. **Voice system**  
10. **Cross-platform compatibility**  
11. **Full synchronization across devices** ✨ → version 1.0.0 reached

---

## 🔮 Future versions post-1.0.0

Once all roadmap phases are complete, B.A.I. will keep evolving with structural and functional improvements that enable a smarter, more flexible, and more powerful experience.

### 🔀 Model combination
- Use different LLM models depending on the task type (code, QA, creativity)
- Model chaining (one generates, another refines)
- Future: weight merging (model merging)

### 🧩 Dynamic engine selection
- Automatic choice between engines (GPT4All, Ollama...)
- Criteria: prompt type, performance, connectivity
- User-adjustable prioritization in real time

### 🧠 Memory optimization
- Message importance (`low`, `high`, `critical`)
- Smart pruning based on context
- Natural temporal references ("a few days ago", "last time")


- 🧩 Combining LLM models for different tasks
- 🎛️ Visual or web configuration
- 🗣️ Voice mode with local hotword
- 📱 Mobile app and Car Launcher integration
- 📊 Memory analysis and prioritization
- 🔌 Scripts via natural commands ("turn on lights", "open VSCode")

---

## 📉 Planned versions after v1.0.0

### 📌 Version 1.1.0 – Automations and scripts
- Launch scripts via natural commands ("turn on the living room PC")
- Control recurring tasks (workouts, backups, updates)

### 📌 Version 1.2.0 – Custom command interface
- Commands like `bai workout start`
- Aliases by voice or text

### 📌 Version 1.3.0 – Local listening mode
- Hotword activation ("B.A.I.")
- Offline speech recognition (Whisper, Vosk)

### 📌 Version 1.4.0 – Mobile app / Car Launcher integration
- Connection with Android head unit and Car Launcher Pro
- Co-pilot-style travel module (navigation, calls, music)

### 📌 Version 1.5.0 – Visual panel and control console
- Web or local UI, terminal-like
- Control modules, logs, and configuration
