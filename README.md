# 🎮 MC Local AI Bot

> **Autonomous Human-Like Minecraft Co-op Companion Powered 100% Locally by Ollama & Mineflayer**

[![Status: Production Ready](https://img.shields.io/badge/status-active%20release%20(v0.7.0)-brightgreen.svg)](IMPLEMENTATION_ROADMAP.md)
[![Progress: 100%](https://img.shields.io/badge/progress-100%25%20(Phase%207%20Complete)-brightgreen.svg)](IMPLEMENTATION_ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Node.js: 18+](https://img.shields.io/badge/node.js-18%2B-green.svg)](https://nodejs.org/)
[![LLM: Ollama](https://img.shields.io/badge/LLM-Ollama%20(Qwen%202.5)-purple.svg)](https://ollama.com/)

---

> [!NOTE]
> ### 🏆 Project Status: Feature-Complete (v0.7.0)
> **MC Local AI Bot has completed all core roadmap phases!**  
> - **Phases 1-3:** Autonomous survival, mining, recursive crafting, smelting, dimension safety, Nether portal construction, Blaze hunting, Stronghold tracking, and End Portal activation.
> - **Phase 4:** End Crystal demolition, Ender Dragon perch combat & bed bombing, victory XP harvesting, exit fountain completion, and one-click launch scripts (`run.bat` / `run.sh`).
> - **Phases 5-6:** Sustainable farming & bread engine, universal emergency shelter, autonomous enchanting & XP engine, tactical Nether outposts, void bridging, RTX GPU offloading.
> - **Phase 7:** Full-project audit, concurrency hardening, survival interrupt system, safe dragon combat, bridge action ID tracking.
> Community contributions, pull requests, and bug reports are warmly welcomed!

---

## 🌟 Overview

**MC Local AI Bot** is an embodied AI agent designed to play vanilla survival Minecraft as a genuine co-op teammate alongside you. Unlike cloud-based agents that cost money per token, this bot runs **entirely on your local machine** using [Ollama](https://ollama.com/) and models like **Qwen 2.5 (3B / 7B)** or **Llama 3**.

The bot perceives its 3D environment, manages its hunger and health, crafts tools recursively, builds Nether portals, and aims to reach the End to defeat the Ender Dragon—all with **zero cloud dependencies, zero API costs, and complete privacy**.

---

## 📐 Architecture

The bot uses an asynchronous decoupled architecture separating high-level strategic reasoning from low-level real-time tick execution:

```
+-------------------------------------------------------------+
|                     Minecraft Server                        |
|             (Paper / Fabric / Vanilla / LAN)                |
+-------------------------------------------------------------+
                              ▲
                              │ Minecraft Protocol (TCP)
                              ▼
+-------------------------------------------------------------+
|             Mineflayer Worker (Node.js Engine)              |
|  - Real-time pathfinding (A*), block perception & spatial   |
|  - Recursive smartCraft & smartSmelt engine                 |
|  - Off-hand shield defense & tool durability monitor        |
|  - Autonomous Nether portal builder & End portal activator  |
+-------------------------------------------------------------+
                              ▲
                              │ WebSocket Bridge (JSON RPC)
                              ▼
+-------------------------------------------------------------+
|              Python AI Orchestrator (Brain)                 |
|  - Strategic Decision Engine & Speedrun Tech-Tree Planner   |
|  - Emergency Reflex System (Health <= 6 / Food <= 4)        |
|  - Dimension Safety Guard (Exploding bed prevention)        |
|  - SQLite Persistent World Memory & Player Task Queue       |
+-------------------------------------------------------------+
                              ▲
                              │ HTTP REST API (Function Calling)
                              ▼
+-------------------------------------------------------------+
|                   Local LLM Engine (Ollama)                 |
|           qwen2.5:3b (default) / qwen2.5:7b / llama3        |
+-------------------------------------------------------------+
```

---

## 🚀 Key Capabilities

### 🧠 100% Local & Free AI Reasoning
- Powered by **Qwen 2.5 3B/7B** running locally through Ollama.
- Native function calling / tool calling schemas (`craft_item`, `collect_block`, `smelt_item`, `build_nether_portal`, etc.).
- Sub-second local inference with connection pooling and emergency fallbacks.

### ⛏️ Autonomous Survival Engine
- **Resource Gathering**: Universal tag matching for all wood species, stone/deepslate variants, and vanilla ores.
- **Recursive Crafting (`smartCraft`)**: Automatically checks and crafts prerequisite materials (e.g. logs $\to$ planks $\to$ sticks $\to$ crafting table $\to$ pickaxe) on the fly.
- **Autonomous Smelting (`smartSmelt`)**: Places a furnace, fuels it with coal or wood, smelts ores or cooks meat, and recovers the furnace when done.
- **Combat & Hunting**: Equips swords/axes, wields shields in the off-hand, hunts food animals when hungry, and defends against hostile mobs.

### 🌌 Nether & End Progression (Phase 3 Complete)
- **Nether Portal Construction (`build_nether_portal`)**: Gathers $\ge 10$ obsidian and flint & steel, finds a flat spot, constructs a vertical $4 \times 5$ frame with scaffolding, ignites the portal, and enters the Nether.
- **Blaze Hunting & Stronghold Tracking (`throw_eye_of_ender`)**: Defeats Blazes, crafts blaze powder and Eyes of Ender, throws eyes into the sky, and calculates trajectory angle and coordinates to the Stronghold.
- **End Portal Activation (`activate_end_portal`)**: Scans for 12 End portal frame blocks, inserts Eyes of Ender into empty sockets, and activates the End Portal.

### 🐉 Boss Combat & Game Completion Engine (Phase 4 Complete)
- **End Crystal Demolition (`destroy_end_crystals`)**: Scans for `end_crystal` entities atop obsidian towers, snipes them safely with bows/crossbows or scaffolds up with shield deflection.
- **Ender Dragon Combat (`fight_ender_dragon`)**: 
  - **Perch Phase**: Rushes to the central bedrock fountain (0, 65, 0) and unloads melee jump criticals or high-explosive **Bed Bombing**.
  - **Flight Phase**: Evades purple dragon breath clouds (`area_effect_cloud`) and raises shield against diving attacks.
- **Victory & Exit Fountain (`enter_exit_portal`)**: Saps the 68 levels of fallen dragon XP orbs and enters the central exit portal to beat the game.

### 🌾 Sustainable Farming & Bread Engine
- **Hay Bale Harvesting (`farm_crops`)**: Rapidly scans villages and plains for `hay_block`s. Automatically converts 1 hay bale into 9 wheat $\to$ 3 loaves of fresh bread (providing 60+ loaves in minutes).
- **Crop Lifecycle & Farmland**: Harvests mature wheat, carrots, and potatoes, replants seeds on farmland, and tills dirt near water with hoes.

### 🏰 Universal Emergency Shelter & Burrowing
- **Universal Solid Block Support (`build_shelter`)**: Constructs 360-degree protective bunkers using **ANY solid block** in Minecraft (cobblestone, deepslate, dirt, sandstone, tuff, planks, netherrack, etc.).
- **Zero-Resource Burrowing (`burrow`)**: If unarmed with zero blocks, digs 3 blocks deep into the terrain and seals the roof with a mined block for 100% immunity to mobs.
- **Interior Lighting & Safe Breakout (`break_out_shelter`)**: Places torches inside to prevent monster spawns, and mines an exit once daylight arrives and health regenerates.

### ✨ Autonomous Enchanting & XP Engine
- **XP & Catalyst Management (`enchant_gear`)**: Tracks player XP levels (levels 15–30) and lapis lazuli catalyst availability. Automatically places and uses Enchanting Tables.
- **Optimal Gear Buff Priorities**: Prioritizes Diamond Weapons (`Sharpness`, `Looting`), Diamond Armor (`Protection`, `Unbreaking`), Bows (`Power`, `Infinity`), and Pickaxes (`Efficiency`, `Fortune`).
- **Pipeline Automation**: Manages sugar cane $\to$ paper $\to$ book $\to$ bookshelf chains, optimizing 15-bookshelf perimeter geometry for Level 30 max enchants.

### 🛡️ Tactical Nether Outposts & Void Bridging
- **Ghast-Proof Forts (`build_nether_outpost`)**: Encases Nether portals in blast-resistant cobblestone/blackstone (blast resistance $\ge 6$), ensuring Ghast fireballs cannot extinguish portals or leave the team stranded.
- **Safe Crouch-Bridging (`bridge_chasm`)**: Activates `sneak` controls to bridge across lava lakes or End void chasms without ever falling off edges.

### 🛡️ Dimension Safety & Health Reflexes
- **Exploding Bed Prevention**: Strictly forbids bed sleeping in `the_nether` and `the_end`, preventing catastrophic explosions.
- **Emergency Reflexes**: Bypasses LLM cooldown instantly when health drops $\le 6$ HP or hunger drops $\le 4$, sealing into shelter or consuming food.
- **Anti-Stuck Protection**: Detects repetitive actions and pathfinding deadlocks, automatically triggering safe regroups.
- **Durability Monitoring**: Alerts the team and preserves tools with $\le 5$ durability remaining.

### 💾 Persistent SQLite World Memory
- Saves landmark coordinates (`save_current_location`, e.g. base, iron mine, portal).
- Tracks tech tree milestone progress across sessions (`VICTORY_BEATEN_GAME`).
- Persists teammate tasks assigned by the player.

---

## 🛠️ Installation & Setup

### 1. Prerequisites
- **Python**: 3.10 or higher
- **Node.js**: 18.0 or higher
- **Ollama**: Installed and running ([ollama.com](https://ollama.com/))
- **Minecraft**: Java Edition (1.20.x recommended) on LAN, local server, or Paper/Fabric server.

### 2. Pull the AI Model
```bash
ollama pull qwen2.5:3b
# Or for a stronger model if you have 8GB+ VRAM:
# ollama pull qwen2.5:7b
```

### 3. Clone & Install Dependencies
```bash
# Clone the repository
git clone https://github.com/OmerF-CS/MC_Local_AI_Bot.git
cd MC_Local_AI_Bot

# Install Python requirements
pip install -r requirements.txt

# Install Node.js Mineflayer requirements
cd minecraft_bot
npm install
cd ..
```

### 4. Configuration
Copy `.env.example` to `.env` and set your server details:
```bash
cp .env.example .env
```

Edit `.env`:
```env
# Minecraft Server
MINECRAFT_HOST=localhost
MINECRAFT_PORT=25565
MINECRAFT_USERNAME=AIAssistant

# Local AI (Ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b

# Teammate Settings
BOT_NAME=AIAssistant
BOT_OWNER=YourMinecraftUsername
```

### 5. Launch the Bot

**One-Click Launchers (Recommended):**
- **Windows:** Double-click `run.bat` (or run `setup.bat` for first-time automated setup).
- **Linux/macOS:** Run `./run.sh` (or `./setup.sh` for first-time setup).

**Manual Launch:**
```bash
python main.py
```
*(The Python orchestrator automatically spawns and manages the Node.js Mineflayer worker process).*

---

## 💬 In-Game Player Commands

You can talk to the bot normally in chat or use **instant shortcut commands** (0ms latency, bypasses LLM cooldown):

| Command / Trigger | Action |
|---|---|
| `!mine <block> [count]` | Mines specified blocks (e.g. `!mine iron 5` or `!mine log 10`) |
| `!craft <item> [count]` | Recursively crafts an item (e.g. `!craft iron_pickaxe 1` or `!craft shield`) |
| `!smelt <item> [count]` | Smelts ores or cooks meat in a furnace |
| `!hunt [animal]` | Hunts cows, pigs, sheep, or chickens for meat |
| `!portal` | Constructs and ignites a Nether Portal frame with obsidian |
| `!eye` | Throws an Eye of Ender and chats Stronghold coordinates |
| `!end` | Activates nearby End Portal frames with Eyes of Ender |
| `!crystal` | Snipes and demolishes End Crystals atop obsidian pillars |
| `!dragon` | Engages the Ender Dragon in melee perch / bed bombing combat |
| `!win` | Collects victory dragon XP and steps into the exit fountain |
| `!farm` / `!bread` | Harvests hay bales, bakes fresh bread, and harvests ripe crops |
| `!shelter` / `!bunker` | Constructs an emergency bunker with any solid blocks or digs a sealed burrow |
| `!unbunker` | Safely breaks out of shelter when danger passes |
| `!enchant` / `!buyu` | Enchants weapons, armor, or tools with lapis and XP at an enchanting table |
| `!outpost` / `!nether_outpost` | Builds a blast-resistant cobblestone fort around the Nether portal |
| `!bridge [distance]` | Crouch-bridges safely across chasms, lava, or End void without falling |
| `!follow` / `!come` | Follows the owner |
| `!guard` | Defends the owner against hostile mobs |
| `!status` | Reports current HP, hunger, coordinates, and inventory |
| `!tasks` / `!queue` | Lists active task and pending SQLite queue length |
| `!clear` | Cancels all active and queued tasks |
| `!gpu` | Displays RTX 3060 VRAM, GPU utilization, and model acceleration |
| `!stop` | Immediately interrupts all actions and clears task queue |
| `beat the game` | Activates autonomous speedrun progression mode |

---

## 🎯 Fine-Tuning with Unsloth (Phases 5 & 6)

The bot learns directly from its gameplay experience. Every in-game action, state delta, and milestone is logged to `data/minecraft_decisions.jsonl`.

### 1. View Decision Logs
Inspect real-time AI decisions, progress checks, and errors in an interactive Markdown table:
```bash
python show_decisions.py --limit 15
```

### 2. Export & Curate SFT Dataset
Cleans real game decisions, deduplicates loops, teacher-corrects edge cases, and synthesizes complete golden speedrun milestones (350+ clean samples in ChatML format):
```bash
python export_sft_dataset.py --min-samples 350
```
This produces `data/sft_train.jsonl` and `data/sft_val.jsonl`.

### 3. Fine-Tune with Unsloth QLoRA
Fine-tune **Qwen 2.5 3B Instruct** with 4-bit QLoRA optimized specifically for **RTX 3060 6 GB VRAM** (~3.4 GB peak VRAM):
```bash
python train_unsloth_lora.py --epochs 3 --batch-size 1 --grad-accum 4
```
*Alternatively, open and run `train_colab.ipynb` in Google Colab (Free T4 GPU) to train in 3–5 minutes with zero local VRAM usage.*

### 4. Register & Serve with Ollama
The script automatically exports the fine-tuned model to 4-bit GGUF (`q4_k_m`) and builds `models/Modelfile`:
```bash
# Register with Ollama
ollama create mc-qwen:3b -f models/Modelfile

# Update .env to use the fine-tuned model
OLLAMA_MODEL=mc-qwen:3b
```


---

## 🗺️ Tech Tree Progression Eras

The bot autonomously progresses through 8 survival eras:

```
[WOOD]         Gather logs -> Craft wooden pickaxe
  │
[STONE]        Mine stone/deepslate -> Craft stone pickaxe
  │
[FURNACE]      Mine cobblestone -> Craft furnace
  │
[IRON_GEAR]    Mine iron ore -> Smelt ingots -> Craft iron pickaxe & shield
  │
[DIAMOND]      Descend to Y: -58 -> Mine diamonds -> Craft diamond pickaxe
  │
[NETHER]       Gather obsidian (10) -> Build Nether portal -> Hunt Blazes (6+ rods)
  │
[EYE_OF_ENDER] Craft blaze powder -> Combine with ender pearls -> Craft 12 Eyes
  │
[THE_END]      Track Stronghold -> Activate End Portal -> Slay Ender Dragon
```

Track detailed implementation status in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).

---

## 🤝 Contributing

Contributions, suggestions, and pull requests are very welcome!  
If you find a bug or have an idea for new tactics:
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
