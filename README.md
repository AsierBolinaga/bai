# B.A.I

B.A.I. is a modular, private, and autonomous personal assistant. Its goal is to act as a natural, contextual, and extensible artificial intelligence system. B.A.I. operates offline by default, protecting the user's privacy, and offers online capabilities under explicit control. Its architecture enables the integration of multiple LLM engines, natural commands, personalized memory, and control over day-to-day tasks—both technical and personal.

This README documents the architecture and structure of the B.A.I system, with a modular focus for language engines and a controlled fallback to OpenAI.

---

## 🧠 General architecture

```mermaid
graph LR
    A[User (CLI)] --> B[bai.py]
    B --> C[assistant.py]
    C --> D[ai_engine.py]
    D --> E[online_engine.py]
    D --> F[offline_engine.py]
    E --> G[OpenAI]
    F --> H[local engines: llama.cpp, etc]
    D --> I[memory_engine.py]
    I --> J[boli.yaml memory + JSON history]
```

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

## 🔧 Automatic installation

```bash
./setup_bai.sh
```

This script:
- Creates and activates a virtual environment
- Installs dependencies
- Downloads the local LLM model (`mistral-7b-instruct`)
- Launches `bai.sh` (CLI interface)

---

## ✨ Useful commands (text mode)

- `Switch to offline mode`: forces use of the local engine
- `Switch to online mode`: switches back to OpenAI
- `salir`, `exit`, `quit`: exit the session
- `reset`: clears the conversation history
- `ver memoria`: shows the current history
- `recuerda que X es Y`, `aprende: Z es ...`: saves to memory

---

## 🚀 How it works

- By default, B.A.I responds using **OpenAI**
- If there is **no connection** or the user says *"Switch to offline mode"*, it uses the local model
- You can switch back to online mode with *"Switch to online mode"*
- The entire conversation is saved in `history/historial.json`
- The **personal memory context** is kept in `config/data/boli.yaml`

---

## 📁 Project structure

```
core/
├── ai_engine.py         # Chooses between online or offline engine
├── assistant.py         # Main CLI
├── memory_engine.py     # Personalized memory and history management
├── offline_engine.py    # Calls local models (e.g., llama.cpp)
├── online_engine.py     # Calls OpenAI
├── motors/              # Pluggable engines (offline)
│   └── llama_cpp_engine.py
config/
├── data/
│   ├── boli.yaml        # Personal memory
│   └── system_prompt.txt
├── motors_config.yaml   # Offline engine configuration
history/
└── historial.json       # Unified session history
```

---

## 🔌 Adding offline engines

1. Create a new file in `core/motors/my_engine.py`
2. Implement the `respond(prompt)` function
3. Register the engine in `offline_engine.py` (dictionary of available engines)
4. Add it to `motors_config.yaml` if desired

---

## 📋 Example `motors_config.yaml` configuration

```yaml
motor: llama_cpp
ruta_modelo: models/mistral-7b-instruct-v0.1.Q4_0.gguf
```

---

## 🧠 Memory and context

- `boli.yaml` stores data learned during sessions
- `system_prompt.txt` defines the assistant's base behavior
- `historial.json` is created on startup and continuously updated

---

## 🚀 Project phases (up to version 1.0.0)

1. **System initialization** – completed ✅  
2. **Modular offline/online architecture** – completed ✅  
3. **Identity customization** – completed ✅  
4. **Controlled online mode (OpenAI)** – completed ✅  
5. **Robust history and flow** – completed ✅  
6. Local engine integration `llama_cpp` 🔄  
7. Natural local learning (in progress)  
8. **Visual interface (UI)**  
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
