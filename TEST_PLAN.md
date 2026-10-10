# MC Local AI Bot — Test & Validation Plan (Windows 1.20.4 Survival)

> **Document Status:** Operational Reference & Verification Standard  
> **Target Version:** Minecraft Java Edition 1.20.4  
> **Platform:** Windows 11 (PowerShell 7 / 5.1), Node.js v18+, Python 3.10+, Java 21 OpenJDK, Ollama (Qwen 2.5 3B / 7B)  
> **Current Baseline:** 84 / 84 Tests Passing (100% OK), Complete Run Isolation (`runs/<run_id>/`)

---

## 1. Architecture & Verification Principles

The MC Local AI Bot operates as a dual-runtime co-op survival agent designed to conquer Minecraft 1.20.4 from scratch to the Ender Dragon and End Cities.

```
       ┌────────────────────────────────────────────────────────┐
       │                Python Brain / Orchestrator             │
       │  (AutonomousCoopBrain, Progression Tree, Loop Breaker) │
       └──────────────┬──────────────────────────▲──────────────┘
                      │ Actions & Goals          │ State Telemetry & Chat
                      ▼                          │
       ┌─────────────────────────────────────────┴──────────────┐
       │              WebSocket Bridge (core/bridge.py)         │
       └──────────────▲──────────────────────────┬──────────────┘
                      │ JSON-RPC                 │ Commands
                      │                          ▼
       ┌──────────────┴─────────────────────────────────────────┐
       │          Mineflayer Worker (minecraft_bot/bot.js)      │
       │  (Reflexes, Combat Cooldowns, Pathfinding, Drops)      │
       └──────────────┬──────────────────────────▲──────────────┘
                      │ Packets                  │ World Packets
                      ▼                          │
       ┌─────────────────────────────────────────┴──────────────┐
       │     Minecraft Dedicated Server 1.20.4 (Java 21)        │
       └────────────────────────────────────────────────────────┘
```

### Core Verification Principles

1. **Fast Reflexes in Code, Long-Term Strategy in LLM:**
   - **Mineflayer (JavaScript, Sub-200ms):** Attack cooldown delays (`getWeaponCooldownMs`), jump-critical downward strikes, shield blocking (`off-hand` item activation against arrows/creepers), Ghast fireball reflection, emergency splash healing, drop collection, and death coordinate capture.
   - **Python Orchestrator & LLM (Ollama / Qwen):** Progression milestones, technology tree advancement, resource budgeting, villager trades, Nether fortress scouting, dragon attack sequencing, and loop breaking.
2. **Zero-Mock Policy on Windows:**
   - Production validation exercises real binaries without mocking the game engine: real Java 1.20.4 Mojang `server.jar`, real Mineflayer worker process, and real WebSocket bridge.
   - Mock simulations are strictly reserved for unit tests where external daemons (e.g. Ollama LLM) are offline, and are explicitly tagged (`"mock": true`).
3. **Run Isolation Philosophy:**
   - No two runs share mutable execution state. Each execution generates a deterministic, collision-free `run_id` (`YYYYMMDD-HHMMSS_<commit>` or `test_*` / `benchmark_*`).
   - Every log message, decisions dataset, benchmark sample, and test report is directed into an isolated directory: `runs/<run_id>/`.
   - Production databases and dataset archives are protected from synthetic test mutations via environment overrides (`MC_DB_PATH`, `MC_RUN_ID`).

---

## 2. Prerequisites & Environment Setup

### 2.1 Hardware & Operating System
- **OS:** Windows 10 / 11 (64-bit)
- **Shell:** Windows PowerShell or PowerShell Core (`pwsh`)
- **GPU:** NVIDIA RTX 3060 (6 GB VRAM) or equivalent supporting 4-bit / 8-bit local LLM inference
- **RAM:** 16 GB+ recommended (server allocates 256MB–768MB, Ollama uses ~2.5GB VRAM)

### 2.2 System Runtimes & Binaries
Verify all required runtimes from PowerShell:

```powershell
# 1. Python (3.10+ required, 3.12 verified)
python --version

# 2. Node.js (18+ required, 20/22 verified)
node --version
npm --version

# 3. Java Development Kit (Java 21 OpenJDK required for Minecraft 1.20.4)
java --version

# 4. Git CLI
git --version

# 5. Ollama Daemon
ollama --version
```

If Java 21 is not globally in `PATH`, the test suite automatically probes known Windows paths:
- `C:\Program Files\Java\jdk-21\bin\java.exe`
- `C:\Program Files\Eclipse Adoptium\jdk-21\bin\java.exe`
- `C:\Program Files\Android\Android Studio\jbr\bin\java.exe`
- Or configured via environment variable `JAVA_HOME`.

### 2.3 Dependency Installation

```powershell
# Clone and enter workspace
cd "c:\Users\omerf\OneDrive\Desktop\Projeler tümü\education_app\Kick_asistan"

# Install Python packages
pip install -r requirements.txt

# Install Node.js Mineflayer dependencies
cd minecraft_bot
npm install
cd ..
```

### 2.4 Local LLM Model Setup (Ollama)

Before launching the bot or running model benchmarks, download the required local models into Ollama:

```powershell
# 1. Pull the primary model used by the bot (configured in utils/config.py: OLLAMA_MODEL = "qwen2.5:3b")
ollama pull qwen2.5:3b

# 2. Pull the 7B comparison model used for benchmarks (measures latency & VRAM headroom on 6GB RTX 3060)
ollama pull qwen2.5:7b

# 3. Verify installed models
ollama list
```

Expected verification output (`ollama list` displays both models):
```text
NAME               ID              SIZE      MODIFIED
qwen2.5:3b:latest  f8820c78a3f6    1.9 GB    ...
qwen2.5:7b:latest  b83d78e96da8    4.7 GB    ...
```

#### Custom Speedrunner Model (`mc-qwen:3b`)
The repository includes a specialized Modelfile at `models/Modelfile` containing custom system instructions and tuned inference parameters (`temperature: 0.1`, `top_p: 0.8`, `num_ctx: 2048`, `num_gpu: 999` based on `FROM qwen2.5:3b`).
To create and use this custom model:
```powershell
# Build custom model from repository Modelfile
ollama create mc-qwen:3b -f models/Modelfile
```
To run the bot with this custom model, set `OLLAMA_MODEL=mc-qwen:3b` in `.env`.
*(Note: By default in `utils/config.py`, the default model is `OLLAMA_MODEL = "qwen2.5:3b"`).*

### 2.5 Configuration (.env)
Create a `.env` file at the root or verify default settings against `.env.example`:

```env
# Minecraft Server
MINECRAFT_HOST=localhost
MINECRAFT_PORT=25565
MINECRAFT_USERNAME=AIAssistant
MINECRAFT_VERSION=1.20.4

# Ollama Local LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b

# WebSocket Bridge
BRIDGE_HOST=127.0.0.1
BRIDGE_PORT=8765

# Bot Identity
BOT_NAME=AIAssistant
BOT_OWNER=Omer
LOG_LEVEL=INFO
COOLDOWN_SECONDS=0.2
```

---

## 3. Run Isolation & Artifact Hierarchy

Every execution (production bot run, unit test run, or model benchmark) creates an isolated directory in `runs/<run_id>/`.

### 3.1 Run Identifier Format
The `run_id` is generated by `utils/run_context.py`:
- **Standard Bot Run:** `YYYYMMDD-HHMMSS_<commit_hash>` (e.g., `20261010-183000_36cd98b`)
- **Test Session:** `test_YYYYMMDD-HHMMSS_<commit_hash>` (e.g., `test_20261010-183425_05ff104`)
- **Benchmark Session:** `benchmark_YYYYMMDD-HHMMSS_<commit_hash>`
- **Environment Override:** Passing `MC_RUN_ID="my_custom_run"` forces the exact run ID.

### 3.2 Directory Layout

```
runs/
└── <run_id>/
    ├── run_meta.json        # Session metadata: commit, timestamp, duration, model, test status
    ├── bot.log              # Dedicated Python orchestrator & Node.js worker logs
    ├── decisions.jsonl      # Run-specific in-game state -> decision -> delta execution logs
    ├── results.json         # Benchmark performance summary metrics (if benchmark run)
    ├── samples.jsonl        # Raw model prompt responses & latencies (if benchmark run)
    ├── test_report.json     # Machine-readable test execution report (if test run)
    ├── server_latest.log    # Mirrored Minecraft Java 1.20.4 server log (if live server test)
    └── node_worker.log      # Raw Mineflayer stdout/stderr trace (if captured)
```

### 3.3 Database Run Tracking & Isolation
- **Environment Database Redirection:** Setting `MC_DB_PATH="path/to/test.db"` directs SQLite operations to an isolated database.
- **Runs Table Schema:**
  ```sql
  CREATE TABLE runs (
      run_id TEXT PRIMARY KEY,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      commit_hash TEXT DEFAULT '',
      is_test INTEGER DEFAULT 0,
      model_name TEXT DEFAULT '',
      notes TEXT DEFAULT ''
  );
  ```
- **Backward-Compatible Schema Migration:**
  All existing gameplay tables (`progression_checkpoints`, `death_points`, `beds`, `chests`, `ore_map`, `chat_history`) automatically verify and append the column:
  ```sql
  ALTER TABLE <table_name> ADD COLUMN run_id TEXT DEFAULT '';
  ```
  Legacy data without `run_id` is preserved with empty strings, ensuring backward compatibility.

### 3.4 Starting the Bot (Live Gameplay) / Botu Başlatma (Canlı Oyun)

#### 1. Prerequisites (Ön Koşullar)
- Ollama daemon is running locally (`ollama serve` or active background service at `http://localhost:11434`).
- Target model is downloaded and verified (`ollama list` shows `qwen2.5:3b` or `mc-qwen:3b`).
- Target Minecraft Java 1.20.4 server is running on the host/port configured in `.env`.

#### 2. Launch Commands (Başlatma Komutları)
- **Windows Automated Script (`run.bat`):**
  Checks for `.env` (copies from `.env.example` if missing), verifies Ollama connectivity on `http://localhost:11434` (attempts background start if offline), and executes `python main.py`:
  ```cmd
  run.bat
  ```
- **Direct CLI Execution (PowerShell / Terminal):**
  ```powershell
  # Standard autonomous survival run:
  python main.py

  # Flagged as test session (generates test_* run_id, flags is_test: true):
  python main.py --test

  # Custom run identifier with test isolation:
  python main.py --run-id live_eval_session_01 --test

  # With isolated SQLite database path:
  python main.py --db-path data/eval_gameplay.db --test
  ```

#### 3. Configuration Variables (`utils/config.py`)
All settings are loaded dynamically via `Config.load_from_env()`:
- `MINECRAFT_HOST`: Minecraft server IP or hostname (default: `"localhost"`).
- `MINECRAFT_PORT`: Minecraft server port (default: `25565`).
- `MINECRAFT_USERNAME`: Bot player username in world (default: `"AIAssistant"`).
- `MINECRAFT_VERSION`: Minecraft version (default: `""`; auto-detected by Mineflayer when empty).
- `BOT_NAME`: In-game bot name (default: `"AIAssistant"`).
- `BOT_OWNER`: Teammate/human player username to protect and co-op with (default: `"Omer"`).
- `OLLAMA_BASE_URL`: Ollama endpoint (default: `"http://localhost:11434"`).
- `OLLAMA_MODEL`: Target model name (default: `"qwen2.5:3b"`).
- `BRIDGE_HOST` & `BRIDGE_PORT`: Local WebSocket bridge (defaults: `"127.0.0.1"` and `8765`).
- `COOLDOWN_SECONDS`: Throttle interval between bot actions (default: `0.2`).
- `MC_RUN_ID`: Active run identifier override (default: dynamic `generate_run_id()`).
- `MC_DB_PATH`: SQLite database file path (default: `"minecraft_bot.db"`).

#### 4. Expected Initial Log Sequence (Başlatma Sonrası Beklenen Loglar)
Upon launch, the orchestrator outputs structured logs and creates run artifacts:
```text
[2026-10-10 18:30:00] [INFO] [20261010-183000_5edfa5e] [Main]: Starting Minecraft Local AI Bot...
[2026-10-10 18:30:00] [INFO] [20261010-183000_5edfa5e] [Bridge]: WebSocket bridge server listening on 127.0.0.1:8765
[2026-10-10 18:30:00] [INFO] [20261010-183000_5edfa5e] [Main]: Spawning Mineflayer worker process (node minecraft_bot/bot.js)...
[2026-10-10 18:30:02] [INFO] [20261010-183000_5edfa5e] [Main]: [Node.js] [Minecraft] 🌟 Bot successfully spawned into the world!
[2026-10-10 18:30:02] [INFO] [20261010-183000_5edfa5e] [Main]: ✨ AIAssistant spawned into the world! Health: 20
[2026-10-10 18:30:02] [INFO] [20261010-183000_5edfa5e] [Bridge]: Broadcast chat: "Hello Omer! I am AIAssistant, ready to explore and beat the game."
```
Verified Artifacts Created:
- `runs/<run_id>/bot.log` receives all formatted Python and Node.js logs.
- `runs/<run_id>/run_meta.json` is initialized with `"status": "starting"`, commit hash, timestamp, and model name.
- `runs/<run_id>/decisions.jsonl` begins logging structured state-action-outcome decisions.

#### 5. Graceful Termination & Finalization (Durdurma)
- Press `Ctrl+C` in the console to trigger graceful shutdown.
- Signal handler receives `SIGINT`/`SIGTERM` and sets shutdown event:
  `⚠️ Received signal 2. Initiating graceful shutdown...`
- Orchestrator cancels progression loop, disconnects WebSocket bridge, closes Ollama session, and terminates Node.js subprocess cleanly.
- Code explicitly finalizes `runs/<run_id>/run_meta.json` (`main.py:533-539` via `write_run_metadata`):
  ```json
  {
    "status": "completed",
    "summary": "Bot shutdown complete cleanly",
    "duration_seconds": 124.5
  }
  ```
- Console confirms: `👋 Bot shutdown complete.`

---

## 4. Unit & Integration Test Suite

### 4.1 Test Catalog by Progression Phase

| Phase | Test File | Covered Features & Acceptance Criteria |
| :--- | :--- | :--- |
| **Infra** | `tests/test_run_isolation.py` | `run_id` generation, directory creation, log filter, DB migrations, dataset dual write, benchmark persistence, server log capture, test report serialization. |
| **F0.1** | `tests/test_live_server_integration.py` | Live Mojang 1.20.4 server boot, Mineflayer worker spawn, WebSocket bridge handshake, chat echo, clean shutdown, log mirroring. |
| **F0.2–F0.4** | `tests/test_action_results_and_recovery.py` | Action schemas (`items_delta`, `duration_ms`), death point persistence, unrecovered corpse navigation, nearest-first drop collection. |
| **F1.1–F1.3** | `tests/test_v2_phase1_lifecycle.py` | `smartPlaceBed` placement, night sleep, phantom risk scoring, animal breeding, fishing, chest sorting & storage. |
| **F2.1–F2.5** | `tests/test_v2_phase2_phase3.py` | Anvil gear repair, villager trading, potion brewing, 3D ore spatial mapping, spare iron tool crafting. |
| **F3.1–F3.4** | `tests/test_v2_phase2_phase3.py` | Weapon cooldowns (`getWeaponCooldownMs`), jump-critical strikes, shield block reflex, Skeleton LOS cover break, Zombie barrier funneling. |
| **F4.1–F4.6** | `tests/test_v2_phase2_phase3.py` | Nether cobblestone outpost, Piglin gold bartering, Hoglin hunting, respawn anchor, Nether fortress search, Bastion raiding. |
| **F5.1–F5.4** | `tests/test_v2_phase2_phase3.py` | Stronghold eye throw, End Portal activation, End Crystal demolition, End City navigation, Elytra rocket flight, tactical Chorus Fruit void escape. |
| **F6.1–F6.3** | `tests/test_export_sft.py` | ChatML training sample formatting, teacher corrections, synthetic test run filtering, golden speedrun synthesis. |
| **Tactics** | `tests/test_planner_tactics.py` | Stuck loop breaking (3 repeated actions without progress), starvation meat hunt, emergency bunker construction. |
| **Combat** | `tests/test_dragon_fight.py` | Ender Dragon phases: perching melee attack, projectile crystal demolition, perch recovery. |
| **Craft** | `tests/test_farming_and_shelter.py` | Crop harvesting, hoe tilling, dirt bunker construction with door and light. |
| **Enchant** | `tests/test_enchanting_and_blueprints.py` | Enchanting table placement, 15 bookshelves, Lapis Lazuli validation, shelter templates. |
| **Hardware**| `tests/test_tasks_and_gpu.py` | Player task queue priority sorting, Ollama GPU warmup, latency tracking. |
| **Data** | `tests/test_dataset_and_prompt.py` | System prompt generation, schema validation, decision JSON parser. |

### 4.2 Executing the Test Suite

Execute the entire test suite using the machine-readable runner:

```powershell
# Run full suite with standard summary
python scripts/run_tests.py

# Run with verbose per-test timing and status
python scripts/run_tests.py -v

# Run with fail-fast (stop on first failure)
python scripts/run_tests.py -f

# Run tests matching a specific pattern
python scripts/run_tests.py --pattern "test_run_isolation.py"
```

### 4.3 Expected Console Output

```text
=================================================================
📋 TEST SUITE SUMMARY (Run ID: test_20261010-153425_05ff104)
=================================================================
  • Total Tests  : 84
  • Passed       : 84 (✅)
  • Failed       : 0 (❌)
  • Errors       : 0 (💥)
  • Skipped      : 0 (⏭️)
  • Success Rate : 100.0%
  • Duration     : 27.87s
-----------------------------------------------------------------
📁 Machine-readable report saved to:
   runs\test_20261010-153425_05ff104\test_report.json
=================================================================
```

---

## 5. Live Server Validation (F0.1)

The live server integration test exercises the full production pipeline without mocking:

1. **Server Initialization:**
   - Automatically downloads the official Mojang 1.20.4 `server.jar` if not already present.
   - Launches `server.jar` in a subprocess using Java 21 (`-Xms256M -Xmx768M nogui`).
   - Polls `test_server/logs/latest.log` until `Done (` is logged (typically 6–12 seconds).
2. **Worker Spawn & Handshake:**
   - Starts Python WebSocket bridge on dedicated port `8769`.
   - Spawns Mineflayer `bot.js` connecting to `127.0.0.1:31313`.
   - Waits for bot spawn event in the Minecraft world, verifying `health: 20`, `food: 20`, and valid coordinates.
3. **Bidirectional Communication:**
   - Sends `say_chat` action packet; verifies broadcast into Minecraft chat.
   - Dispatches `stop_actions` command to ensure pathfinder terminates cleanly.
4. **Teardown & Log Capture:**
   - Issues `stop` command to dedicated server stdin; waits for clean exit.
   - Automatically copies `test_server/logs/latest.log` to `runs/<run_id>/server_latest.log`.

### Running the Live Server Test

```powershell
python -m unittest tests/test_live_server_integration.py
```

---

## 6. Model Benchmarking (F6.3)

Compares decision latency, format validity, and tactical milestone accuracy between models (e.g. `qwen2.5:3b` vs `qwen2.5:7b`).

### 6.1 Evaluation Metrics
1. **JSON Format Validity Rate (%):** Parses cleanly as JSON or contains an extractable JSON block.
2. **Tool Call Schema Compliance (%):** Contains valid `tool_calls` structure with target tool name and parameter dictionary.
3. **Decision Latency (ms):** Average and p95 elapsed roundtrip time.
4. **Tactical Accuracy (%):** Chooses the canonical optimal survival tool across canonical benchmark prompts (wood gathering, shield crafting, raw iron smelting, emergency bunker, Nether Piglin bartering, End Crystal demolition, anvil repair).

### 6.2 Running the Benchmark

```powershell
# Live Ollama evaluation (Ollama must be running: ollama serve)
python scripts/benchmark_models.py --models qwen2.5:3b qwen2.5:7b

# Offline deterministic simulation (when Ollama daemon is offline)
python scripts/benchmark_models.py --mock
```

> **Offline Protection:** If Ollama is offline and `--mock` is omitted, the script exits immediately with a clean error message and setup instructions, preventing silent mock fallback.

### 6.3 Benchmark Output Artifacts
Results are written to `runs/<run_id>/`:
- `results.json`: Summary metrics, model parameters, latency percentiles, and `"mock": true/false` tag.
- `samples.jsonl`: Full trace of every tested prompt, generated text, parsed tool call, and latency.

---

## 7. Dataset Export & SFT Pipeline

The SFT pipeline (`export_sft_dataset.py`) converts recorded in-game gameplay memory into high-quality ChatML training datasets for Unsloth 4-bit QLoRA fine-tuning.

### 7.1 Data Curation & Teacher Corrections
Raw steps in `data/minecraft_decisions.jsonl` are cleaned:
1. **Plank Harvesting Correction:** Remaps `collect_block("planks")` to `collect_block("log")` since planks must be crafted.
2. **Smelting Correction:** Remaps `craft_item("iron_ingot")` to `smelt_item("raw_iron")`.
3. **Cherry / Mangrove Log Preservation:** Preserves non-oak log crafting decisions as valid progression.
4. **Failure Deduplication:** Limits failed actions (e.g., repeated failed hunts) to at most 2 examples to prevent model degradation.
5. **Idle Filtering:** Strips redundant idle actions (`stop_actions`, `list_saved_locations`) when no player instruction is active.

### 7.2 Test Data Isolation
Records originating from test runs (`run_id` starting with `test_` or `is_test: true`) are **strictly excluded** by default, preventing synthetic mock data from contaminating the training set.
To include test runs for diagnostic evaluations, pass `--include-test-runs`.

### 7.3 Golden Speedrun Augmentation
When recorded in-game samples are fewer than the requested target (default: 350), the pipeline synthesizes canonical speedrun milestone samples covering:
- Wood Age (`collect_block`, `craft_item: crafting_table`, `craft_item: wooden_pickaxe`)
- Stone Age (`collect_block: stone`, `craft_item: stone_pickaxe`, `craft_item: furnace`)
- Iron Age (`collect_block: iron_ore`, `smelt_item: raw_iron`, `craft_item: shield`)
- Diamond & Nether (`collect_block: diamond_ore`, `build_nether_portal`, `build_nether_outpost`)
- The End (`throw_eye_of_ender`, `activate_end_portal`, `destroy_end_crystals`, `fight_ender_dragon`)

### 7.4 Running the Exporter

```powershell
python export_sft_dataset.py --min-samples 350 --val-ratio 0.1
```

Generated outputs:
- `data/sft_train.jsonl` (ChatML training split)
- `data/sft_val.jsonl` (ChatML validation split)

---

## 8. End-to-End Autonomous Survival Validation Checklist

Use this checklist during live gameplay observation to verify that all systems operate autonomously.

### Overworld Phase
- [ ] **Spawn & First Wood:** Bot spawns, locates trees, collects 3–5 logs, crafts planks, crafting table, and wooden pickaxe.
- [ ] **Stone Upgrade:** Mines 3 cobblestone, crafts stone pickaxe and stone sword.
- [ ] **Bed & Shelter:** Crafts or locates bed, executes `smartPlaceBed`, and sleeps at night to prevent Phantom spawns.
- [ ] **Iron Smelting & Shield:** Mines raw iron and coal, places furnace, smelts iron ingots, and crafts a shield for off-hand defense.
- [ ] **Farming & Food:** Harvests wheat, breeds cows/sheep with seeds/wheat, or fishes when hunger $\le 14$.
- [ ] **Corpse Recovery:** Upon death, logs coordinates to SQLite, respawns, navigates back to death coordinates within 5 minutes, and recovers items.
- [ ] **Diamond Gear:** Mines at $Y = -58$, discovers diamond vein, logs coordinates to `ore_map`, crafts diamond pickaxe and sword.

### Nether Phase
- [ ] **Portal & Outpost:** Builds obsidian portal, lights with flint and steel, enters Nether, and constructs a fortified cobblestone outpost at entry.
- [ ] **Piglin Barter:** Equips gold armor, approaches piglins, drops gold ingots, and collects Ender Pearls and Fire Resistance potions.
- [ ] **Fortress Exploration:** Navigates 3D Nether chunks, locates fortress, defeats Blazes, and collects Blaze Rods.
- [ ] **Tactical Defense:** Deflects Ghast fireballs using sword strike; builds emergency bunker if health $\le 6$.

### The End Phase
- [ ] **Stronghold Navigation:** Crafts Eyes of Ender, throws periodically, follows trajectory, and excavates into Stronghold.
- [ ] **Portal Activation:** Inserts 12 Eyes of Ender into frame blocks and enters the End dimension.
- [ ] **Crystal Demolition:** Uses bow or blocks to destroy End Crystals on obsidian pillars.
- [ ] **Dragon Combat:** Waits for dragon perching phase; applies jump-critical downward strikes with diamond sword; consumes Golden Apple if HP $\le 8$.
- [ ] **Outer End & Elytra:** Enters End Gateway via pearl, locates End City, uses shield against Shulker bullets, loots Elytra from End Ship, and equips it.
- [ ] **Void Rescue:** If falling into the void, consumes Chorus Fruit for immediate random teleport back to solid ground.
