/**
 * Mineflayer Bot Worker & Python Bridge
 * Autonomous Co-op Teammate, Anti-Stuck Loop Guard, and Crafting Engine
 */
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const collectBlock = require('mineflayer-collectblock').plugin;
const pvp = require('mineflayer-pvp').plugin;
const toolPlugin = require('mineflayer-tool').plugin;
const WebSocket = require('ws');
const Vec3 = require('vec3');
const toolLearner = require('./tool_learner');

// Configuration
const MC_HOST = process.env.MINECRAFT_HOST || 'localhost';
const MC_PORT = parseInt(process.env.MINECRAFT_PORT || '25565', 10);
const MC_USERNAME = process.env.MINECRAFT_USERNAME || 'AIAssistant';
const MC_VERSION = process.env.MINECRAFT_VERSION || false;
const BRIDGE_URL = process.env.BRIDGE_URL || 'ws://127.0.0.1:8765';

let ws = null;
let bot = null;
let defaultMovements = null;

// Autonomous State Management
let isGuarding = false;
let guardedPlayerName = null;
let isEating = false;
let isBusy = false; // Is bot currently busy with an action (prevents collision)
let currentActionName = 'idle';

// Anti-Stuck Tracking Variables
let lastPosition = null;
let stuckCounter = 0;

// Known Food Items List
const FOOD_NAMES = [
    'cooked_beef', 'cooked_porkchop', 'bread', 'apple', 'golden_apple',
    'cooked_chicken', 'baked_potato', 'cooked_mutton', 'carrot',
    'cooked_cod', 'cooked_salmon', 'melon_slice'
];

// --- WEBSOCKET BRIDGE CONNECTION ---
function connectBridge() {
    console.log(`[Bridge] Connecting to Python bridge at: ${BRIDGE_URL}`);
    ws = new WebSocket(BRIDGE_URL);

    ws.on('open', () => {
        console.log('[Bridge] ✅ Connected to Python bridge successfully.');
        sendToPython({
            type: 'bot_status',
            status: 'connected',
            username: MC_USERNAME
        });
    });

    ws.on('message', async (data) => {
        try {
            const message = JSON.parse(data.toString());
            console.log('[Bridge] 📥 Python Command Received:', message);
            await handleAction(message);
        } catch (err) {
            console.error('[Bridge] ❌ Message handling error:', err.message);
        }
    });

    ws.on('close', () => {
        console.log('[Bridge] ⚠️ Bridge connection lost. Reconnecting in 3s...');
        setTimeout(connectBridge, 3000);
    });

    ws.on('error', (err) => {
        console.error('[Bridge] ❌ Socket error:', err.message);
    });
}

function sendToPython(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(payload));
    }
}

// --- ADVANCED 3D SPATIAL PERCEPTION & VISION ENGINE ---
function getBotState() {
    if (!bot || !bot.entity) return {};

    const inventoryItems = bot.inventory.items().map(i => ({ name: i.name, count: i.count }));
    const inventorySummary = inventoryItems.map(i => `${i.name} x${i.count}`).join(', ') || 'Empty';
    const nearbyPlayers = Object.keys(bot.players).filter(p => p !== bot.username);

    // 1. Spatial & Environmental Metrics (Light, Altitude, Zone)
    const currentBlock = bot.blockAt(bot.entity.position);
    const lightLevel = currentBlock ? currentBlock.light : 15;
    const currentY = Math.round(bot.entity.position.y);
    const altitudeZone = currentY < 0 ? 'Deepslate Core (Y < 0)' : currentY < 62 ? 'Underground Caves' : 'Surface / Overworld';

    // 2. Visible & Air-Exposed Resource Scanning (Expanded to 64-block radius)
    const visibleResources = {};
    const keyCategories = [
        'crafting_table', 'furnace', 'chest', 'bed',
        'oak_log', 'birch_log', 'spruce_log', 'dark_oak_log', 'acacia_log', 'jungle_log', 'cherry_log',
        'stone', 'cobblestone', 'deepslate', 'coal_ore', 'iron_ore', 'copper_ore', 'gold_ore', 'redstone_ore', 'lapis_ore', 'diamond_ore',
        'water', 'lava'
    ];

    try {
        const mcData = require('minecraft-data')(bot.version);
        for (const bName of keyCategories) {
            const bType = mcData.blocksByName[bName];
            if (bType) {
                // Search up to 64 blocks radius
                const found = bot.findBlocks({
                    matching: bType.id,
                    maxDistance: 64,
                    count: 6
                });

                if (found.length > 0) {
                    // Check if at least one is exposed to air (visible line-of-sight)
                    let exposedCount = 0;
                    let closestDist = 999;
                    for (const pos of found) {
                        const dist = Math.round(bot.entity.position.distanceTo(pos));
                        if (dist < closestDist) closestDist = dist;

                        const b = bot.blockAt(pos);
                        if (b) {
                            // Check neighboring air
                            const neighbors = [
                                bot.blockAt(pos.offset(0, 1, 0)),
                                bot.blockAt(pos.offset(0, -1, 0)),
                                bot.blockAt(pos.offset(1, 0, 0)),
                                bot.blockAt(pos.offset(-1, 0, 0)),
                                bot.blockAt(pos.offset(0, 0, 1)),
                                bot.blockAt(pos.offset(0, 0, -1))
                            ];
                            if (neighbors.some(n => n && (n.name === 'air' || n.name === 'cave_air'))) {
                                exposedCount++;
                            }
                        }
                    }
                    visibleResources[bName] = {
                        total_found: found.length,
                        visible_exposed: exposedCount,
                        closest_distance: closestDist
                    };
                }
            }
        }
    } catch (_) {}

    // 3. Multi-Category Entity & Threat Radar (32m Radius)
    const hostiles = [];
    const passives = [];
    const droppedItems = [];
    const playersNearby = [];

    const HOSTILE_KEYWORDS = [
        'zombie', 'skeleton', 'spider', 'creeper', 'drowned', 'witch', 'enderman',
        'phantom', 'slime', 'magma_cube', 'husk', 'stray', 'silverfish', 'cave_spider',
        'pillager', 'ravager', 'vindicator', 'evoker', 'vex', 'blaze', 'ghast',
        'wither', 'warden', 'hoglin', 'piglin'
    ];
    const PASSIVE_KEYWORDS = [
        'cow', 'sheep', 'pig', 'chicken', 'horse', 'donkey', 'mule', 'llama',
        'cat', 'wolf', 'villager', 'iron_golem', 'snow_golem', 'rabbit', 'fox',
        'bee', 'bat', 'squid', 'glow_squid', 'dolphin', 'turtle', 'panda', 'allay'
    ];

    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (!e || !e.position || e === bot.entity) continue;
        const dist = Math.round(e.position.distanceTo(bot.entity.position));

        // Players (excluding self)
        if (e.type === 'player' && e.username && e.username !== bot.username) {
            if (dist <= 48) {
                const held = e.heldItem ? e.heldItem.name : 'empty hand';
                playersNearby.push(`${e.username} (${dist}m, holding ${held})`);
            }
            continue;
        }

        // Dropped items on ground (within 16m)
        if (e.name === 'item' && dist <= 16) {
            const rawItem = e.metadata ? (e.metadata[8]?.name || 'dropped item') : 'dropped item';
            droppedItems.push(`${rawItem} (${dist}m away)`);
            continue;
        }

        if (dist <= 32 && e.name) {
            const raw = e.name.toLowerCase();
            if (HOSTILE_KEYWORDS.some(h => raw.includes(h))) {
                hostiles.push(`${e.name} (${dist}m away)`);
            } else if (PASSIVE_KEYWORDS.some(p => raw.includes(p))) {
                passives.push(`${e.name} (${dist}m away)`);
            }
        }
    }

    const summaryParts = [];
    if (hostiles.length > 0) summaryParts.push(`Hostiles: ${hostiles.slice(0, 6).join(', ')}`);
    if (passives.length > 0) summaryParts.push(`Animals/Passives: ${passives.slice(0, 6).join(', ')}`);
    if (droppedItems.length > 0) summaryParts.push(`Dropped Loot: ${droppedItems.slice(0, 5).join(', ')}`);
    if (playersNearby.length > 0) summaryParts.push(`Nearby Players: ${playersNearby.join(', ')}`);
    const nearbyEntitiesSummary = summaryParts.length > 0 ? summaryParts.join(' | ') : 'No entities within 32m radar';

    // 4. Partner / Owner Tracking
    let ownerObservation = null;
    const ownerName = process.env.BOT_OWNER || 'Omer';
    const ownerEntity = bot.players[ownerName]?.entity;
    if (ownerEntity) {
        const distToOwner = Math.round(ownerEntity.position.distanceTo(bot.entity.position));
        const heldItem = ownerEntity.heldItem ? ownerEntity.heldItem.name : 'Empty hand';
        ownerObservation = {
            name: ownerName,
            distance: distToOwner,
            held_item: heldItem,
            is_visible: distToOwner <= 64,
            position: {
                x: Math.round(ownerEntity.position.x * 10) / 10,
                y: Math.round(ownerEntity.position.y * 10) / 10,
                z: Math.round(ownerEntity.position.z * 10) / 10
            }
        };
    }

    let dimension = 'overworld';
    if (bot.game && bot.game.dimension) {
        const rawDim = String(bot.game.dimension).toLowerCase();
        if (rawDim.includes('nether')) dimension = 'the_nether';
        else if (rawDim.includes('end')) dimension = 'the_end';
        else dimension = 'overworld';
    }

    return {
        health: bot.health || 20,
        food: bot.food || 20,
        position: {
            x: Math.round(bot.entity.position.x * 10) / 10,
            y: Math.round(bot.entity.position.y * 10) / 10,
            z: Math.round(bot.entity.position.z * 10) / 10
        },
        dimension: dimension,
        inventory_items: inventoryItems,
        inventory_summary: inventorySummary,
        nearby_players: nearbyPlayers,
        visible_resources: visibleResources,
        nearby_hostiles: hostiles,
        nearby_passives: passives,
        dropped_items: droppedItems,
        nearby_entities_summary: nearbyEntitiesSummary,
        carried_tools: toolLearner.getCarriedToolsSummary(bot),
        vision_metrics: {
            render_radius: 64,
            light_level: lightLevel,
            altitude_zone: altitudeZone
        },
        is_guarding: isGuarding,
        is_busy: isBusy,
        current_action: currentActionName,
        is_day: bot.time ? bot.time.isDay : true,
        biome: bot.blockAt(bot.entity.position)?.biome?.name || 'unknown',
        owner_info: ownerObservation
    };
}

// --- INFINITE LOOP & STUCK PREVENTION (ANTI-STUCK GUARD) ---
function antiStuckCheck() {
    if (!bot || !bot.entity) return;

    const currentPos = bot.entity.position;
    if (lastPosition && bot.pathfinder && bot.pathfinder.isMoving()) {
        const distMoved = currentPos.distanceTo(lastPosition);
        if (distMoved < 0.5) {
            stuckCounter++;
            if (stuckCounter >= 3) { // Stuck in same spot for ~9s
                console.log('🚨 [Anti-Stuck] Bot stuck on obstacle! Resetting goal and performing unstuck jump...');
                bot.pathfinder.stop();
                bot.setControlState('jump', true);
                setTimeout(() => bot.setControlState('jump', false), 500);

                isBusy = false;
                currentActionName = 'idle';
                stuckCounter = 0;

                sendToPython({
                    type: 'action_completed',
                    command: 'stuck_recovery',
                    success: false,
                    reason: 'Obstacle obstruction detected; goal reset.'
                });
            }
        } else {
            stuckCounter = 0;
        }
    } else {
        stuckCounter = 0;
    }
    lastPosition = currentPos.clone();
}

// --- AUTONOMOUS SURVIVAL SYSTEMS ---
async function autoEatCheck() {
    if (!bot || !bot.entity || isEating || isBusy) return;

    if (bot.food < 16 || (bot.health < 20 && bot.food < 20)) {
        const foodItem = bot.inventory.items().find(i => FOOD_NAMES.includes(i.name));
        if (foodItem) {
            try {
                isEating = true;
                console.log(`[AutoEat] 🍞 Low hunger (${bot.food}/20). Consuming ${foodItem.name}...`);
                await bot.equip(foodItem, 'hand');
                await bot.consume();
                console.log(`[AutoEat] ✅ Replenished! New hunger: ${bot.food}/20`);
            } catch (err) {
                console.log(`[AutoEat] Error consuming food: ${err.message}`);
            } finally {
                isEating = false;
            }
        }
    }
}

function guardLoop() {
    if (!isGuarding || !bot || !bot.entity || !guardedPlayerName || isBusy) return;

    const player = bot.players[guardedPlayerName]?.entity;
    if (!player) return;

    const hostileMob = bot.nearestEntity(e => {
        if (!e || !e.name) return false;
        const name = e.name.toLowerCase();
        const isHostile = ['zombie', 'skeleton', 'spider', 'creeper', 'drowned', 'husk'].some(m => name.includes(m));
        if (!isHostile) return false;

        const distToPlayer = e.position.distanceTo(player.position);
        const distToBot = e.position.distanceTo(bot.entity.position);
        return distToPlayer < 12 || distToBot < 10;
    });

    if (hostileMob && bot.pvp) {
        const sword = bot.inventory.items().find(i => i.name.includes('sword') || i.name.includes('axe'));
        if (sword) bot.equip(sword, 'hand').catch(() => {});
        bot.pvp.attack(hostileMob);
    } else {
        const dist = bot.entity.position.distanceTo(player.position);
        if (dist > 4 && (!bot.pathfinder.isMoving() || bot.pathfinder.goal == null)) {
            const { GoalFollow } = goals;
            bot.pathfinder.setGoal(new GoalFollow(player, 2), true);
        }
    }
}

// --- AUTO-EQUIP ARMOR & OFFHAND SHIELD ---
async function autoEquipGearCheck() {
    if (!bot || !bot.entity || isBusy) return;

    const destinations = [
        { dest: 'head', keywords: ['helmet', 'cap'] },
        { dest: 'torso', keywords: ['chestplate', 'tunic'] },
        { dest: 'legs', keywords: ['leggings', 'pants'] },
        { dest: 'feet', keywords: ['boots'] },
        { dest: 'off-hand', keywords: ['shield', 'totem'] }
    ];

    const armorSlotIndices = {
        head: 5,
        torso: 6,
        legs: 7,
        feet: 8,
        'off-hand': 45
    };

    const items = bot.inventory.items();
    for (const d of destinations) {
        const item = items.find(i => d.keywords.some(k => i.name.toLowerCase().includes(k)));
        if (item) {
            const slotIndex = armorSlotIndices[d.dest];
            const currentItem = bot.inventory.slots[slotIndex];
            if (!currentItem) {
                try {
                    await bot.equip(item, d.dest);
                    console.log(`🛡️ [AutoGear] Equipped ${item.name} into ${d.dest}!`);
                } catch (_) {}
            }
        }
    }
}

// --- AUTO-TORCH LIGHTING IN DARK CAVES ---
async function autoTorchCheck() {
    if (!bot || !bot.entity || isBusy) return;
    const currentBlock = bot.blockAt(bot.entity.position);
    if (!currentBlock || currentBlock.light >= 6) return;

    const torch = bot.inventory.items().find(i => i.name === 'torch');
    if (!torch) return;

    const loc = findPlacementLocation(bot);
    if (loc) {
        try {
            await bot.equip(torch, 'hand');
            await bot.placeBlock(loc.referenceBlock, loc.faceVector);
            console.log("🔦 [AutoTorch] Lit up dark cave area!");
        } catch (_) {}
    }
}

// --- AUTO-SELF DEFENSE AGAINST SURROUNDING HOSTILE MOBS ---
async function autoSelfDefenseCheck() {
    if (!bot || !bot.entity || isBusy) return;

    // Detect hostile mobs dangerously close (< 6 blocks)
    const dangerMob = bot.nearestEntity(e => {
        if (!e || !e.name || !e.position) return false;
        const name = e.name.toLowerCase();
        const isHostile = ['zombie', 'skeleton', 'spider', 'creeper', 'drowned', 'husk', 'cave_spider', 'witch'].some(m => name.includes(m));
        if (!isHostile) return false;
        return e.position.distanceTo(bot.entity.position) < 6;
    });

    if (dangerMob) {
        const mobName = dangerMob.name.toLowerCase();
        const dist = dangerMob.position.distanceTo(bot.entity.position);

        // Emergency heal/eat during combat if health drops below 10 HP
        if (bot.health <= 10 && !isEating) {
            const food = bot.inventory.items().find(i => FOOD_NAMES.includes(i.name));
            if (food) {
                try {
                    await bot.equip(food, 'hand');
                    await bot.consume();
                } catch (_) {}
            }
        }

        // Creeper defense: back off immediately to avoid explosion!
        if (mobName.includes('creeper') && dist < 4) {
            bot.setControlState('back', true);
            setTimeout(() => bot.setControlState('back', false), 800);
            return;
        }

        // Off-hand shield auto-equip
        const shield = bot.inventory.items().find(i => i.name.includes('shield'));
        if (shield && (!bot.inventory.slots[45] || !bot.inventory.slots[45].name.includes('shield'))) {
            try { await bot.equip(shield, 'off-hand'); } catch (_) {}
        }

        // Equip best weapon
        const weapon = bot.inventory.items().find(i => i.name.includes('sword') || i.name.includes('axe'));
        if (weapon) await bot.equip(weapon, 'hand').catch(() => {});

        // Attack or raise shield
        if (bot.pvp) {
            bot.pvp.attack(dangerMob);
        } else {
            await bot.lookAt(dangerMob.position.offset(0, dangerMob.height, 0));
            bot.attack(dangerMob);
        }
    }
}

// --- BOT CREATION & LIFECYCLE EVENTS ---
function createBot() {
    console.log(`[Minecraft] Connecting to ${MC_HOST}:${MC_PORT} as '${MC_USERNAME}'...`);
    
    const botOptions = {
        host: MC_HOST,
        port: MC_PORT,
        username: MC_USERNAME
    };
    if (MC_VERSION) {
        botOptions.version = MC_VERSION;
    }

    bot = mineflayer.createBot(botOptions);

    bot.loadPlugin(pathfinder);
    bot.loadPlugin(toolPlugin);
    bot.loadPlugin(collectBlock);
    bot.loadPlugin(pvp);

    bot.once('spawn', () => {
        console.log('[Minecraft] 🌟 Bot successfully spawned into the world!');
        const mcData = require('minecraft-data')(bot.version);
        defaultMovements = new Movements(bot, mcData);
        bot.pathfinder.setMovements(defaultMovements);

        // Periodic maintenance loops
        setInterval(autoEatCheck, 6000);
        setInterval(guardLoop, 1500);
        setInterval(autoSelfDefenseCheck, 1500); // Proactive close-range threat defense
        setInterval(antiStuckCheck, 3000); // Anti-stuck watchdog every 3s
        setInterval(autoEquipGearCheck, 4000); // Armor & shield auto-equip every 4s
        setInterval(autoTorchCheck, 8000); // Dark cave auto-torching

        // Live 2-second state synchronization heartbeat
        setInterval(() => {
            if (bot && bot.entity) {
                sendToPython({
                    type: 'state_update',
                    state: getBotState()
                });
            }
        }, 2000);

        sendToPython({
            type: 'bot_spawned',
            state: getBotState()
        });
    });

    bot.on('chat', (username, message) => {
        if (username === bot.username) return;
        console.log(`[Minecraft Chat] <${username}> ${message}`);

        sendToPython({
            type: 'chat_message',
            sender: username,
            message: message,
            state: getBotState()
        });
    });

    bot.on('death', () => {
        console.log('[Minecraft] 💀 Bot died!');
        isGuarding = false;
        isBusy = false;
        currentActionName = 'idle';
        sendToPython({
            type: 'bot_death',
            state: getBotState()
        });
    });

    bot.on('kicked', (reason) => {
        console.log('[Minecraft] 🚫 Kicked from server:', reason);
    });

    bot.on('error', (err) => {
        console.error('[Minecraft] ❌ Error:', err.message);
    });

    bot.on('end', () => {
        console.log('[Minecraft] 🔄 Connection closed. Reconnecting in 5 seconds...');
        setTimeout(createBot, 5000);
    });
}

// --- SMART RECURSIVE CRAFTING & SMELTING SYSTEM ---

function normalizeCraftItemName(rawName, bot) {
    let name = (rawName || '').toLowerCase().trim();
    if (['plank', 'planks', 'wooden_planks'].includes(name)) {
        if (bot && bot.inventory) {
            const logItem = bot.inventory.items().find(i => i.name.endsWith('_log') || i.name.endsWith('_stem') || i.name.endsWith('_wood'));
            if (logItem) {
                return logItem.name.replace(/(_log|_stem|_wood)/, '_planks');
            }
            const existingPlank = bot.inventory.items().find(i => i.name.endsWith('_planks'));
            if (existingPlank) return existingPlank.name;
        }
        return 'oak_planks';
    }
    if (['workbench', 'table'].includes(name)) return 'crafting_table';

    // Auto-detect best tier if generic tool name was given
    if (bot && bot.inventory) {
        const invNames = bot.inventory.items().map(i => i.name);
        if (name === 'pickaxe' || name === 'pickaxes') {
            if (invNames.some(i => i.includes('diamond'))) return 'diamond_pickaxe';
            if (invNames.some(i => i.includes('iron_ingot'))) return 'iron_pickaxe';
            if (invNames.some(i => i.includes('cobble') || i.includes('deepslate') || i.includes('blackstone'))) return 'stone_pickaxe';
            return 'wooden_pickaxe';
        }
        if (name === 'axe' || name === 'axes') {
            if (invNames.some(i => i.includes('diamond'))) return 'diamond_axe';
            if (invNames.some(i => i.includes('iron_ingot'))) return 'iron_axe';
            if (invNames.some(i => i.includes('cobble') || i.includes('deepslate') || i.includes('blackstone'))) return 'stone_axe';
            return 'wooden_axe';
        }
        if (name === 'sword' || name === 'swords') {
            if (invNames.some(i => i.includes('diamond'))) return 'diamond_sword';
            if (invNames.some(i => i.includes('iron_ingot'))) return 'iron_sword';
            if (invNames.some(i => i.includes('cobble') || i.includes('deepslate') || i.includes('blackstone'))) return 'stone_sword';
            return 'wooden_sword';
        }
    }

    try {
        const mcData = require('minecraft-data')(bot.version);
        if (mcData.itemsByName[name] || mcData.blocksByName[name]) return name;

        if (name.endsWith('es')) {
            const sing2 = name.slice(0, -2);
            if (mcData.itemsByName[sing2] || mcData.blocksByName[sing2]) return sing2;
            const sing1 = name.slice(0, -1);
            if (mcData.itemsByName[sing1] || mcData.blocksByName[sing1]) return sing1;
        }
        if (name.endsWith('s') && !name.endsWith('planks')) {
            const sing = name.slice(0, -1);
            if (mcData.itemsByName[sing] || mcData.blocksByName[sing]) return sing;
        }
    } catch (_) {}

    return name;
}

function findPlacementLocation(bot) {
    const botPos = bot.entity.position;
    for (let dy of [-1, 0]) {
        for (let dx of [1, -1, 0, 2, -2]) {
            for (let dz of [1, -1, 0, 2, -2]) {
                if (dx === 0 && dz === 0) continue;
                const groundPos = botPos.floored().offset(dx, dy, dz);
                const ground = bot.blockAt(groundPos);
                if (!ground || ground.name === 'air' || ground.name === 'cave_air' || ground.name === 'water' || ground.name === 'lava') {
                    continue;
                }
                const placePos = groundPos.offset(0, 1, 0);
                const airBlock = bot.blockAt(placePos);
                if (airBlock && (airBlock.name === 'air' || airBlock.name === 'cave_air')) {
                    const dist = botPos.distanceTo(placePos);
                    if (dist >= 1.2 && dist <= 3.8) {
                        return { referenceBlock: ground, faceVector: new Vec3(0, 1, 0), placedPos: placePos };
                    }
                }
            }
        }
    }
    return null;
}

async function ensurePlanks(bot, neededPlankCount) {
    const mcData = require('minecraft-data')(bot.version);
    let availablePlanks = bot.inventory.items().filter(i => i.name.endsWith('_planks')).reduce((s, i) => s + i.count, 0);
    if (availablePlanks >= neededPlankCount) return true;

    const deficit = neededPlankCount - availablePlanks;
    const craftsNeeded = Math.ceil(deficit / 4);

    const logItem = bot.inventory.items().find(i => i.name.endsWith('_log') || i.name.endsWith('_stem') || i.name.endsWith('_wood'));
    if (!logItem) return false;

    const plankName = logItem.name.replace(/(_log|_stem|_wood)/, '_planks');
    const plankDef = mcData.itemsByName[plankName];
    if (!plankDef) return false;

    const recipes = bot.recipesFor(plankDef.id, null, 1, null);
    if (recipes.length === 0) return false;

    bot.chat(`Crafting ${craftsNeeded * 4}x ${plankName} from logs...`);
    await bot.craft(recipes[0], craftsNeeded, null);
    return true;
}

async function ensureSticks(bot, neededStickCount) {
    const mcData = require('minecraft-data')(bot.version);
    let availableSticks = bot.inventory.items().filter(i => i.name === 'stick').reduce((s, i) => s + i.count, 0);
    if (availableSticks >= neededStickCount) return true;

    const deficit = neededStickCount - availableSticks;
    const stickCraftsNeeded = Math.ceil(deficit / 4);
    const planksNeeded = stickCraftsNeeded * 2;

    await ensurePlanks(bot, planksNeeded);
    const plankCount = bot.inventory.items().filter(i => i.name.endsWith('_planks')).reduce((s, i) => s + i.count, 0);
    if (plankCount < 2) return false;

    const stickDef = mcData.itemsByName['stick'];
    const recipes = bot.recipesFor(stickDef.id, null, 1, null);
    if (recipes.length === 0) return false;

    bot.chat(`Crafting ${stickCraftsNeeded * 4}x sticks...`);
    await bot.craft(recipes[0], stickCraftsNeeded, null);
    return true;
}

async function retrieveBlock(bot, block) {
    if (!block) return;
    try {
        await toolLearner.prepareAndEquipToolForBlock(bot, block.name, null);
        const pos = block.position.clone();
        await bot.dig(block);
        await bot.waitForTicks(10);
        await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, 0.5)).catch(() => {});
    } catch (err) {
        console.warn(`[Cleanup] Error retrieving block: ${err.message}`);
    }
}

async function ensureCraftingTableInWorld(bot) {
    const mcData = require('minecraft-data')(bot.version);
    const tableBlockId = mcData.blocksByName.crafting_table.id;

    // 1. Existing table right next to bot (< 4m)
    let tableBlock = bot.findBlock({ matching: tableBlockId, maxDistance: 4 });
    if (tableBlock) return { tableBlock, placedByMe: false };

    // 2. Existing table within 16m
    const distantTable = bot.findBlock({ matching: tableBlockId, maxDistance: 16 });
    if (distantTable) {
        try {
            await bot.pathfinder.goto(new goals.GoalNear(distantTable.position.x, distantTable.position.y, distantTable.position.z, 2));
            return { tableBlock: distantTable, placedByMe: false };
        } catch (_) {}
    }

    // 3. Need to place one. Check if in inventory
    let tableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
    if (!tableItem) {
        await ensurePlanks(bot, 4);
        const totalPlanks = bot.inventory.items().filter(i => i.name.endsWith('_planks')).reduce((s, i) => s + i.count, 0);
        if (totalPlanks < 4) {
            bot.chat("Need 4 wood planks to craft a crafting table.");
            return { tableBlock: null, placedByMe: false };
        }

        const tableDef = mcData.itemsByName['crafting_table'];
        const recipes = bot.recipesFor(tableDef.id, null, 1, null);
        if (recipes.length === 0) {
            bot.chat("Could not find recipe for crafting table.");
            return { tableBlock: null, placedByMe: false };
        }

        bot.chat("Crafting a crafting table...");
        await bot.craft(recipes[0], 1, null);
        tableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
    }

    if (!tableItem) return { tableBlock: null, placedByMe: false };

    const loc = findPlacementLocation(bot);
    if (!loc) {
        bot.chat("Cannot find a clear space to place crafting table.");
        return { tableBlock: null, placedByMe: false };
    }

    bot.chat("Placing crafting table...");
    await bot.equip(tableItem, 'hand');
    await bot.placeBlock(loc.referenceBlock, loc.faceVector);
    tableBlock = bot.blockAt(loc.placedPos);
    return { tableBlock, placedByMe: true };
}

async function smartCraft(bot, rawItemName, count = 1) {
    const mcData = require('minecraft-data')(bot.version);
    const Recipe = require('prismarine-recipe')(bot.registry).Recipe;

    const itemName = normalizeCraftItemName(rawItemName, bot);
    const itemDef = mcData.itemsByName[itemName] || mcData.blocksByName[itemName];
    if (!itemDef) {
        bot.chat(`Unknown item to craft: '${rawItemName}'.`);
        return false;
    }

    bot.chat(`Preparing to craft ${count}x ${itemName}...`);

    const allRecipes = Recipe.find(itemDef.id);
    if (!allRecipes || allRecipes.length === 0) {
        bot.chat(`No recipe registered for ${itemName}.`);
        return false;
    }

    const requiresTable = allRecipes.some(r => r.requiresTable);
    let tableBlock = null;
    let placedByMe = false;

    // Step 1: If table required, ensure table is placed in world FIRST
    if (requiresTable) {
        const res = await ensureCraftingTableInWorld(bot);
        tableBlock = res.tableBlock;
        placedByMe = res.placedByMe;
        if (!tableBlock) {
            bot.chat(`Cannot craft ${itemName}: requires crafting table.`);
            return false;
        }
    }

    // Step 2: Ensure sticks if needed
    if (itemName.includes('pickaxe') || itemName.includes('axe') || itemName.includes('shovel') || itemName.includes('hoe')) {
        await ensureSticks(bot, 2 * count);
    } else if (itemName.includes('sword')) {
        await ensureSticks(bot, 1 * count);
    } else if (itemName === 'torch') {
        await ensureSticks(bot, Math.ceil(count / 4));
    }

    // Step 3: Ensure planks if needed
    if (itemName.startsWith('wooden_')) {
        if (itemName.includes('pickaxe') || itemName.includes('axe')) {
            await ensurePlanks(bot, 3 * count);
        } else if (itemName.includes('sword')) {
            await ensurePlanks(bot, 2 * count);
        } else if (itemName.includes('shovel')) {
            await ensurePlanks(bot, 1 * count);
        }
    } else if (itemName === 'shield') {
        await ensurePlanks(bot, 6 * count);
    } else if (itemName === 'crafting_table') {
        await ensurePlanks(bot, 4 * count);
    }

    // Step 4: Find matching recipe with available inventory
    const recipes = bot.recipesFor(itemDef.id, null, count, tableBlock);
    if (recipes.length === 0) {
        bot.chat(`Missing materials to craft ${itemName}.`);
        if (placedByMe && tableBlock) {
            await retrieveBlock(bot, tableBlock);
        }
        return false;
    }

    const recipe = recipes[0];
    await bot.craft(recipe, count, tableBlock);
    bot.chat(`Successfully crafted ${count}x ${itemName}! ✨`);

    // Step 5: Clean-up placed table
    if (placedByMe && tableBlock) {
        await retrieveBlock(bot, tableBlock);
    }

    return true;
}

async function smartSmelt(bot, inputItemName, count = 1) {
    const mcData = require('minecraft-data')(bot.version);
    const rawName = (inputItemName || '').toLowerCase().trim();

    const inputItem = bot.inventory.items().find(i => i.name.toLowerCase().includes(rawName));
    if (!inputItem) {
        bot.chat(`I don't have '${rawName}' in my inventory to smelt.`);
        return false;
    }

    const fuelItem = bot.inventory.items().find(i => 
        i.name === 'coal' || 
        i.name === 'charcoal' || 
        i.name.endsWith('_planks') || 
        i.name.endsWith('_log') ||
        i.name === 'stick'
    );
    if (!fuelItem) {
        bot.chat("No fuel available (coal, charcoal, or wood) to smelt with.");
        return false;
    }

    let furnaceBlock = bot.findBlock({ matching: mcData.blocksByName.furnace.id, maxDistance: 4 });
    if (!furnaceBlock) {
        const distantFurnace = bot.findBlock({ matching: mcData.blocksByName.furnace.id, maxDistance: 16 });
        if (distantFurnace) {
            try {
                await bot.pathfinder.goto(new goals.GoalNear(distantFurnace.position.x, distantFurnace.position.y, distantFurnace.position.z, 2));
                furnaceBlock = distantFurnace;
            } catch (_) {}
        }
    }

    let placedFurnaceByMe = false;
    if (!furnaceBlock) {
        let furnaceItem = bot.inventory.items().find(i => i.name === 'furnace');
        if (!furnaceItem) {
            const cobbleCount = bot.inventory.items().filter(i => 
                ['cobblestone', 'cobbled_deepslate', 'blackstone'].includes(i.name)
            ).reduce((s, i) => s + i.count, 0);

            if (cobbleCount >= 8) {
                bot.chat("Crafting a furnace first...");
                const crafted = await smartCraft(bot, 'furnace', 1);
                if (crafted) {
                    furnaceItem = bot.inventory.items().find(i => i.name === 'furnace');
                }
            }
        }

        if (!furnaceItem) {
            bot.chat("No furnace available and not enough stone to craft one.");
            return false;
        }

        const loc = findPlacementLocation(bot);
        if (!loc) {
            bot.chat("No suitable spot to place the furnace.");
            return false;
        }

        bot.chat("Placing furnace on the ground...");
        await bot.equip(furnaceItem, 'hand');
        await bot.placeBlock(loc.referenceBlock, loc.faceVector);
        furnaceBlock = bot.blockAt(loc.placedPos);
        placedFurnaceByMe = true;
    }

    if (!furnaceBlock) return false;

    bot.chat(`Opening furnace to smelt ${count}x ${inputItem.name}...`);
    const furnace = await bot.openFurnace(furnaceBlock);
    try {
        await furnace.putFuel(fuelItem.type, null, Math.min(fuelItem.count, 2));
        await furnace.putInput(inputItem.type, null, count);

        bot.chat(`Smelting in progress... waiting for output.`);
        const start = Date.now();
        while (Date.now() - start < 30000) {
            await bot.waitForTicks(20);
            const out = furnace.outputItem();
            if (out && out.count >= 1) {
                await furnace.takeOutput();
                bot.chat(`Smelting finished! Collected ${out.name}. 🔥`);
                break;
            }
            if (!furnace.inputItem()) break;
        }
    } finally {
        furnace.close();
    }

    if (placedFurnaceByMe && furnaceBlock) {
        await retrieveBlock(bot, furnaceBlock);
    }

    return true;
}

// --- LOOT COLLECTION SYSTEM ---
async function collectNearbyDrops(bot, maxDistance = 12) {
    if (!bot || !bot.entity) return;
    const drops = [];
    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (e && e.name === 'item' && e.position) {
            const dist = bot.entity.position.distanceTo(e.position);
            if (dist <= maxDistance) {
                drops.push(e);
            }
        }
    }
    for (const drop of drops) {
        if (!drop || !drop.isValid) continue;
        try {
            const { GoalNear } = goals;
            await bot.pathfinder.goto(new GoalNear(drop.position.x, drop.position.y, drop.position.z, 1));
            await new Promise(r => setTimeout(r, 250));
        } catch (_) {}
    }
}

// --- PHASE 3: NETHER & END PROGRESSION HELPERS ---

async function placeBlockDirect(bot, item, targetPos) {
    if (!item) return false;
    const currentBlock = bot.blockAt(targetPos);
    if (currentBlock && currentBlock.name !== 'air' && currentBlock.name !== 'cave_air' && currentBlock.name !== 'water' && currentBlock.name !== 'lava') {
        return true;
    }

    const directions = [
        new Vec3(0, -1, 0),
        new Vec3(0, 1, 0),
        new Vec3(-1, 0, 0),
        new Vec3(1, 0, 0),
        new Vec3(0, 0, -1),
        new Vec3(0, 0, 1)
    ];

    let refBlock = null;
    let faceVector = null;

    for (const dir of directions) {
        const neighborPos = targetPos.minus(dir);
        const neighbor = bot.blockAt(neighborPos);
        if (neighbor && neighbor.name !== 'air' && neighbor.name !== 'cave_air' && neighbor.name !== 'water' && neighbor.name !== 'lava') {
            refBlock = neighbor;
            faceVector = dir;
            break;
        }
    }

    if (!refBlock) return false;

    const dist = bot.entity.position.distanceTo(targetPos);
    if (dist > 3.8) {
        const { GoalNear } = goals;
        await bot.pathfinder.goto(new GoalNear(targetPos.x, targetPos.y, targetPos.z, 2.5)).catch(() => {});
    }

    await bot.equip(item, 'hand');
    await bot.placeBlock(refBlock, faceVector);
    await new Promise(r => setTimeout(r, 250));
    return true;
}

async function buildNetherPortal(bot) {
    const mcData = require('minecraft-data')(bot.version);
    const portalBlockId = mcData.blocksByName['nether_portal']?.id;
    if (portalBlockId) {
        const existing = bot.findBlock({ matching: portalBlockId, maxDistance: 32 });
        if (existing) {
            bot.chat("Active Nether Portal located nearby! Stepping through... 🌀");
            const { GoalNear } = goals;
            await bot.pathfinder.goto(new GoalNear(existing.position.x, existing.position.y, existing.position.z, 0.5));
            return true;
        }
    }

    const totalObsidian = bot.inventory.items().filter(i => i.name === 'obsidian').reduce((s, i) => s + i.count, 0);
    if (totalObsidian < 10) {
        bot.chat(`Need at least 10 Obsidian to build a Nether Portal (have ${totalObsidian}). 🪨`);
        return false;
    }

    const flintItem = bot.inventory.items().find(i => i.name === 'flint_and_steel');
    if (!flintItem) {
        bot.chat("Flint and Steel is required to ignite the Nether Portal! 🔥");
        return false;
    }

    bot.chat("Surveying location to construct Nether Portal frame (4x5 obsidian)... 🏗️");

    const basePos = bot.entity.position.floored().offset(2, 0, 0);
    const fillerItem = bot.inventory.items().find(i => ['dirt', 'cobblestone', 'stone', 'netherrack'].includes(i.name)) || bot.inventory.items().find(i => i.name === 'obsidian');

    for (let dx = 0; dx <= 3; dx++) {
        const groundPos = basePos.offset(dx, -1, 0);
        const ground = bot.blockAt(groundPos);
        if (!ground || ground.name === 'air' || ground.name === 'cave_air' || ground.name === 'water' || ground.name === 'lava') {
            if (fillerItem) {
                await placeBlockDirect(bot, fillerItem, groundPos).catch(() => {});
            }
        }
    }

    for (let dx = 1; dx <= 2; dx++) {
        for (let dy = 1; dy <= 3; dy++) {
            const insidePos = basePos.offset(dx, dy, 0);
            const insideBlock = bot.blockAt(insidePos);
            if (insideBlock && insideBlock.name !== 'air' && insideBlock.name !== 'cave_air') {
                try {
                    await bot.dig(insideBlock);
                } catch (_) {}
            }
        }
    }

    const portalObsidianOffsets = [
        new Vec3(1, 0, 0),
        new Vec3(2, 0, 0),
        new Vec3(0, 1, 0),
        new Vec3(0, 2, 0),
        new Vec3(0, 3, 0),
        new Vec3(3, 1, 0),
        new Vec3(3, 2, 0),
        new Vec3(3, 3, 0),
        new Vec3(1, 4, 0),
        new Vec3(2, 4, 0)
    ];

    const scaffoldPos = basePos.offset(0, 4, 0);
    if (fillerItem) {
        await placeBlockDirect(bot, fillerItem, scaffoldPos).catch(() => {});
    }

    for (const offset of portalObsidianOffsets) {
        const obsItem = bot.inventory.items().find(i => i.name === 'obsidian');
        if (!obsItem) {
            bot.chat("Ran out of obsidian while building frame!");
            return false;
        }
        const targetPos = basePos.plus(offset);
        const currentB = bot.blockAt(targetPos);
        if (currentB && currentB.name === 'obsidian') continue;

        const placed = await placeBlockDirect(bot, obsItem, targetPos);
        if (!placed) {
            console.log(`[NetherPortal] Could not place obsidian at ${targetPos}`);
        }
    }

    bot.chat("Frame complete! Striking flint and steel to ignite Nether Portal... 🔥");
    const readyFlint = bot.inventory.items().find(i => i.name === 'flint_and_steel');
    if (readyFlint) {
        await bot.equip(readyFlint, 'hand');
        const igniteBase = bot.blockAt(basePos.offset(1, 0, 0));
        if (igniteBase) {
            try {
                await bot.activateBlock(igniteBase, new Vec3(0, 1, 0));
            } catch (ignErr) {
                console.warn(`[NetherPortal] Ignite error: ${ignErr.message}`);
            }
        }
    }

    await new Promise(r => setTimeout(r, 1200));

    const interiorPos = basePos.offset(1, 1, 0);
    const litPortal = bot.blockAt(interiorPos);
    if (litPortal && (litPortal.name.includes('portal') || litPortal.name === 'fire')) {
        bot.chat("Portal activated! Entering Nether dimension! 🌌");
        const { GoalNear } = goals;
        await bot.pathfinder.goto(new GoalNear(interiorPos.x, interiorPos.y, interiorPos.z, 0.5)).catch(() => {});
        return true;
    }

    bot.chat("Nether Portal frame built! Standing by to ignite or enter.");
    return true;
}

async function handleThrowEyeOfEnder(bot) {
    const eyeItem = bot.inventory.items().find(i => i.name === 'eye_of_ender');
    if (!eyeItem) {
        bot.chat("I don't have an Eye of Ender in inventory to throw! 👁️");
        return false;
    }

    bot.chat("Throwing Eye of Ender to scan Stronghold trajectory... 👁️");
    await bot.equip(eyeItem, 'hand');
    await bot.look(bot.entity.yaw, 0.6, true);
    bot.activateItem();

    let foundSignal = null;
    const startCheck = Date.now();
    while (Date.now() - startCheck < 3000) {
        for (const id in bot.entities) {
            const e = bot.entities[id];
            if (e && (e.name === 'eye_of_ender' || e.name === 'eye_of_ender_signal' || e.entityType === 83)) {
                foundSignal = e;
                break;
            }
        }
        if (foundSignal) break;
        await new Promise(r => setTimeout(r, 200));
    }

    if (foundSignal) {
        const dx = foundSignal.position.x - bot.entity.position.x;
        const dz = foundSignal.position.z - bot.entity.position.z;
        const angleDeg = Math.round(Math.atan2(-dx, -dz) * (180 / Math.PI));
        bot.chat(`Stronghold signal tracked! Heading: ${angleDeg}°, moving towards (${Math.round(foundSignal.position.x)}, ${Math.round(foundSignal.position.z)}). 🧭`);
        return true;
    } else {
        bot.chat("Eye of Ender launched! Advancing towards the Stronghold signal. 🏃");
        return true;
    }
}

async function handleActivateEndPortal(bot) {
    const mcData = require('minecraft-data')(bot.version);
    const frameId = mcData.blocksByName['end_portal_frame']?.id;
    if (!frameId) {
        bot.chat("End Portal Frame definition not found in game data.");
        return false;
    }

    const frameBlocks = bot.findBlocks({ matching: frameId, maxDistance: 16, count: 16 });
    if (frameBlocks.length === 0) {
        bot.chat("No End Portal frames found within 16m radar.");
        return false;
    }

    bot.chat(`Found ${frameBlocks.length} End Portal frames! Checking sockets... 👁️`);

    const eyeItem = bot.inventory.items().find(i => i.name === 'eye_of_ender');
    if (!eyeItem) {
        bot.chat("Need Eye of Ender in inventory to activate End Portal frames!");
        return false;
    }

    let filledCount = 0;
    for (const pos of frameBlocks) {
        const b = bot.blockAt(pos);
        if (!b) continue;

        const hasEye = (b._properties && (b._properties.eye === 'true' || b._properties.eye === true)) ||
                       (b.properties && (b.properties.eye === 'true' || b.properties.eye === true)) ||
                       (b.stateValues && b.stateValues.eye === 1);

        if (!hasEye) {
            try {
                const { GoalNear } = goals;
                await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 2.5));
                const currentEye = bot.inventory.items().find(i => i.name === 'eye_of_ender');
                if (!currentEye) {
                    bot.chat("Ran out of Eyes of Ender while filling frames!");
                    break;
                }
                await bot.equip(currentEye, 'hand');
                await bot.activateBlock(b);
                filledCount++;
                await new Promise(r => setTimeout(r, 400));
            } catch (err) {
                console.warn(`[EndPortal] Failed to place eye on frame: ${err.message}`);
            }
        }
    }

    const portalId = mcData.blocksByName['end_portal']?.id;
    if (portalId) {
        const portal = bot.findBlock({ matching: portalId, maxDistance: 16 });
        if (portal) {
            bot.chat("🌌 The End Portal is fully ACTIVATED! Entering the End dimension to face the Ender Dragon!");
            const { GoalNear } = goals;
            await bot.pathfinder.goto(new GoalNear(portal.position.x, portal.position.y, portal.position.z, 0.5));
            return true;
        }
    }

    bot.chat(`Placed ${filledCount} Eye(s) of Ender in portal frames.`);
    return true;
}

// --- ACTION EXECUTION ENGINE (TIMEOUT & CONCURRENCY GUARDED) ---
async function handleAction(action) {
    if (!bot) return;

    const { command, args } = action;
    let actionSuccess = true;
    let actionError = null;

    // Guard against action overlap if bot is already performing a critical multi-step action
    if (isBusy && command !== 'stop_actions' && command !== 'say_chat') {
        console.log(`⚠️ [Busy Guard] Bot currently busy with '${currentActionName}'. Postponing new action.`);
        return;
    }

    if (['craft_item', 'collect_block', 'hunt_food', 'smelt_item', 'place_block', 'go_to_coordinates', 'build_nether_portal', 'throw_eye_of_ender', 'activate_end_portal'].includes(command)) {
        isBusy = true;
        currentActionName = `${command}_${args.item_name || args.block_name || args.input_item || ''}`;
        sendToPython({
            type: 'action_started',
            command: command,
            state: getBotState()
        });
    }

    try {
        switch (command) {
            case 'say_chat': {
                const text = args.message || '';
                if (text) bot.chat(text);
                break;
            }

            case 'craft_item': {
                isBusy = true;
                currentActionName = `craft_${args.item_name}`;
                const itemName = args.item_name;
                const count = args.count || 1;
                await smartCraft(bot, itemName, count);
                break;
            }

            case 'collect_block': {
                isBusy = true;
                currentActionName = `collect_${args.block_name}`;
                isGuarding = false;
                const rawName = (args.block_name || '').toLowerCase();
                const count = args.count || 1;

                const mcData = require('minecraft-data')(bot.version);
                let matchingIds = [];
                let categoryLabel = rawName;

                // 1. Universal Wood / Log Variants
                if (rawName.includes('log') || rawName.includes('wood') || rawName === 'tree') {
                    categoryLabel = 'wood/trees';
                    const woodNames = [
                        'oak_log', 'birch_log', 'spruce_log', 'acacia_log',
                        'dark_oak_log', 'jungle_log', 'mangrove_log', 'cherry_log',
                        'crimson_stem', 'warped_stem'
                    ];
                    for (const name of woodNames) {
                        if (mcData.blocksByName[name]) matchingIds.push(mcData.blocksByName[name].id);
                    }
                }
                // 2. Universal Stone / Deepslate / Blackstone Variants
                else if (rawName.includes('stone') || rawName.includes('cobble') || rawName.includes('rock') || rawName === 'deepslate') {
                    categoryLabel = 'stone/cobblestone/deepslate';
                    const stoneNames = [
                        'stone', 'cobblestone', 'deepslate', 'cobbled_deepslate',
                        'blackstone', 'andesite', 'diorite', 'granite', 'tuff'
                    ];
                    for (const name of stoneNames) {
                        if (mcData.blocksByName[name]) matchingIds.push(mcData.blocksByName[name].id);
                    }
                }
                // 3. Universal Iron Ore Variants
                else if (rawName.includes('iron')) {
                    categoryLabel = 'iron ore';
                    for (const name of ['iron_ore', 'deepslate_iron_ore']) {
                        if (mcData.blocksByName[name]) matchingIds.push(mcData.blocksByName[name].id);
                    }
                }
                // 4. Universal Coal Ore Variants
                else if (rawName.includes('coal')) {
                    categoryLabel = 'coal ore';
                    for (const name of ['coal_ore', 'deepslate_coal_ore']) {
                        if (mcData.blocksByName[name]) matchingIds.push(mcData.blocksByName[name].id);
                    }
                }
                // 5. Universal Diamond Ore Variants
                else if (rawName.includes('diamond')) {
                    categoryLabel = 'diamond ore';
                    for (const name of ['diamond_ore', 'deepslate_diamond_ore']) {
                        if (mcData.blocksByName[name]) matchingIds.push(mcData.blocksByName[name].id);
                    }
                }
                // 6. Direct Specific Block Match
                else {
                    const blockType = mcData.blocksByName[rawName];
                    if (blockType) matchingIds.push(blockType.id);
                }

                if (matchingIds.length === 0) {
                    bot.chat(`Unknown or unsupported block type: '${rawName}'.`);
                    break;
                }

                bot.chat(`Searching for ${count}x ${categoryLabel}...`);

                const targets = bot.findBlocks({ matching: matchingIds, maxDistance: 48, count: count });

                if (targets.length === 0) {
                    bot.chat(`No ${categoryLabel} found in the immediate area. Exploring outward to discover veins! 🏃`);
                    const angle = Math.random() * Math.PI * 2;
                    const exploreX = Math.round(bot.entity.position.x + Math.cos(angle) * 35);
                    const exploreZ = Math.round(bot.entity.position.z + Math.sin(angle) * 35);
                    const exploreY = Math.round(bot.entity.position.y);
                    const { GoalNear } = goals;
                    bot.pathfinder.setGoal(new GoalNear(exploreX, exploreY, exploreZ, 2));
                    break;
                }

                const blocks = targets.map(p => bot.blockAt(p)).filter(b => b);
                if (blocks.length === 0) break;

                // Tool mastery pre-check and equipping
                const prep = await toolLearner.prepareAndEquipToolForBlock(bot, blocks[0].name, smartCraft);
                if (!prep.canHarvest) {
                    console.log(`[ToolLearner] Aborting mining of '${blocks[0].name}' due to missing tool requirement: ${prep.minToolName}`);
                    break;
                }

                const startTime = Date.now();
                const invBefore = bot.inventory.items().map(i => ({ name: i.name, count: i.count }));

                try {
                    await bot.collectBlock.collect(blocks);
                    const durationMs = Date.now() - startTime;
                    const invAfter = bot.inventory.items().map(i => ({ name: i.name, count: i.count }));

                    // Detect gained drop items
                    const gained = [];
                    for (const a of invAfter) {
                        const bItem = invBefore.find(x => x.name === a.name);
                        const diff = a.count - (bItem ? bItem.count : 0);
                        if (diff > 0) gained.push(`${a.name} x${diff}`);
                    }

                    const lesson = toolLearner.recordExperience(blocks[0].name, prep.toolEquipped, durationMs, true, gained);
                    if (lesson) console.log(`🧠 [Tool Learning] ${lesson}`);
                    bot.chat(`Gathered ${count}x ${categoryLabel}! (Used: ${prep.toolEquipped})`);

                    // Tool durability check
                    const heldTool = bot.heldItem;
                    if (heldTool && heldTool.maxDurability) {
                        const remainingDurability = heldTool.maxDurability - (heldTool.durabilityUsed || 0);
                        if (remainingDurability <= 5) {
                            console.log(`⚠️ [Tool Durability] ${heldTool.name} is low: ${remainingDurability} uses left!`);
                            bot.chat(`Warning: ${heldTool.name} is nearly broken (${remainingDurability} uses left).`);
                        }
                    }
                } catch (cErr) {
                    bot.chat(`Mining interrupted: ${cErr.message}`);
                }
                break;
            }

            case 'follow_player': {
                const targetName = args.player_name;
                const target = bot.players[targetName]?.entity;
                if (!target) {
                    bot.chat(`Cannot see ${targetName} nearby!`);
                    break;
                }
                const { GoalFollow } = goals;
                bot.pathfinder.setGoal(new GoalFollow(target, 2), true);
                break;
            }

            case 'guard_player': {
                const targetName = args.player_name;
                const target = bot.players[targetName]?.entity;
                if (!target) {
                    bot.chat(`${targetName} is not nearby to guard.`);
                    break;
                }
                isGuarding = true;
                guardedPlayerName = targetName;
                bot.chat(`Got your back, ${targetName}! Guarding you 🛡️`);
                break;
            }

            case 'stop_actions': {
                isBusy = false;
                isGuarding = false;
                guardedPlayerName = null;
                currentActionName = 'idle';
                bot.pathfinder.stop();
                if (bot.pvp) bot.pvp.stop();
                bot.chat("Stopped all ongoing actions.");
                break;
            }

            case 'go_to_coordinates': {
                isBusy = true;
                currentActionName = 'walking';
                const { x, y, z } = args;
                const { GoalNear } = goals;
                bot.pathfinder.setGoal(new GoalNear(x, y, z, 1));
                break;
            }

            case 'sleep_in_bed': {
                const curDim = (bot.game && bot.game.dimension) ? String(bot.game.dimension).toLowerCase() : '';
                if (curDim.includes('nether') || curDim.includes('end')) {
                    bot.chat("Cannot sleep in this dimension! Beds explode violently here! 💥");
                    actionSuccess = false;
                    actionError = "Cannot sleep in Nether or End (beds explode)";
                    break;
                }
                const bed = bot.findBlock({ matching: b => b.name.includes('bed'), maxDistance: 16 });
                if (bed) {
                    try {
                        await bot.sleep(bed);
                        bot.chat("Sleeping now, sweet dreams!");
                    } catch (_) {}
                }
                break;
            }

            case 'eat_food': {
                const foodItem = bot.inventory.items().find(i => FOOD_NAMES.includes(i.name));
                if (foodItem) {
                    await bot.equip(foodItem, 'hand');
                    await bot.consume();
                }
                break;
            }

            case 'attack_target': {
                const targetName = (args.target_name || '').toLowerCase();
                const entity = bot.nearestEntity(e => e.name && e.name.toLowerCase().includes(targetName) && e.position.distanceTo(bot.entity.position) < 16);
                if (entity && bot.pvp) {
                    bot.pvp.attack(entity);
                }
                break;
            }

            case 'hunt_food': {
                isBusy = true;
                currentActionName = 'hunting';
                const animalType = (args.animal_type || 'any').toLowerCase().trim();
                const FOOD_ANIMALS = ['cow', 'pig', 'sheep', 'chicken'];

                // Search for animal
                const targetEntity = bot.nearestEntity(e => {
                    if (!e || !e.name || !e.position) return false;
                    const eName = e.name.toLowerCase();
                    if (animalType !== 'any') {
                        return eName.includes(animalType) && e.position.distanceTo(bot.entity.position) < 48;
                    }
                    return FOOD_ANIMALS.some(a => eName.includes(a)) && e.position.distanceTo(bot.entity.position) < 48;
                });

                if (!targetEntity) {
                    bot.chat(`No food animals found nearby. Exploring outward to find animals! 🏃`);
                    const angle = Math.random() * Math.PI * 2;
                    const exploreX = Math.round(bot.entity.position.x + Math.cos(angle) * 35);
                    const exploreZ = Math.round(bot.entity.position.z + Math.sin(angle) * 35);
                    const exploreY = Math.round(bot.entity.position.y);
                    const { GoalNear } = goals;
                    bot.pathfinder.setGoal(new GoalNear(exploreX, exploreY, exploreZ, 2));
                    break;
                }

                const animalName = targetEntity.name;
                bot.chat(`Hunting ${animalName} for food! 🥩`);

                const weapon = bot.inventory.items().find(i => i.name.includes('sword') || i.name.includes('axe'));
                if (weapon) {
                    await bot.equip(weapon, 'hand').catch(() => {});
                }

                try {
                    if (bot.pvp) {
                        bot.pvp.attack(targetEntity);
                        await new Promise((resolve) => {
                            const timeout = setTimeout(() => {
                                if (bot.pvp) bot.pvp.stop();
                                resolve();
                            }, 12000);

                            const checkInterval = setInterval(() => {
                                if (!targetEntity.isValid || targetEntity.health <= 0) {
                                    clearInterval(checkInterval);
                                    clearTimeout(timeout);
                                    if (bot.pvp) bot.pvp.stop();
                                    resolve();
                                }
                            }, 400);
                        });
                    } else {
                        const { GoalNear } = goals;
                        await bot.pathfinder.goto(new GoalNear(targetEntity.position.x, targetEntity.position.y, targetEntity.position.z, 2));
                        await bot.attack(targetEntity);
                    }

                    await new Promise(r => setTimeout(r, 600));
                    await collectNearbyDrops(bot, 12);
                    bot.chat(`Successfully hunted ${animalName} and collected food drops! 🍗`);
                } catch (hErr) {
                    bot.chat(`Hunt interrupted: ${hErr.message}`);
                }
                break;
            }

            case 'give_item_to_player': {
                const playerName = args.player_name;
                const itemName = args.item_name;
                const count = args.count || 1;
                const item = bot.inventory.items().find(i => i.name.includes(itemName));
                const player = bot.players[playerName]?.entity;

                if (item && player) {
                    const { GoalNear } = goals;
                    await bot.pathfinder.goto(new GoalNear(player.position.x, player.position.y, player.position.z, 2));
                    await bot.toss(item.type, null, count);
                }
                break;
            }

            case 'smelt_item': {
                isBusy = true;
                currentActionName = `smelt_${args.input_item}`;
                const inputItem = args.input_item;
                const count = args.count || 1;
                await smartSmelt(bot, inputItem, count);
                break;
            }

            case 'place_block': {
                isBusy = true;
                currentActionName = `place_${args.block_name}`;
                const blockName = (args.block_name || '').toLowerCase().trim();
                const item = bot.inventory.items().find(i => i.name.toLowerCase().includes(blockName));
                if (!item) {
                    bot.chat(`I don't have '${blockName}' in my inventory to place.`);
                    break;
                }
                const loc = findPlacementLocation(bot);
                if (loc) {
                    await bot.equip(item, 'hand');
                    await bot.placeBlock(loc.referenceBlock, loc.faceVector);
                    bot.chat(`Placed ${item.name}!`);
                } else {
                    bot.chat(`Could not find a clear spot to place ${blockName}.`);
                }
                break;
            }

            case 'build_nether_portal': {
                isBusy = true;
                currentActionName = 'building_nether_portal';
                const ok = await buildNetherPortal(bot);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to build or ignite Nether portal";
                }
                break;
            }

            case 'throw_eye_of_ender': {
                isBusy = true;
                currentActionName = 'throwing_eye_of_ender';
                const ok = await handleThrowEyeOfEnder(bot);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to throw Eye of Ender";
                }
                break;
            }

            case 'activate_end_portal': {
                isBusy = true;
                currentActionName = 'activating_end_portal';
                const ok = await handleActivateEndPortal(bot);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to activate End portal";
                }
                break;
            }

            default:
                console.log(`[Bridge] Unknown command received: ${command}`);
                actionSuccess = false;
                actionError = `Unknown command: ${command}`;
        }
    } catch (err) {
        console.error(`[Action Error] ${command}:`, err.message);
        actionSuccess = false;
        actionError = err.message;
    } finally {
        isBusy = false;
        currentActionName = 'idle';
        sendToPython({
            type: 'action_completed',
            command: command,
            success: actionSuccess,
            error: actionError,
            state: getBotState()
        });
    }
}

// Startup & Initialization
connectBridge();
createBot();
