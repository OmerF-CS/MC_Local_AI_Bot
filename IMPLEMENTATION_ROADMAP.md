# 🎯 MC Local AI Bot - Complete Implementation Roadmap

## 📊 Overall Progress: ~90% → Target 100%

### Project Scope
**Goal:** Build a Minecraft co-op AI bot that can autonomously progress through vanilla survival and reach the End.

**Current State:**
- ✅ Python orchestrator skeleton & signal handling
- ✅ Ollama LLM integration (Qwen 2.5 3B with connection pooling)
- ✅ WebSocket bridge with action lifecycle confirmation & error reporting
- ✅ Basic logger & config
- ✅ Mineflayer autonomous worker (full mining, recursive crafting, smelting, hunting, combat, navigation)
- ✅ Real game progression logic & SQLite database persistence
- ✅ Instant player shortcut commands (`!mine`, `!craft`, `!portal`, `!eye`, `!end`, etc.) & emergency cooldown bypass
- ✅ Autonomous Nether & End progression engine (portal construction, blaze hunting, eye of ender tracking, end portal activation)
- ✅ Dimension safety (exploding bed prevention in Nether & End)
- 🟡 End fight dragon tactics & production deployment (Phase 4)

---

## 🟢 PHASE 2: Core Action Implementation
**Status:** ✅ COMPLETE

### Task P2.1: Node.js Bot Worker - Real Action Handlers
**File:** `minecraft_bot/bot.js`  
**Status:** ✅ COMPLETE

#### P2.1.1: Mining & Block Collection System
- [x] Implement `collect_block(block_name, count)`
  - Find nearest block of type (supports tag variants: wood, stone, iron ore, coal, diamond)
  - Walk to block (within 48m, explores outward if not visible)
  - Mine with appropriate tool (pickaxe, axe, shovel via `toolLearner`)
  - Handle block drops via `collectNearbyDrops`
  - Return real success/fail status to Python
- [x] Add tool requirement checker
  - Stone requires wooden pickaxe+
  - Iron ore requires stone pickaxe+
  - Diamond requires iron pickaxe+
  - Log requires axe for speed
  - Low durability warning (≤ 5 uses)
- [x] Implement block drop collection
  - Move to drops
  - Pick up items

**Acceptance Criteria:**
- `collect_block("oak_log", 5)` successfully collects 5 oak logs
- Bot uses appropriate tool
- Tool durability decreases with warning
- Failure handling if bot dies/stuck

---

#### P2.1.2: Crafting System
- [x] Implement `craft_item(item_name, count)` 
  - Detect nearby crafting tables or craft/place one
  - Use inventory crafting (4-slot grid) for basic items
  - Use crafting table for 3x3 recipes via `smartCraft`
  - Handle output to inventory
  - Return status to Python
- [x] Recipe database
  - wooden_pickaxe (wood)
  - stone_pickaxe (wood + stone)
  - iron_pickaxe (wood + iron ingot)
  - diamond_pickaxe (wood + diamond)
  - crafting_table (wood)
  - furnace (stone)
  - chest (wood)
  - bed (wood + wool)
  - iron_sword (iron ingot + stick)
  - shield (iron ingot + wood)
  - Recursive ingredient resolution

**Acceptance Criteria:**
- `craft_item("wooden_pickaxe", 1)` creates wooden pickaxe
- `craft_item("crafting_table", 2)` creates 2 crafting tables
- Returns error if insufficient materials
- Places output in inventory correctly

---

#### P2.1.3: Smelting & Furnace System
- [x] Implement `smelt_item(input_item, count, fuel_type = "coal")`
  - Find/place furnace via `smartSmelt`
  - Add input items to top slot
  - Add fuel to fuel slot (coal, charcoal, wood planks)
  - Wait for smelting
  - Collect output & retrieve placed furnace
  - Return status to Python
- [x] Fuel management
  - Coal / charcoal (default)
  - Wood / planks
  - Handle fuel shortage
- [x] Input handling
  - raw_iron → iron_ingot
  - raw_copper → copper_ingot
  - raw_gold → gold_ingot
  - raw_beef → cooked_beef
  - raw_porkchop → cooked_porkchop
  - raw_chicken → cooked_chicken

**Acceptance Criteria:**
- `smelt_item("raw_iron", 10)` produces 10 iron ingots
- Fuel is consumed correctly
- Failure if fuel unavailable
- Timeout after 30s

---

#### P2.1.4: Food & Hunger Management
- [x] Implement `hunt_food(animal_type = "any", count = 1)`
  - Find nearest animal (cow, pig, sheep, chicken within 48m)
  - Walk to animal / pathfinder
  - Attack until death
  - Collect drops
  - Return count harvested to Python
- [x] Implement `eat_food()` 
  - Find first edible item in inventory
  - Equip and consume
  - Check food level before/after
  - Auto-eat loop every 6s and in-combat when HP ≤ 10
- [x] Food prioritization
  - Prefer cooked meat > raw meat > bread > apples
  - Keep minimum food reserve (14/20)

**Acceptance Criteria:**
- `hunt_food()` kills nearest animal and collects drops
- `eat_food()` restores hunger to acceptable level
- Food level reported to Python correctly
- Emergency reflex in Python planner if food ≤ 4

---

#### P2.1.5: Movement & Navigation
- [x] Implement `go_to_coordinates(x, y, z, radius = 1)`
  - Use pathfinder goal system
  - Handle obstacles with anti-stuck detection
  - Timeout after 5 mins
  - Return success/fail
- [x] Implement `follow_player(player_name)`
  - Maintain 2-4 block distance
  - Avoid collision
  - Adjust for terrain
- [x] Movement helpers
  - Jump when needed
  - Climb ladders
  - Handle water
  - Avoid fall damage

**Acceptance Criteria:**
- `go_to_coordinates(100, 64, 100)` navigates there
- `follow_player("Omer")` stays 2-4 blocks away
- Both handle terrain correctly
- Python receives distance/success updates

---

#### P2.1.6: Combat & Defense
- [x] Implement `guard_player(player_name)`
  - Stay near player (2-4 blocks)
  - Detect nearby hostiles (32m radius)
  - Attack automatically if within range
  - Prioritize attacking player's attackers
- [x] Implement `attack_target(target_name)`
  - Find mob by name
  - Move within attack range (3 blocks)
  - Attack with equipped weapon
  - Return success/fail
- [x] Combat mechanics
  - Equip best sword from inventory
  - Auto-equip shield to off-hand
  - Emergency eating during combat if HP ≤ 10
  - Creeper avoidance reflex (step back)

**Acceptance Criteria:**
- `guard_player("Omer")` protects from mobs
- `attack_target("zombie")` kills nearest zombie
- Weapon/armor equipped appropriately
- Combat reported to Python

---

#### P2.1.7: Sleep & Night Management
- [x] Implement `sleep_in_bed()`
  - Find nearest bed (within 16m)
  - Walk to bed
  - Click bed (interact)
  - Fast-forward night to day
  - Return success/fail
- [x] Night mode handling
  - Skip night if beds available
  - Stay guarded during night if no bed
  - Mobs stop spawning at dawn

**Acceptance Criteria:**
- `sleep_in_bed()` advances night to day
- Returns error if no bed nearby
- Time correctly advanced to morning

---

#### P2.1.8: WebSocket Message Handling & State Sync
- [x] Message routing
  - State updates every 2 seconds (heartbeat)
  - Chat messages trigger Python handler
  - Action commands from Python → bot execution
  - Real error/exception reporting back to Python (`action_completed` with `success: bool`, `error: str`)
- [x] State snapshot completeness
  - Health/food/position
  - Inventory items
  - Nearby mobs/players
  - Biome/time/light level
  - Bot busy status
  - Current task name
- [x] Error recovery
  - Reconnect on disconnect (3s auto-retry)
  - State synchronization
  - `send_action_and_wait` for synchronized commands

**Acceptance Criteria:**
- Python receives state every 2s reliably
- All actions complete or report failure
- No state desync for >30s
- Graceful recovery from network hiccup

---

### Task P2.2: Python Chat Handler & Tool Dispatcher
**File:** `core/chat_handler.py`  
**Status:** ✅ COMPLETE

#### P2.2.1: Tool Execution Bridge
- [x] `_execute_tool(tool_name, args, state, owner)` - Complete implementation
  - Validate tool exists
  - Validate args schema (required args, sanitization, integer bounds)
  - Send command to bot via bridge
  - Wait for completion / dispatch
  - Return result dictionary to caller
- [x] Tool schema validation
  - Check required args present (`item_name`, `block_name`, `input_item`, etc.)
  - Type checking (string, float, int)
  - Default values
  - Enum validation
- [x] Result handling
  - Success → return result
  - Failure → log + return error
  - Memory location tools: `save_current_location`, `go_to_saved_location`, `list_saved_locations`

**Acceptance Criteria:**
- `execute_tool("craft_item", {"item_name": "wooden_pickaxe"}, ...)` works
- Schema validation prevents bad calls
- LLM receives tool result in response

---

#### P2.2.2: Player Command Parsing
- [x] Parse player chat messages
  - Direct shortcut commands: `!mine`, `!craft`, `!smelt`, `!hunt`, `!follow`, `!guard`, `!sleep`, `!stop`, `!status` (0ms latency, bypasses LLM cooldown)
  - Natural language: "mine some coal" → LLM + tool
  - Task assignment: "follow me" → planner update & SQLite persistence
  - Info requests: `lookup_recipe`, `explain_component`
- [x] Command interpreter
  - `!mine <block> <count>`
  - `!craft <item> [count]`
  - `!hunt [animal_type]`
  - `!follow [player_name]`
  - `!guard [player_name]`
  - `!status` → report state
  - `!sleep`
  - `!come` → follow owner
  - `!stop` → interrupt current action & clear tasks

**Acceptance Criteria:**
- `!mine oak_log 10` successfully mines 10 oak logs
- `follow me` is understood and executed
- Bot responds with status updates
- Owner can interrupt bot mid-task

---

### Task P2.3: Ollama Brain - Stability & Recovery
**File:** `ai/ollama_client.py`  
**Status:** ✅ COMPLETE

#### P2.3.1: Timeout & Retry Logic
- [x] Add timeout handling
  - LLM call timeout = 20s
  - Fallback to planner if timeout
  - Session connection pooling (`aiohttp.ClientSession`)
  - Latency tracking & rolling average
- [x] Ollama health monitoring
  - Health check at startup
  - Switch to fallback if unhealthy
  - Log warnings if model missing
- [x] Model loading
  - Fallback emergency actions if LLM is slow or offline
  - No bot freezing or deadlock

**Acceptance Criteria:**
- If Ollama unavailable, bot uses fallback (emergency + gather resources)
- No freezing or deadlock
- Health checks logged
- Recovery within 60s

---

#### P2.3.2: Tool Calling Reliability
- [x] Ensure robust tool call per response
  - If model returns 0 tools, planner provides fallback
  - If model returns tools, parsed cleanly
- [x] Tool call parsing
  - Handle both function and direct tool_calls format
  - JSON string argument parsing and object unwrapping
  - Value normalization
- [x] Prompt Optimization
  - English prompt engineering with milestones and inventory awareness
  - Temperature 0.2, top_p 0.8 for Qwen 2.5 3B consistency

**Acceptance Criteria:**
- Every decision cycle resolves to an action
- Parser handles Ollama format variations
- No tool call errors due to parsing

---

## 🟢 PHASE 3: Autonomous Progression Logic
**Dependency:** Phase 2 complete  
**Status:** ✅ COMPLETE

### Task P3.1: Tech Tree & Goal Planner
**Files:** `ai/progression_tree.py`, `ai/recipes.py`, `ai/tools.py`  
**Status:** ✅ COMPLETE

#### P3.1.1: Minecraft Progression Tech Tree
Define clear goal sequence:

```
1. Gather wood (5-10 logs) → crafting_table + wooden_pickaxe
2. Mine stone (20-30) → stone_pickaxe + furnace
3. Mine coal (10+) → fuel for furnace
4. Mine iron (20+) → smelt to ingots → iron_pickaxe
5. Mine diamonds (3-5) → craft diamond pickaxe
6. Mine obsidian (10+) → build nether portal
7. Enter Nether
8. Find fortress + blaze rods
9. Craft blaze powder + ender pearls → ender eyes
10. Locate stronghold + end portal
11. Collect end crystals + attack dragon
```

- [x] Create `TechTree` & tag-aware material engine (`ai/progression_tree.py`)
  - Universal wood, stone, fuel tag resolution
  - Goals list with dependencies: WOOD → STONE → FURNACE → IRON_GEAR → DIAMOND → NETHER → EYE_OF_ENDER → THE_END
  - Current goal tracking via `get_current_progression_goal()`
  - Progression milestone database saves (`db.save_progression`)
- [x] Goal status detector
  - Evaluates inventory dynamically
  - Checks tools, resources, and missing components
  - Detects era milestones
- [x] Next goal advisor
  - Recommends next milestone and unlocks optimal path
  - English recipes database in `ai/recipes.py` (flint_and_steel, blaze_powder, eye_of_ender)
  - Tool calling schemas registered in `ai/tools.py` (`build_nether_portal`, `throw_eye_of_ender`, `activate_end_portal`)

**Acceptance Criteria:**
- `get_current_progression_goal(inventory)` returns active goal + hint
- Evaluates materials with universal tag equivalents
- Progression saved to SQLite database
- Phase 3 recipes and tools fully registered

---

#### P3.1.2: Resource Gathering Planner & Autonomous Portals
**Files:** `minecraft_bot/bot.js`, `ai/planner.py`  
**Status:** ✅ COMPLETE

- [x] Gather wood, stone, iron, diamonds
  - Universal log/stone/ore matching across vanilla variations
  - Tool requirement verification before harvesting
- [x] Nether Portal Construction (`build_nether_portal`)
  - Validates 10+ obsidian and flint_and_steel
  - Builds vertical 4x5 obsidian frame with scaffold
  - Clears interior air space and ignites bottom face with flint_and_steel
  - Enters Nether dimension
- [x] Eye of Ender & Stronghold Tracking (`throw_eye_of_ender`)
  - Crafts blaze powder and eyes of ender
  - Throws Eye of Ender, detects entity trajectory and reports angle + coordinates
- [x] End Portal Activation (`activate_end_portal`)
  - Scans for 12 end_portal_frame blocks
  - Identifies empty sockets, inserts eyes of ender, activates End Portal
- [x] Dimension Safety
  - Reports dimension in state (`bot.game.dimension`)
  - Disables sleeping in Nether and End (prevents bed explosions!)

**Acceptance Criteria:**
- `build_nether_portal` constructs and ignites functional portal
- `throw_eye_of_ender` tracks Stronghold path
- `activate_end_portal` inserts eyes and opens End gateway
- Bot never sleeps with beds in Nether or End

---

### Task P3.2: Planner State Machine Enhancement
**File:** `ai/planner.py`, `core/chat_handler.py`  
**Status:** ✅ COMPLETE

#### P3.2.1: Structured Decision Making
- [x] Decision priority hierarchy:
  1. Evaluate emergency state (health <= 6? starvation <= 4? hostiles nearby?)
  2. Dimension safety: Guard player in Nether/End rather than attempting sleep
  3. Check tech tree progression milestone (`get_current_progression_goal`)
  4. Missing materials resolution and action selection
  5. Fallback behavior for all eras (including Nether, Eye of Ender, and The End)
  6. Player shortcuts (`!portal`, `!eye`, `!end`, `!mine`, `!craft`)
- [x] Infinite loop breaking (repeats >= 3 triggers regroup)
- [x] Database persistence for tasks and progression checkpoints

**Acceptance Criteria:**
- Planner makes decisions consistently across all 8 progression eras
- Dimension safety prevents Nether explosions
- Instant shortcut commands for portal and eye throwing
- SQLite database logs progression milestones and tasks

---

## 🟢 PHASE 4: Polish & Deployment
**Dependency:** Phase 2-3 complete  
**Status:** 🔴 NOT STARTED

### Task P4.1: Logging & Monitoring
**File:** `utils/logger.py` + NEW monitoring  
**Status:** 🟡 PARTIAL

#### P4.1.1: Structured Logging
- [ ] Enhance logger with levels
  - DEBUG: every decision, state update
  - INFO: major actions, goals, tasks
  - WARNING: failures, retries, stuck detection
  - ERROR: exceptions, crashes
  - CRITICAL: unrecoverable failures
- [ ] Add log context
  - Session ID
  - Player name
  - Current goal
  - Action name
  - Timestamp + duration
- [ ] Log file rotation
  - Daily rotation + compression
  - Keep 7 days of logs
  - Archive old logs

**Acceptance Criteria:**
- All major events logged with context
- Can replay bot actions from logs
- Log files don't grow unbounded
- Errors easy to find and diagnose

---

#### P4.1.2: Metrics & Telemetry
- [ ] Create `metrics.py`
  - Decision latency (avg/p95)
  - Action success rate
  - Tool call success rate
  - LLM response time
  - Ollama health uptime
  - Mineflayer connection uptime
  - Mobs defeated
  - Resources gathered
  - Distance traveled
  - Deaths
- [ ] Export to file/database
  - JSON format
  - Periodic flush (every hour)
  - Compute trends (daily, weekly)

**Acceptance Criteria:**
- Can see bot performance metrics
- Identify bottlenecks (LLM vs actions)
- Track progress over time
- Debug poor performance

---

### Task P4.2: Configuration & Deployment
**File:** `.env.example`, `deploy.sh`, Docker (optional)  
**Status:** 🟡 PARTIAL

#### P4.2.1: Advanced Configuration
- [ ] Create `config.py` v2
  - Mode selection (debug / production / speedrun)
  - Goal override (end dragon only / peaceful farming)
  - Difficulty settings
  - Ollama model selection
  - Minecraft server profile
  - Logging verbosity
- [ ] Validation
  - Check all required env vars
  - Validate server reachability
  - Check Ollama available
  - Verify Node.js + dependencies
  - Report issues clearly
- [ ] Config profiles
  - `development.env`
  - `production.env`
  - `speedrun.env` (aggressive mining, skip base-building)
  - `peaceful.env` (no combat, gathering focus)

**Acceptance Criteria:**
- Missing config clearly identified
- User gets setup instructions
- Can switch profiles easily
- All components verified before start

---

#### P4.2.2: Installation & Setup Scripts
- [ ] Create `setup.sh`
  - Clone repo
  - Check Python 3.10+
  - Check Node.js 16+
  - Install Python deps (pip install -r requirements.txt)
  - Install Node deps (cd minecraft_bot && npm install)
  - Download Ollama model if needed
  - Test Minecraft server connection
  - Generate .env from template
  - Run health checks
- [ ] Create `run.sh`
  - Start Ollama (if not running)
  - Start bot (python main.py)
  - Monitor for crashes
  - Auto-restart on failure (max 3x)
  - Graceful shutdown on signal

**Acceptance Criteria:**
- New user can run `./setup.sh` + `./run.sh` and bot works
- No manual npm install / env setup needed
- Errors caught early
- Clear feedback to user

---

### Task P4.3: Testing & Quality Assurance
**File:** `tests/` (NEW)  
**Status:** 🔴 NEW

#### P4.3.1: Unit Tests
- [ ] Test Ollama client
  - Mock responses
  - Tool parsing
  - Timeout handling
  - Health checks
- [ ] Test planner logic
  - Emergency action detection
  - Goal advancement
  - Task queueing
- [ ] Test bridge message parsing
  - Chat messages
  - State updates
  - Action commands

- [ ] Run tests
  - `pytest tests/ --cov`
  - Coverage target: 70%+
  - Run before commits

**Acceptance Criteria:**
- Core logic covered by unit tests
- Tests run quickly (<5s)
- CI/CD integration possible

---

#### P4.3.2: Integration Tests
- [ ] Test end-to-end scenarios
  - Bot spawn → gather wood → craft pickaxe
  - Player command → tool execution
  - Day/night cycle → sleep
  - Combat scenario → guard player
- [ ] Test error recovery
  - Disconnect bot → reconnect
  - Kill Ollama → fallback mode
  - Player dies → respawn
  - Stuck mining → retry location

**Acceptance Criteria:**
- Major workflows tested
- Failure scenarios handled
- Can run full scenario in <5 minutes

---

### Task P4.4: Documentation
**File:** `README.md`, `ARCHITECTURE.md`, `DEVELOPER.md` (NEW)  
**Status:** 🟡 PARTIAL

#### P4.4.1: User Documentation
- [ ] Complete README with:
  - Features list
  - Quick start (setup.sh + run.sh)
  - Configuration guide
  - Command reference (!)
  - Troubleshooting guide
  - FAQ
- [ ] Create `QUICK_START.md`
  - 5-minute setup walkthrough
  - Common first issues + fixes
  - "Is it working?" checklist
- [ ] Create `COMMANDS.md`
  - All ! commands listed
  - Examples
  - Expected output

**Acceptance Criteria:**
- New user can follow README and get running
- All commands documented
- Troubleshooting covers 80% of issues

---

#### P4.4.2: Developer Documentation
- [ ] Create `ARCHITECTURE.md`
  - System diagram
  - Component responsibilities
  - Data flow
  - Key classes/functions
- [ ] Create `DEVELOPER.md`
  - How to add new tool
  - How to add new goal
  - How to modify LLM behavior
  - Testing instructions
  - Code style guide
- [ ] Inline code comments
  - Complex logic explained
  - Decision rationale
  - Edge cases noted

**Acceptance Criteria:**
- Developer can understand system in 30 minutes
- Adding new tool takes <1 hour
- Code style consistent

---

## 📋 Implementation Order (Recommended)

```
Week 1: PHASE 2.1 - Core Actions
  - P2.1.1: Mining
  - P2.1.2: Crafting
  - P2.1.3: Smelting
  - P2.1.4: Food
  - P2.1.5: Movement
  Test each action individually

Week 2: PHASE 2.2-2.3 - Chat + Brain
  - P2.2: Chat handler + tool dispatcher
  - P2.3: Ollama stability
  - Comprehensive testing
  - Full integration test

Week 3: PHASE 3.1 - Progression
  - P3.1.1: Tech tree
  - P3.1.2: Resource planning
  - P3.1.3: Base building
  - Test progression cycle

Week 4: PHASE 3.2-3.3 - Planner
  - P3.2: Planner state machine
  - P3.2: Multi-tasking
  - P3.2: Adaptive behavior
  - Full autonomous testing

Week 5: PHASE 4 - Polish
  - P4.1: Logging
  - P4.2: Config/deploy
  - P4.3: Testing
  - P4.4: Documentation
  
Week 6: Final testing + bug fixes + speedrun optimization
```

---

## ✅ Success Criteria (Project Complete)

- [ ] Bot spawns reliably
- [ ] Bot gathers wood without player help
- [ ] Bot crafts pickaxe
- [ ] Bot mines stone, coal, iron
- [ ] Bot smelts ore into ingots
- [ ] Bot manages hunger (hunts/eats)
- [ ] Bot builds base with bed
- [ ] Bot sleeps through night
- [ ] Player can command bot (! commands)
- [ ] Bot defends from mobs
- [ ] Bot mines diamonds (y<20)
- [ ] Bot crafts diamond pickaxe
- [ ] Bot collects obsidian
- [ ] Bot builds nether portal
- [ ] Bot enters nether (optional: full end completion)
- [ ] Zero unhandled exceptions (graceful recovery)
- [ ] Logs are clean + searchable
- [ ] Setup script works on Linux/Mac/Windows
- [ ] Documentation is complete
- [ ] Code coverage >70%

---

## 📞 Quick Reference: Tool Implementation Checklist

For each tool, ensure:
- [ ] Node.js handler exists
- [ ] Python tool dispatcher exists
- [ ] Tool schema in ai/tools.py
- [ ] Timeout handling
- [ ] Error messages clear
- [ ] State updated correctly
- [ ] Test case written
- [ ] Documented in COMMANDS.md

---

## 🚨 High-Risk Areas (Pay Attention!)

1. **Mineflayer stability** - Can hang if bot gets stuck
2. **Ollama latency** - Decisions delayed if LLM slow
3. **State sync** - Python/Node desync causes confusion
4. **Pathfinding** - Can get trapped in terrain
5. **Tool schema** - Mismatches cause tool call failures
6. **Night mechanics** - Mobs spawn, needs careful handling
7. **Inventory management** - Can drop important items
8. **Database persistence** - Crashes lose progress
9. **Multiplayer** - Other players can interfere
10. **Resource deadlock** - Waiting for smelting forever

---

**Last Updated:** 2026-10-03  
**Next Review:** After Phase 2 complete
