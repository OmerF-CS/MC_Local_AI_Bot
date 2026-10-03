# 🎮 MC Local AI Bot

> **Autonomous Human-Like Minecraft Co-op Companion Powered 100% Locally by Ollama & Mineflayer**

[![Status: Production Ready](https://img.shields.io/badge/status-active%20release%20(v0.4.0)-brightgreen.svg)](IMPLEMENTATION_ROADMAP.md)
[![Progress: 100%](https://img.shields.io/badge/progress-100%25%20(Phase%204%20Complete)-brightgreen.svg)](IMPLEMENTATION_ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Node.js: 18+](https://img.shields.io/badge/node.js-18%2B-green.svg)](https://nodejs.org/)
[![LLM: Ollama](https://img.shields.io/badge/LLM-Ollama%20(Qwen%202.5)-purple.svg)](https://ollama.com/)

---

> [!NOTE]
> ### 🏆 Project Status: Feature-Complete (v0.4.0)
> **MC Local AI Bot has completed all core roadmap phases!**  
> - **Phases 1-3:** Autonomous survival, mining, recursive crafting, smelting, dimension safety, Nether portal construction, Blaze hunting, Stronghold tracking, and End Portal activation.
> - **Phase 4:** End Crystal demolition, Ender Dragon perch combat & bed bombing, victory XP harvesting, exit fountain completion, and one-click launch scripts (`run.bat` / `run.sh`).
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

### 🛡️ Dimension Safety & Health Reflexes
- **Exploding Bed Prevention**: Strictly forbids bed sleeping in `the_nether` and `the_end`, preventing catastrophic explosions.
- **Emergency Reflexes**: Bypasses LLM cooldown instantly when health drops $\le 6$ HP or hunger drops $\le 4$.
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
| `!follow` / `!come` | Follows the owner |
| `!guard` | Defends the owner against hostile mobs |
| `!status` | Reports current HP, hunger, coordinates, and inventory |
| `!stop` | Immediately interrupts all actions and clears task queue |
| `beat the game` | Activates autonomous speedrun progression mode |

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
