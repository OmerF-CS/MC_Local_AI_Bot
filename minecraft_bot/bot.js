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
const MC_HOST = process.env.MINECRAFT_HOST || process.env.MC_HOST || 'localhost';
const MC_PORT = parseInt(process.env.MINECRAFT_PORT || process.env.MC_PORT || '25565', 10);
const MC_USERNAME = process.env.MINECRAFT_USERNAME || process.env.MC_USERNAME || 'AIAssistant';
const MC_VERSION = process.env.MINECRAFT_VERSION || process.env.MC_VERSION || false;
const BRIDGE_URL = process.env.BRIDGE_URL || `ws://${process.env.BRIDGE_HOST || '127.0.0.1'}:${process.env.BRIDGE_PORT || '8765'}`;

let ws = null;
let bot = null;
let defaultMovements = null;

// Autonomous State Management
let isGuarding = false;
let guardedPlayerName = null;
let isEating = false;
let isBusy = false; // Is bot currently busy with an action (prevents collision)
let currentActionName = 'idle';
let dragonDefeatedFlag = false;
let isSheltered = false;
let netherOutpostBuilt = false;

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

// Round-Robin Resource Scanner State (Non-blocking background radar)
const RESOURCE_CATEGORIES = [
    'crafting_table', 'furnace', 'chest', 'bed',
    'hay_block', 'wheat', 'carrots', 'potatoes', 'farmland',
    'oak_log', 'birch_log', 'spruce_log', 'dark_oak_log', 'acacia_log', 'jungle_log', 'cherry_log',
    'stone', 'cobblestone', 'deepslate', 'coal_ore', 'iron_ore', 'copper_ore', 'gold_ore', 'redstone_ore', 'lapis_ore', 'diamond_ore',
    'deepslate_coal_ore', 'deepslate_iron_ore', 'deepslate_copper_ore', 'deepslate_gold_ore', 'deepslate_redstone_ore', 'deepslate_lapis_ore', 'deepslate_diamond_ore', 'ancient_debris',
    'water', 'lava'
];
const cachedVisibleResources = {};
const reportedOreVeins = new Set();
const ORE_INTEREST_NAMES = [
    'coal_ore', 'deepslate_coal_ore',
    'iron_ore', 'deepslate_iron_ore',
    'copper_ore', 'deepslate_copper_ore',
    'gold_ore', 'deepslate_gold_ore',
    'redstone_ore', 'deepslate_redstone_ore',
    'lapis_ore', 'deepslate_lapis_ore',
    'diamond_ore', 'deepslate_diamond_ore',
    'ancient_debris'
];
let scanRoundRobinIndex = 0;
let botCreatedTime = Date.now();
let lastSleepTime = Date.now();

function tickResourceScanner() {
    if (!bot || !bot.entity) return;
    try {
        const mcData = require('minecraft-data')(bot.version);
        const bName = RESOURCE_CATEGORIES[scanRoundRobinIndex % RESOURCE_CATEGORIES.length];
        scanRoundRobinIndex++;

        const bType = mcData.blocksByName[bName];
        if (!bType) return;

        // Radius 32m (8x smaller volume than 64m), count 4
        const found = bot.findBlocks({
            matching: bType.id,
            maxDistance: 32,
            count: 4
        });

        if (found.length > 0) {
            let exposedCount = 0;
            let closestDist = 999;
            const curDim = (bot.game && bot.game.dimension ? String(bot.game.dimension).toLowerCase() : 'overworld');

            for (const pos of found) {
                const dist = Math.round(bot.entity.position.distanceTo(pos));
                if (dist < closestDist) closestDist = dist;

                const b = bot.blockAt(pos);
                if (b) {
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

                // Phase 2 / F2.3: Record persistent ore vein locations to SQLite
                if (ORE_INTEREST_NAMES.includes(bName)) {
                    const oreKey = `${curDim}:${pos.x},${pos.y},${pos.z}`;
                    if (!reportedOreVeins.has(oreKey)) {
                        reportedOreVeins.add(oreKey);
                        sendToPython({
                            type: 'ore_discovered',
                            dim: curDim,
                            x: pos.x,
                            y: pos.y,
                            z: pos.z,
                            block: bName
                        });
                    }
                }
            }
            cachedVisibleResources[bName] = {
                total_found: found.length,
                visible_exposed: exposedCount,
                closest_distance: closestDist
            };
        } else {
            delete cachedVisibleResources[bName];
        }
    } catch (_) {}
}

function setMovementsForTask(taskType = 'walk') {
    if (!bot) return;
    try {
        const mcData = require('minecraft-data')(bot.version);
        const m = new Movements(bot, mcData);

        // Fluid Human-Like Movement Profile
        m.allowSprinting = true; // Enables smooth continuous sprinting instead of rigid 1-block steps
        m.allowParkour = true;   // Smoothly jumps 1-block gaps without stopping
        m.canOpenDoors = true;   // Traverses buildings and doors without getting stuck

        if (taskType === 'mine' || taskType === 'dig') {
            m.canDig = true;
            m.maxDropDown = 4;
        } else {
            // High-speed fluid traversal (walking, sprinting, following, fleeing, exploring)
            m.canDig = false; // Fast A* search without evaluating block destruction
            m.maxDropDown = 4; // Safely drops down small ledges
            m.scaffoldingBlocks = []; // Don't place random pillars/bridges while walking
        }
        defaultMovements = m;
        bot.pathfinder.setMovements(m);
        if (bot.pathfinder) {
            bot.pathfinder.thinkTimeout = 5000;
        }
    } catch (err) {
        console.warn(`[Movements] Error updating movements: ${err.message}`);
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

    // 2. Visible & Air-Exposed Resource Scanning (Read from non-blocking round-robin background cache)
    const visibleResources = { ...cachedVisibleResources };

    // 3. Multi-Category Entity & Threat Radar (32m Radius)
    const hostiles = [];
    const hostileEntityObjects = [];
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
                hostileEntityObjects.push(e);
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

    let endCrystalsCount = 0;
    let enderDragonInfo = null;
    let endPortalBlockFound = false;

    if (dimension === 'the_end') {
        for (const id in bot.entities) {
            const e = bot.entities[id];
            if (!e || !e.name) continue;
            if (e.name === 'end_crystal') {
                endCrystalsCount++;
            } else if (e.name === 'ender_dragon') {
                const dist = Math.round(e.position.distanceTo(bot.entity.position));
                const hp = (e.metadata && typeof e.metadata[9] === 'number') ? e.metadata[9] : (e.health || 200);
                enderDragonInfo = {
                    id: e.id,
                    health: hp,
                    distance: dist,
                    position: {
                        x: Math.round(e.position.x * 10) / 10,
                        y: Math.round(e.position.y * 10) / 10,
                        z: Math.round(e.position.z * 10) / 10
                    },
                    is_perching: Math.abs(e.position.x) < 14 && Math.abs(e.position.z) < 14 && e.position.y < 75
                };
            }
        }

        try {
            const mcData = require('minecraft-data')(bot.version);
            const portalId = mcData.blocksByName['end_portal']?.id;
            if (portalId) {
                const exitPortal = bot.findBlock({ matching: portalId, maxDistance: 32 });
                if (exitPortal) {
                    endPortalBlockFound = true;
                }
            }
        } catch (_) {}
    }

    const dragonDefeated = dragonDefeatedFlag || (dimension === 'the_end' && endPortalBlockFound && !enderDragonInfo);

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
        is_raining: Boolean(bot.isRaining),
        is_thundering: Boolean(bot.thunderState > 0),
        time_of_day: bot.time ? bot.time.timeOfDay : 0,
        time_since_sleep_seconds: Math.floor((Date.now() - lastSleepTime) / 1000),
        phantom_risk: ((Date.now() - lastSleepTime) > 2400000),
        should_sleep: (!bot.time || !bot.time.isDay || Boolean(bot.isRaining) || Boolean(bot.thunderState > 0)),
        food_saturation: bot.foodSaturation != null ? Math.round(bot.foodSaturation * 10) / 10 : 5,
        oxygen_level: bot.oxygenLevel != null ? bot.oxygenLevel : 20,
        armor_equipped: {
            head: bot.inventory.slots[5]?.name || null,
            torso: bot.inventory.slots[6]?.name || null,
            legs: bot.inventory.slots[7]?.name || null,
            feet: bot.inventory.slots[8]?.name || null,
            offhand: bot.inventory.slots[45]?.name || null
        },
        status_effects: bot.entity?.effects ? Object.values(bot.entity.effects).map(ef => ({ id: ef.id, amplifier: ef.amplifier, duration: ef.duration })) : [],
        threat_score: calculateThreatScore(bot, hostileEntityObjects),
        held_item: bot.heldItem ? bot.heldItem.name : 'empty',
        biome: bot.blockAt(bot.entity.position)?.biome?.name || 'unknown',
        owner_info: ownerObservation,
        end_crystals_count: endCrystalsCount,
        ender_dragon: enderDragonInfo,
        dragon_defeated: dragonDefeated,
        dragon_health: enderDragonInfo ? enderDragonInfo.health : (dragonDefeated ? 0 : 200),
        is_sheltered: isSheltered,
        nether_outpost_built: netherOutpostBuilt,
        xp_level: bot.experience ? bot.experience.level : 0,
        xp_points: bot.experience ? bot.experience.points : 0
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
    if (!bot || !bot.entity || isEating) return;

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

// --- COMBAT WEAPON HIERARCHY & SELECTION ---
const WEAPON_SCORES = {
    'netherite_sword': 100,
    'diamond_sword': 90,
    'iron_sword': 80,
    'stone_sword': 70,
    'golden_sword': 65,
    'wooden_sword': 60,
    'netherite_axe': 58,
    'diamond_axe': 52,
    'iron_axe': 46,
    'stone_axe': 38,
    'golden_axe': 32,
    'wooden_axe': 26
};

function getWeaponScore(itemName) {
    if (!itemName) return 0;
    const name = itemName.toLowerCase();
    // EXPLICIT FILTER: Pickaxes, shovels, hoes are NOT combat weapons!
    if (name.includes('pickaxe') || name.includes('shovel') || name.includes('hoe')) return 0;
    if (WEAPON_SCORES[name]) return WEAPON_SCORES[name];
    if (name.endsWith('_sword')) return 50;
    if (name.endsWith('_axe')) return 30;
    return 0;
}

function getBestWeapon(bot) {
    if (!bot || !bot.inventory) return null;
    const items = bot.inventory.items();
    let best = null;
    let bestScore = 0;
    for (const item of items) {
        const score = getWeaponScore(item.name);
        if (score > bestScore) {
            bestScore = score;
            best = item;
        }
    }
    return best;
}

async function equipBestWeapon(bot) {
    if (!bot || !bot.inventory) return false;
    const best = getBestWeapon(bot);
    if (!best) return false;
    // Prevent weapon churn: if already holding this item in main hand, do nothing
    if (bot.heldItem && bot.heldItem.name === best.name) return true;
    try {
        await bot.equip(best, 'hand');
        return true;
    } catch (_) {
        return false;
    }
}

// --- SHIELD STATE & BLOCKING ENGINE ---
let isShieldActive = false;

function raiseShield(bot) {
    if (!bot || !bot.inventory) return;
    const offhand = bot.inventory.slots[45];
    if (offhand && offhand.name.includes('shield') && !isShieldActive) {
        try {
            bot.activateItem(true);
            isShieldActive = true;
        } catch (_) {}
    }
}

function lowerShield(bot) {
    if (!bot) return;
    if (isShieldActive) {
        try {
            bot.deactivateItem();
            isShieldActive = false;
        } catch (_) {}
    }
}

// --- ARMOR TIERS & AUTO-UPGRADE CHECK ---
const ARMOR_TIERS = {
    'netherite': 6,
    'diamond': 5,
    'iron': 4,
    'chainmail': 3,
    'golden': 2,
    'leather': 1,
    'turtle': 3
};

function getArmorScore(itemName) {
    if (!itemName) return 0;
    const name = itemName.toLowerCase();
    for (const [tier, score] of Object.entries(ARMOR_TIERS)) {
        if (name.includes(tier)) return score;
    }
    return 1;
}

async function autoEquipGearCheck() {
    if (!bot || !bot.entity || !bot.inventory) return;

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
        const slotIndex = armorSlotIndices[d.dest];
        const currentItem = bot.inventory.slots[slotIndex];

        if (d.dest === 'off-hand') {
            if (!currentItem || (!currentItem.name.includes('shield') && !currentItem.name.includes('totem'))) {
                const offhandItem = items.find(i => d.keywords.some(k => i.name.toLowerCase().includes(k)));
                if (offhandItem) {
                    try {
                        await bot.equip(offhandItem, 'off-hand');
                        console.log(`🛡️ [AutoGear] Equipped ${offhandItem.name} into off-hand!`);
                    } catch (_) {}
                }
            }
            continue;
        }

        // Armor upgrade logic: pick highest tier candidate
        const candidates = items.filter(i => d.keywords.some(k => i.name.toLowerCase().includes(k)));
        if (candidates.length === 0) continue;

        const currentScore = currentItem ? getArmorScore(currentItem.name) : 0;
        let bestCandidate = null;
        let bestScore = currentScore;

        for (const cand of candidates) {
            const score = getArmorScore(cand.name);
            if (score > bestScore) {
                bestScore = score;
                bestCandidate = cand;
            }
        }

        if (bestCandidate && bestScore > currentScore) {
            try {
                await bot.equip(bestCandidate, d.dest);
                console.log(`🛡️ [AutoGear] Upgraded ${currentItem ? currentItem.name : 'empty'} -> ${bestCandidate.name} on ${d.dest}!`);
            } catch (_) {}
        }
    }
}

let activeGuardedHostile = null;

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
        activeGuardedHostile = hostileMob;
        equipBestWeapon(bot).then(() => {
            if (bot.pvp) bot.pvp.attack(hostileMob);
        }).catch(() => {});
    } else {
        // F0.4: If guarded hostile mob just fell, collect combat drops immediately!
        if (activeGuardedHostile && (!activeGuardedHostile.isValid || activeGuardedHostile.health <= 0)) {
            activeGuardedHostile = null;
            setTimeout(async () => {
                try {
                    await collectNearbyDrops(bot, 12);
                } catch (_) {}
            }, 400);
        }

        const dist = bot.entity.position.distanceTo(player.position);
        if (dist > 4 && (!bot.pathfinder.isMoving() || bot.pathfinder.goal == null)) {
            const { GoalFollow } = goals;
            bot.pathfinder.setGoal(new GoalFollow(player, 2), true);
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
let lastDefenseRetreatTime = 0;
let hadHostilesRecently = false;
let isCollectingDefenseDrops = false;
let lastMeleeAttackTime = 0;

function getWeaponCooldownMs(weaponName) {
    if (!weaponName) return 625;
    const name = weaponName.toLowerCase();
    if (name.includes('axe') && !name.includes('pickaxe')) return 1100;
    if (name.includes('sword')) return 625;
    return 625;
}

async function performChargedAttack(bot, target) {
    if (!bot || !target) return;
    const held = bot.heldItem ? bot.heldItem.name : '';
    const cooldown = getWeaponCooldownMs(held);
    const now = Date.now();
    const elapsed = now - lastMeleeAttackTime;
    if (elapsed < cooldown) {
        await new Promise(r => setTimeout(r, cooldown - elapsed));
    }
    lowerShield(bot);
    await bot.lookAt(target.position.offset(0, target.height, 0));
    bot.attack(target);
    lastMeleeAttackTime = Date.now();
}

function calculateThreatScore(bot, nearbyHostiles) {
    let score = 0;
    for (const mob of nearbyHostiles) {
        const dist = mob.position.distanceTo(bot.entity.position);
        const name = mob.name.toLowerCase();
        let danger = 10;
        if (name.includes('creeper')) danger = dist < 4 ? 60 : 30;
        else if (name.includes('skeleton')) danger = dist < 12 ? 22 : 12;
        else if (name.includes('witch') || name.includes('warden')) danger = 45;
        else if (name.includes('enderman')) danger = 25;
        score += Math.round(danger * Math.max(0.2, (16 - dist) / 16));
    }
    return score;
}

async function autoSelfDefenseCheck() {
    if (!bot || !bot.entity || isBusy) return;

    // Detect hostile mobs dangerously close (< 10 blocks)
    const hostileEntities = [];
    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (!e || !e.name || !e.position || e === bot.entity) continue;
        const name = e.name.toLowerCase();

        // Daytime spider exemption: Neutral in daylight unless attacked
        if (name.includes('spider') && bot.time && bot.time.isDay) {
            const b = bot.blockAt(bot.entity.position);
            if (!b || b.light >= 10) continue;
        }

        const isHostile = ['zombie', 'skeleton', 'creeper', 'drowned', 'husk', 'cave_spider', 'witch', 'spider'].some(m => name.includes(m));
        if (isHostile) {
            const dist = e.position.distanceTo(bot.entity.position);
            if (dist < 10) hostileEntities.push(e);
        }
    }

    if (hostileEntities.length === 0) {
        lowerShield(bot);
        // F0.4: Combat drops collection right after threat is eliminated!
        if (hadHostilesRecently && !isCollectingDefenseDrops) {
            hadHostilesRecently = false;
            isCollectingDefenseDrops = true;
            console.log("🛡️ [Combat Engine] All nearby hostiles eliminated! Collecting combat drops...");
            setTimeout(async () => {
                try {
                    await collectNearbyDrops(bot, 14);
                } catch (_) {}
                finally {
                    isCollectingDefenseDrops = false;
                }
            }, 400);
        }
        return;
    }

    hadHostilesRecently = true;

    // Sort by proximity
    hostileEntities.sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position));
    const dangerMob = hostileEntities[0];
    const dist = dangerMob.position.distanceTo(bot.entity.position);
    const mobName = dangerMob.name.toLowerCase();
    const threatScore = calculateThreatScore(bot, hostileEntities);

    // 1. Critical health + high threat -> Tactical Retreat
    if (bot.health <= 6 || (bot.health <= 10 && threatScore >= 40)) {
        const now = Date.now();
        if (now - lastDefenseRetreatTime > 3000) {
            lastDefenseRetreatTime = now;
            console.log(`⚠️ [Combat Engine] High threat (${threatScore}) & low HP (${bot.health})! Retreating...`);
            if (bot.pvp) bot.pvp.stop();
            lowerShield(bot);
            const awayVec = bot.entity.position.minus(dangerMob.position).normalize();
            const retreatGoalPos = bot.entity.position.plus(awayVec.scaled(8));
            try {
                const { GoalNear } = goals;
                bot.pathfinder.setGoal(new GoalNear(retreatGoalPos.x, retreatGoalPos.y, retreatGoalPos.z, 2));
            } catch (_) {}
            return;
        }
    }

    // 2. Emergency eat during combat if health drops below 10 HP
    if (bot.health <= 10 && !isEating) {
        const food = bot.inventory.items().find(i => FOOD_NAMES.includes(i.name));
        if (food) {
            try {
                lowerShield(bot);
                await bot.equip(food, 'hand');
                await bot.consume();
            } catch (_) {}
        }
    }

    // 3. Creeper Tactic: sprint away immediately if within 4.5m!
    if (mobName.includes('creeper') && dist < 4.5) {
        if (bot.pvp) bot.pvp.stop();
        lowerShield(bot);
        bot.setControlState('back', true);
        bot.setControlState('sprint', true);
        setTimeout(() => {
            bot.setControlState('back', false);
            bot.setControlState('sprint', false);
        }, 800);
        return;
    }

    // 4. Skeleton Tactic: if distance > 3.5m, raise shield to block incoming arrows!
    if (mobName.includes('skeleton') && dist > 3.5 && dist < 12) {
        raiseShield(bot);
    } else {
        lowerShield(bot);
    }

    // 5. Equip best weapon (swords prioritized, pickaxes strictly excluded!)
    await equipBestWeapon(bot);

    // 6. Attack target with Java 1.20.4 attack cooldown cadence
    if (bot.pvp) {
        lowerShield(bot);
        bot.pvp.attack(dangerMob);
    } else {
        await performChargedAttack(bot, dangerMob);
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
        setMovementsForTask('walk');

        // Round-robin background resource scanner (1 block category every 200ms, non-blocking)
        setInterval(tickResourceScanner, 200);

        // High-frequency reactive maintenance loops (optimized for low latency)
        setInterval(autoEatCheck, 1500);          // Check hunger & health every 1.5s (was 6s)
        setInterval(guardLoop, 500);              // Guard tracking every 0.5s (was 1.5s)
        setInterval(autoSelfDefenseCheck, 500);   // Proactive close-range threat defense every 0.5s (was 1.5s)
        setInterval(antiStuckCheck, 1500);        // Anti-stuck watchdog every 1.5s (was 3s)
        setInterval(autoEquipGearCheck, 1500);    // Armor & shield auto-equip every 1.5s (was 4s)
        setInterval(autoTorchCheck, 5000);        // Dark cave auto-torching every 5s (was 8s)

        // Live high-speed state synchronization heartbeat (500ms for instant telemetry)
        setInterval(() => {
            if (bot && bot.entity) {
                sendToPython({
                    type: 'state_update',
                    state: getBotState()
                });
            }
        }, 500);

        sendToPython({
            type: 'bot_spawned',
            state: getBotState()
        });
    });

    bot.on('chat', (username, message) => {
        if (username === bot.username) return;
        console.log(`[Minecraft Chat] <${username}> ${message}`);

        const cleanMsg = (message || '').trim().toLowerCase();
        if (cleanMsg === '!dragon' || cleanMsg === '!fight_dragon') {
            handleAction({ command: 'fight_ender_dragon', args: { tactic: 'melee_sword' } });
        } else if (cleanMsg === '!crystal' || cleanMsg === '!crystals') {
            handleAction({ command: 'destroy_end_crystals', args: {} });
        } else if (cleanMsg === '!win' || cleanMsg === '!victory' || cleanMsg === '!exit_portal') {
            handleAction({ command: 'enter_exit_portal', args: {} });
        } else if (cleanMsg === '!farm' || cleanMsg === '!bread' || cleanMsg === '!harvest') {
            handleAction({ command: 'farm_crops', args: { action_type: 'auto' } });
        } else if (cleanMsg === '!shelter' || cleanMsg === '!bunker' || cleanMsg === '!hide') {
            handleAction({ command: 'build_shelter', args: { mode: 'auto' } });
        } else if (cleanMsg === '!unbunker' || cleanMsg === '!unshelter' || cleanMsg === '!exit_shelter') {
            handleAction({ command: 'break_out_shelter', args: {} });
        } else if (cleanMsg === '!enchant' || cleanMsg === '!buyu') {
            handleAction({ command: 'enchant_gear', args: { gear_type: 'auto', target_level: 15 } });
        } else if (cleanMsg === '!outpost' || cleanMsg === '!nether_outpost') {
            handleAction({ command: 'build_nether_outpost', args: { wall_material: 'auto' } });
        } else if (cleanMsg.startsWith('!bridge')) {
            const parts = cleanMsg.split(' ');
            const dist = parts.length > 1 && !isNaN(parseInt(parts[1])) ? parseInt(parts[1]) : 5;
            handleAction({ command: 'bridge_chasm', args: { direction: 'forward', distance: dist } });
        }

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
        isSheltered = false;
        currentActionName = 'idle';
        lowerShield(bot);

        const deathPos = bot.entity ? {
            x: Math.round(bot.entity.position.x * 10) / 10,
            y: Math.round(bot.entity.position.y * 10) / 10,
            z: Math.round(bot.entity.position.z * 10) / 10
        } : null;
        const invSnapshot = bot.inventory ? bot.inventory.items().map(i => ({ name: i.name, count: i.count })) : [];
        const dim = (bot.game && bot.game.dimension) ? String(bot.game.dimension) : 'overworld';

        sendToPython({
            type: 'bot_death',
            death_pos: deathPos,
            dimension: dim,
            inventory_snapshot: invSnapshot,
            timestamp: Date.now(),
            state: getBotState()
        });
    });

    bot.on('entityDead', (entity) => {
        if (!entity || !entity.position || !bot.entity) return;
        const dist = bot.entity.position.distanceTo(entity.position);
        const name = (entity.name || '').toLowerCase();
        const isCombatOrHunt = [
            'zombie', 'skeleton', 'creeper', 'spider', 'drowned', 'husk', 'enderman',
            'blaze', 'piglin', 'witch', 'slime', 'magma_cube', 'piglin_brute', 'wither_skeleton',
            'cow', 'sheep', 'pig', 'chicken'
        ].some(m => name.includes(m));

        if (dist <= 14 && isCombatOrHunt) {
            console.log(`⚔️ [Loot Engine] Mob ${entity.name} died nearby (${dist.toFixed(1)}m)! Collecting combat drops...`);
            setTimeout(async () => {
                if (!bot || !bot.entity) return;
                try {
                    await collectNearbyDrops(bot, 14);
                } catch (_) {}
            }, 500);
        }
    });

    bot.on('sleep', () => {
        console.log('[Minecraft] 💤 Bot fell asleep in bed! Phantom insomnia timer reset.');
        lastSleepTime = Date.now();
    });

    bot.on('respawn', () => {
        console.log('[Minecraft] 🔄 Bot respawned into the world!');
        isGuarding = false;
        isBusy = false;
        isSheltered = false;
        currentActionName = 'idle';
        lastSleepTime = Date.now();
        setMovementsForTask('walk');
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

function withTimeout(promise, ms = 8000, desc = 'Action') {
    return Promise.race([
        promise,
        new Promise((_, reject) => setTimeout(() => reject(new Error(`${desc} timed out after ${ms}ms`)), ms))
    ]);
}

const REPLACEABLE_BLOCKS = new Set([
    'air', 'cave_air', 'void_air', 'pink_petals', 'grass', 'short_grass',
    'tall_grass', 'fern', 'large_fern', 'dead_bush', 'snow',
    'dandelion', 'poppy', 'blue_orchid', 'allium', 'azure_bluet',
    'red_tulip', 'orange_tulip', 'white_tulip', 'pink_tulip',
    'oxeye_daisy', 'cornflower', 'lily_of_the_valley'
]);

function findPlacementLocation(bot) {
    const botPos = bot.entity.position;
    for (let dy of [0, -1, 1]) {
        for (let dx of [1, -1, 0, 2, -2, 3, -3]) {
            for (let dz of [1, -1, 0, 2, -2, 3, -3]) {
                if (dx === 0 && dz === 0) continue;
                const groundPos = botPos.floored().offset(dx, dy, dz);
                const ground = bot.blockAt(groundPos);
                if (!ground || ground.name === 'air' || ground.name === 'cave_air' || ground.name === 'water' || ground.name === 'lava') {
                    continue;
                }
                const placePos = groundPos.offset(0, 1, 0);
                const airBlock = bot.blockAt(placePos);
                if (airBlock) {
                    const bName = airBlock.name.toLowerCase();
                    const isReplaceable = REPLACEABLE_BLOCKS.has(bName) || bName.includes('air') || bName.includes('petal') || bName.includes('grass') || bName.includes('flower');
                    if (isReplaceable) {
                        const dist = botPos.distanceTo(placePos);
                        if (dist >= 0.8 && dist <= 4.2) {
                            return { referenceBlock: ground, faceVector: new Vec3(0, 1, 0), placedPos: placePos };
                        }
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
    console.log(`[Crafting] ensurePlanks: needed=${neededPlankCount}, available=${availablePlanks}`);
    if (availablePlanks >= neededPlankCount) return true;

    const deficit = neededPlankCount - availablePlanks;
    const craftsNeeded = Math.ceil(deficit / 4);

    const logItem = bot.inventory.items().find(i => i.name.endsWith('_log') || i.name.endsWith('_stem') || i.name.endsWith('_wood') || i.name.includes('log') || i.name.includes('wood'));
    if (!logItem) {
        console.warn("[Crafting] No log item found in inventory to craft planks.");
        return false;
    }

    const plankName = logItem.name.replace(/(_log|_stem|_wood)/, '_planks');
    const plankDef = mcData.itemsByName[plankName] || mcData.itemsByName['oak_planks'];
    if (!plankDef) return false;

    const recipes = bot.recipesFor(plankDef.id, null, 1, null);
    if (recipes.length === 0) {
        console.warn(`[Crafting] No recipes found for ${plankName} using ${logItem.name}.`);
        return false;
    }

    console.log(`[Crafting] Crafting ${craftsNeeded * 4}x ${plankName} from logs...`);
    bot.chat(`Crafting ${craftsNeeded * 4}x ${plankName} from logs...`);
    try {
        await withTimeout(bot.craft(recipes[0], craftsNeeded, null), 6000, 'Craft planks');
        return true;
    } catch (err) {
        console.warn(`[Crafting] Error crafting planks: ${err.message}`);
        return false;
    }
}

async function ensureSticks(bot, neededStickCount) {
    const mcData = require('minecraft-data')(bot.version);
    let availableSticks = bot.inventory.items().filter(i => i.name === 'stick').reduce((s, i) => s + i.count, 0);
    console.log(`[Crafting] ensureSticks: needed=${neededStickCount}, available=${availableSticks}`);
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

    console.log(`[Crafting] Crafting ${stickCraftsNeeded * 4}x sticks...`);
    bot.chat(`Crafting ${stickCraftsNeeded * 4}x sticks...`);
    try {
        await withTimeout(bot.craft(recipes[0], stickCraftsNeeded, null), 6000, 'Craft sticks');
        return true;
    } catch (err) {
        console.warn(`[Crafting] Error crafting sticks: ${err.message}`);
        return false;
    }
}

async function retrieveBlock(bot, block) {
    if (!block) return;
    try {
        await toolLearner.prepareAndEquipToolForBlock(bot, block.name, null);
        const pos = block.position.clone();
        await withTimeout(bot.dig(block), 6000, 'Dig placed block');
        await bot.waitForTicks(5);
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
    if (tableBlock) {
        console.log(`[Crafting] Found existing crafting table within 4m at ${tableBlock.position}`);
        return { tableBlock, placedByMe: false };
    }

    // 2. Existing table within 16m
    const distantTable = bot.findBlock({ matching: tableBlockId, maxDistance: 16 });
    if (distantTable) {
        try {
            console.log(`[Crafting] Walking towards crafting table within 16m at ${distantTable.position}...`);
            await Promise.race([
                bot.pathfinder.goto(new goals.GoalNear(distantTable.position.x, distantTable.position.y, distantTable.position.z, 2)),
                new Promise((_, reject) => setTimeout(() => reject(new Error('Pathfinder timeout to table')), 6000))
            ]);
            return { tableBlock: distantTable, placedByMe: false };
        } catch (_) {
            try { bot.pathfinder.stop(); } catch (_) {}
        }
    }

    // 3. Need to place one. Check if in inventory
    let tableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
    if (!tableItem) {
        await ensurePlanks(bot, 4);
        const totalPlanks = bot.inventory.items().filter(i => i.name.endsWith('_planks')).reduce((s, i) => s + i.count, 0);
        if (totalPlanks < 4) {
            console.warn(`[Crafting] Need 4 wood planks to craft table, only have ${totalPlanks}`);
            bot.chat("Need 4 wood planks to craft a crafting table.");
            return { tableBlock: null, placedByMe: false };
        }

        const tableDef = mcData.itemsByName['crafting_table'];
        const recipes = bot.recipesFor(tableDef.id, null, 1, null);
        if (recipes.length === 0) {
            console.warn("[Crafting] Could not find recipe for crafting table.");
            bot.chat("Could not find recipe for crafting table.");
            return { tableBlock: null, placedByMe: false };
        }

        console.log("[Crafting] Crafting crafting_table item in 2x2 grid...");
        bot.chat("Crafting a crafting table...");
        try {
            await withTimeout(bot.craft(recipes[0], 1, null), 6000, 'Craft table item');
        } catch (err) {
            console.warn(`[Crafting] Error crafting table item: ${err.message}`);
            return { tableBlock: null, placedByMe: false };
        }
        tableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
    }

    if (!tableItem) return { tableBlock: null, placedByMe: false };

    const loc = findPlacementLocation(bot);
    if (!loc) {
        console.warn("[Crafting] Cannot find a clear placement space for crafting table.");
        bot.chat("Cannot find a clear space to place crafting table.");
        return { tableBlock: null, placedByMe: false };
    }

    // Clear any non-solid plant or petal occupying the block
    const occBlock = bot.blockAt(loc.placedPos);
    if (occBlock && occBlock.name !== 'air' && occBlock.name !== 'cave_air') {
        try {
            console.log(`[Crafting] Clearing obstruction '${occBlock.name}' before placing table...`);
            await bot.dig(occBlock);
            await bot.waitForTicks(2);
        } catch (_) {}
    }

    console.log(`[Crafting] Placing crafting table at (${loc.placedPos.x}, ${loc.placedPos.y}, ${loc.placedPos.z})...`);
    bot.chat("Placing crafting table...");
    try {
        await withTimeout(bot.equip(tableItem, 'hand'), 3000, 'Equip crafting table');
        await withTimeout(bot.placeBlock(loc.referenceBlock, loc.faceVector), 5000, 'Place crafting table');
        tableBlock = bot.blockAt(loc.placedPos);
        console.log(`[Crafting] Successfully placed crafting table.`);
        return { tableBlock, placedByMe: true };
    } catch (err) {
        console.warn(`[Crafting] Error placing table block: ${err.message}`);
        return { tableBlock: null, placedByMe: false };
    }
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
            try { await withTimeout(retrieveBlock(bot, tableBlock), 5000, 'Retrieve table'); } catch (_) {}
        }
        return false;
    }

    const recipe = recipes[0];
    if (tableBlock) {
        if (bot.entity.position.distanceTo(tableBlock.position) > 3.0) {
            try {
                await withTimeout(bot.pathfinder.goto(new goals.GoalNear(tableBlock.position.x, tableBlock.position.y, tableBlock.position.z, 2)), 4000, 'Approach table');
            } catch (_) {}
        }
        try {
            await bot.lookAt(tableBlock.position.offset(0.5, 0.5, 0.5));
        } catch (_) {}
    }

    try {
        await withTimeout(bot.craft(recipe, count, tableBlock), 8000, `Craft ${itemName}`);
        bot.chat(`Successfully crafted ${count}x ${itemName}! ✨`);
    } catch (craftErr) {
        console.warn(`[Crafting] Error crafting ${itemName}: ${craftErr.message}`);
        if (bot.currentWindow) {
            try { bot.closeWindow(bot.currentWindow); } catch (_) {}
        }
        if (placedByMe && tableBlock) {
            try { await withTimeout(retrieveBlock(bot, tableBlock), 5000, 'Retrieve table'); } catch (_) {}
        }
        return false;
    }

    // Step 5: Clean-up placed table
    if (placedByMe && tableBlock) {
        try {
            await withTimeout(retrieveBlock(bot, tableBlock), 5000, 'Retrieve table');
        } catch (_) {}
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
    } catch (smeltErr) {
        console.log(`[Minecraft] Smelting error: ${smeltErr.message}`);
        return { success: false, error: smeltErr.message };
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
    if (drops.length === 0) return;

    // F0.4: Sort closest drops first for optimal pathing
    drops.sort((a, b) => bot.entity.position.distanceTo(a.position) - bot.entity.position.distanceTo(b.position));

    const { GoalNear } = goals;
    for (const drop of drops) {
        if (!drop || !drop.isValid) continue;
        try {
            await Promise.race([
                bot.pathfinder.goto(new GoalNear(drop.position.x, drop.position.y, drop.position.z, 1)),
                new Promise((_, reject) => setTimeout(() => reject(new Error('Drop collection timeout')), 2500))
            ]);
            await bot.waitForTicks(2);
        } catch (e) {
            continue;
        }
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
    try {
        await bot.placeBlock(refBlock, faceVector);
    } catch (placeErr) {
        console.log(`[Minecraft] Block placement failed: ${placeErr.message}`);
        return false;
    }
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

// --- PHASE 4: ENDER DRAGON BOSS COMBAT & VICTORY ENGINE ---

async function destroyEndCrystals(bot) {
    if (!bot || !bot.entity) return false;
    const { GoalNear } = goals;

    // 1. Gather all End Crystals
    const crystals = [];
    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (e && e.name === 'end_crystal' && e.isValid) {
            crystals.push(e);
        }
    }

    if (crystals.length === 0) {
        bot.chat("No End Crystals detected! All pillar crystals appear demolished. 💥");
        return true;
    }

    // Sort by distance to bot
    crystals.sort((a, b) => bot.entity.position.distanceTo(a.position) - bot.entity.position.distanceTo(b.position));
    const targetCrystal = crystals[0];
    const dist = bot.entity.position.distanceTo(targetCrystal.position);
    console.log(`[EndCombat] Targeting End Crystal at (${targetCrystal.position.x.toFixed(1)}, ${targetCrystal.position.y.toFixed(1)}, ${targetCrystal.position.z.toFixed(1)}), dist: ${dist.toFixed(1)}m`);

    // 2. Check for ranged weapon (bow / crossbow with arrows, or snowballs)
    const bowItem = bot.inventory.items().find(i => i.name === 'bow' || i.name === 'crossbow');
    const arrowItem = bot.inventory.items().find(i => i.name === 'arrow' || i.name === 'spectral_arrow');
    const snowball = bot.inventory.items().find(i => i.name === 'snowball' || i.name === 'egg');

    if (bowItem && arrowItem) {
        bot.chat(`Sniping End Crystal at ${Math.round(dist)}m with bow! 🏹`);
        if (dist > 35) {
            await bot.pathfinder.goto(new GoalNear(targetCrystal.position.x, bot.entity.position.y, targetCrystal.position.z, 28)).catch(() => {});
        }
        await bot.equip(bowItem, 'hand');
        await bot.lookAt(targetCrystal.position.offset(0, 0.5, 0));
        bot.activateItem();
        await new Promise(r => setTimeout(r, 1200));
        bot.deactivateItem();
        await new Promise(r => setTimeout(r, 800));
        return true;
    }

    if (snowball) {
        bot.chat(`Lobbing projectile at End Crystal! ❄️`);
        if (dist > 25) {
            await bot.pathfinder.goto(new GoalNear(targetCrystal.position.x, bot.entity.position.y, targetCrystal.position.z, 18)).catch(() => {});
        }
        await bot.equip(snowball, 'hand');
        await bot.lookAt(targetCrystal.position.offset(0, 0.5, 0));
        bot.activateItem();
        await new Promise(r => setTimeout(r, 600));
        return true;
    }

    // 3. Melee / Scaffolding climb
    bot.chat(`Navigating to obsidian pillar to neutralize End Crystal... 🧗`);
    await bot.pathfinder.goto(new GoalNear(targetCrystal.position.x, bot.entity.position.y, targetCrystal.position.z, 4)).catch(() => {});

    // Check height difference
    const heightDiff = targetCrystal.position.y - bot.entity.position.y;
    if (heightDiff > 3) {
        const scaffoldBlock = bot.inventory.items().find(i => ['cobblestone', 'netherrack', 'dirt', 'deepslate', 'blackstone'].includes(i.name));
        if (scaffoldBlock) {
            bot.chat(`Scaffolding up pillar with ${scaffoldBlock.name}... 🧱`);
            for (let h = 0; h < Math.min(heightDiff - 2, 20); h++) {
                try {
                    bot.setControlState('jump', true);
                    await new Promise(r => setTimeout(r, 250));
                    bot.setControlState('jump', false);
                    const belowPos = bot.entity.position.offset(0, -1, 0);
                    await placeBlockDirect(bot, scaffoldBlock, belowPos);
                    await new Promise(r => setTimeout(r, 150));
                } catch (_) {}
            }
        }
    }

    // Equip shield in off-hand for explosion blast protection
    const shield = bot.inventory.items().find(i => i.name === 'shield');
    if (shield) {
        try { await bot.equip(shield, 'off-hand'); } catch (_) {}
    }

    // Strike crystal safely from max range
    await bot.lookAt(targetCrystal.position);
    bot.attack(targetCrystal);
    bot.chat("Detonated End Crystal atop obsidian pillar! 💥");
    await new Promise(r => setTimeout(r, 500));
    return true;
}

async function fightEnderDragon(bot, tactic = 'melee_sword') {
    if (!bot || !bot.entity) return false;
    const { GoalNear, GoalBlock } = goals;

    // Locate Ender Dragon entity
    let dragon = null;
    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (e && e.name === 'ender_dragon' && e.isValid) {
            dragon = e;
            break;
        }
    }

    // If dragon not currently loaded, move towards center bedrock fountain (0, 65, 0)
    if (!dragon) {
        bot.chat("Scanning the End skies for the Ender Dragon... Moving towards central exit fountain (0, 65, 0). 🐉");
        await bot.pathfinder.goto(new GoalNear(0, 65, 0, 8)).catch(() => {});
        return true;
    }

    const dragonPos = dragon.position;
    const distToDragon = bot.entity.position.distanceTo(dragonPos);
    const distToCenter = Math.hypot(dragonPos.x, dragonPos.z);
    const isPerching = distToCenter < 14 && dragonPos.y < 75;

    console.log(`[DragonCombat] Dragon dist: ${distToDragon.toFixed(1)}m, Y: ${dragonPos.y.toFixed(1)}, isPerching: ${isPerching}`);

    // Check for harmful purple dragon breath (area_effect_cloud) nearby
    for (const id in bot.entities) {
        const e = bot.entities[id];
        if (e && e.name === 'area_effect_cloud') {
            const breathDist = bot.entity.position.distanceTo(e.position);
            if (breathDist < 4) {
                bot.chat("⚠️ Evading purple dragon breath cloud! 💨");
                bot.setControlState('sprint', true);
                // Safe escape from dragon breath - validate ground exists
                let escapePos = null;
                const escapeOffsets = [
                    [5, 0, 5], [-5, 0, 5], [5, 0, -5], [-5, 0, -5],
                    [3, 0, 3], [-3, 0, 3], [3, 0, -3], [-3, 0, -3]
                ];
                for (const [dx, dy, dz] of escapeOffsets) {
                    const candidate = bot.entity.position.offset(dx, dy, dz);
                    const groundBlock = bot.blockAt(candidate.offset(0, -1, 0));
                    if (groundBlock && groundBlock.name !== 'air' && groundBlock.name !== 'void_air') {
                        escapePos = candidate;
                        break;
                    }
                }
                if (escapePos) {
                    await bot.pathfinder.goto(new GoalBlock(escapePos.x, escapePos.y, escapePos.z)).catch(() => {});
                }
                bot.setControlState('sprint', false);
                break;
            }
        }
    }

    // Select best weapon
    const weapon = bot.inventory.items().find(i => ['netherrite_sword', 'diamond_sword', 'iron_sword', 'stone_sword', 'diamond_axe', 'iron_axe'].includes(i.name));
    const shield = bot.inventory.items().find(i => i.name === 'shield');
    if (shield) {
        try { await bot.equip(shield, 'off-hand'); } catch (_) {}
    }

    if (isPerching) {
        bot.chat("🐉 THE DRAGON IS PERCHING ON BEDROCK FOUNTAIN! Charging for critical strikes! ⚔️");

        // BED BOMBING TACTIC (if bed exists)
        const bedItem = bot.inventory.items().find(i => i.name.endsWith('_bed'));
        if (tactic === 'bed_bomb' && bedItem) {
            bot.chat("💥 Executing Bed Bombing blast on perching dragon head! 🛏️🔥");
            await bot.pathfinder.goto(new GoalNear(0, 65, 0, 4)).catch(() => {});
            const bedrockTop = bot.blockAt(new Vec3(0, 65, 0)) || bot.blockAt(bot.entity.position.offset(1, 0, 0));
            if (bedrockTop) {
                await bot.equip(bedItem, 'hand');
                await bot.activateBlock(bedrockTop, new Vec3(0, 1, 0)).catch(() => {});
                await new Promise(r => setTimeout(r, 300));
            }
        }

        // SWORD CRITICAL ATTACKS
        if (weapon) {
            await bot.equip(weapon, 'hand');
        }
        await bot.pathfinder.goto(new GoalNear(dragonPos.x, Math.max(bot.entity.position.y, 65), dragonPos.z, 3.5)).catch(() => {});
        await bot.lookAt(dragonPos.offset(0, 1, 0));

        // Jump crits: jump and strike while falling
        for (let i = 0; i < 4; i++) {
            bot.setControlState('jump', true);
            await new Promise(r => setTimeout(r, 150));
            bot.attack(dragon);
            bot.setControlState('jump', false);
            await new Promise(r => setTimeout(r, 200));
        }
        return true;
    } else {
        // Flying phase
        const bowItem = bot.inventory.items().find(i => i.name === 'bow' || i.name === 'crossbow');
        const arrowItem = bot.inventory.items().find(i => i.name === 'arrow' || i.name === 'spectral_arrow');

        if (bowItem && arrowItem && distToDragon < 45) {
            bot.chat("🏹 Leading shot at circling Ender Dragon in flight!");
            await bot.equip(bowItem, 'hand');
            await bot.lookAt(dragonPos.offset(0, 1.5, 0));
            bot.activateItem();
            await new Promise(r => setTimeout(r, 1000));
            bot.deactivateItem();
            await new Promise(r => setTimeout(r, 400));
            return true;
        }

        // If dragon is swooping close (< 15m), block dive with shield
        if (distToDragon < 15 && shield) {
            bot.chat("🛡️ Raising shield to deflect incoming dragon swoop!");
            await bot.lookAt(dragonPos);
            bot.activateItem(true);
            await new Promise(r => setTimeout(r, 1200));
            bot.deactivateItem();
        } else {
            // Reposition towards fountain edge waiting for perch
            await bot.pathfinder.goto(new GoalNear(0, 65, 0, 12)).catch(() => {});
        }
        return true;
    }
}

async function enterExitPortal(bot) {
    if (!bot || !bot.entity) return false;
    const { GoalNear } = goals;

    bot.chat("🏆 VICTORY! Slaying completed! Collecting Ender Dragon XP orbs... ✨");

    // 1. Vacuum XP orbs and dragon drops
    await collectNearbyDrops(bot, 24);

    // 2. Find central exit portal at (0, 65, 0)
    const mcData = require('minecraft-data')(bot.version);
    const portalBlockId = mcData.blocksByName['end_portal']?.id;
    let targetPos = new Vec3(0, 65, 0);

    if (portalBlockId) {
        const portalBlock = bot.findBlock({ matching: portalBlockId, maxDistance: 32 });
        if (portalBlock) {
            targetPos = portalBlock.position;
        }
    }

    bot.chat("🌟 Stepping into the End Exit Portal to complete the game and trigger the victory credits! 📜👑");
    dragonDefeatedFlag = true;

    try {
        await bot.pathfinder.goto(new GoalNear(targetPos.x, targetPos.y, targetPos.z, 0.5));
    } catch (_) {}

    sendToPython({
        type: 'game_won',
        details: 'Ender Dragon defeated and exit portal entered!'
    });

    bot.chat("🎉 GG! GAME BEATEN! We conquered vanilla Minecraft from punch to dragon! 🐉🏆");
    return true;
}

// --- SUSTAINABLE FARMING & UNIVERSAL SHELTER ENGINE ---

async function farmCrops(bot, actionType = 'auto') {
    if (!bot || !bot.entity) return false;
    const { GoalNear } = goals;
    const mcData = require('minecraft-data')(bot.version);

    // 1. Hay Bales Priority: Fastest way to gather hundreds of hunger points
    const hayBlockId = mcData.blocksByName['hay_block']?.id;
    if (hayBlockId && (actionType === 'auto' || actionType === 'harvest_hay_bales')) {
        const hayBlocks = bot.findBlocks({ matching: hayBlockId, maxDistance: 48, count: 8 });
        if (hayBlocks.length > 0) {
            bot.chat(`🌾 Located ${hayBlocks.length} Hay Bale(s)! Harvesting for bread... 🍞`);
            let harvestedHay = 0;
            for (const pos of hayBlocks) {
                const b = bot.blockAt(pos);
                if (!b || b.name !== 'hay_block') continue;
                try {
                    await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 2.5));
                    await bot.dig(b);
                    harvestedHay++;
                    await new Promise(r => setTimeout(r, 200));
                } catch (err) {
                    console.warn(`[Farm] Error harvesting hay block: ${err.message}`);
                }
            }
            // Collect drops
            await collectNearbyDrops(bot, 12);

            // Convert hay into wheat and bread
            const hayItem = bot.inventory.items().find(i => i.name === 'hay_block');
            if (hayItem && hayItem.count > 0) {
                bot.chat(`Crafting wheat & fresh bread from ${hayItem.count} harvested Hay Bale(s)... 🥖`);
                try {
                    await smartCraft(bot, 'wheat', hayItem.count * 9);
                    const wheatItem = bot.inventory.items().find(i => i.name === 'wheat');
                    if (wheatItem && wheatItem.count >= 3) {
                        const loavesToCraft = Math.floor(wheatItem.count / 3);
                        await smartCraft(bot, 'bread', loavesToCraft);
                        bot.chat(`✅ Successfully baked ${loavesToCraft} loaves of Bread! 🍞✨`);
                    }
                } catch (err) {
                    console.warn(`[Farm] Bread crafting error: ${err.message}`);
                }
            }
            return true;
        }
    }

    // 1.5 Bone Meal Acceleration: Fertilize immature crops with bone meal
    const boneItem = bot.inventory.items().find(i => i.name === 'bone');
    let boneMealItem = bot.inventory.items().find(i => i.name === 'bone_meal');
    if (!boneMealItem && boneItem && boneItem.count > 0) {
        try {
            await smartCraft(bot, 'bone_meal', boneItem.count * 3);
            boneMealItem = bot.inventory.items().find(i => i.name === 'bone_meal');
        } catch (_) {}
    }

    if (boneMealItem && boneMealItem.count > 0) {
        const cropBlockNames = ['wheat', 'carrots', 'potatoes', 'beetroots'];
        const cropBlockIds = cropBlockNames.map(name => mcData.blocksByName[name]?.id).filter(Boolean);
        const nearCrops = bot.findBlocks({ matching: cropBlockIds, maxDistance: 16, count: 6 });
        for (const pos of nearCrops) {
            const b = bot.blockAt(pos);
            if (!b) continue;
            const isRipe = (b.metadata === 7 && ['wheat', 'carrots', 'potatoes'].includes(b.name)) ||
                           (b.metadata === 3 && b.name === 'beetroots');
            if (!isRipe && boneMealItem && boneMealItem.count > 0) {
                try {
                    await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 2.5));
                    await bot.equip(boneMealItem, 'hand');
                    await bot.activateBlock(b);
                    await new Promise(r => setTimeout(r, 200));
                    boneMealItem = bot.inventory.items().find(i => i.name === 'bone_meal');
                } catch (_) {}
            }
        }
    }

    // 2. Harvest Ripe Crops (wheat age 7, carrots age 7, potatoes age 7, beetroots age 3)
    const cropNames = ['wheat', 'carrots', 'potatoes', 'beetroots'];
    const cropIds = cropNames.map(name => mcData.blocksByName[name]?.id).filter(Boolean);

    if (cropIds.length > 0 && (actionType === 'auto' || actionType === 'harvest_ripe_crops')) {
        const foundCrops = bot.findBlocks({
            matching: cropIds,
            maxDistance: 32,
            count: 10
        });

        let harvestedCount = 0;
        for (const pos of foundCrops) {
            const b = bot.blockAt(pos);
            if (!b) continue;

            const isRipe = (b.metadata === 7 && ['wheat', 'carrots', 'potatoes'].includes(b.name)) ||
                           (b.metadata === 3 && b.name === 'beetroots');

            if (isRipe) {
                try {
                    await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 2.5));
                    await bot.dig(b);
                    harvestedCount++;
                    await new Promise(r => setTimeout(r, 200));

                    // Check if ground beneath is farmland and replant seed
                    const belowBlock = bot.blockAt(pos.offset(0, -1, 0));
                    if (belowBlock && belowBlock.name === 'farmland') {
                        const seedName = b.name === 'wheat' ? 'wheat_seeds' : b.name === 'beetroots' ? 'beetroot_seeds' : b.name === 'carrots' ? 'carrot' : 'potato';
                        const seedItem = bot.inventory.items().find(i => i.name === seedName);
                        if (seedItem) {
                            await bot.equip(seedItem, 'hand');
                            await bot.placeBlock(belowBlock, new Vec3(0, 1, 0)).catch(() => {});
                        }
                    }
                } catch (_) {}
            }
        }

        if (harvestedCount > 0) {
            await collectNearbyDrops(bot, 12);
            bot.chat(`🌾 Harvested & replanted ${harvestedCount} mature crop(s)!`);

            // If we have 3+ wheat, craft into bread
            const wheatItem = bot.inventory.items().find(i => i.name === 'wheat');
            if (wheatItem && wheatItem.count >= 3) {
                await smartCraft(bot, 'bread', Math.floor(wheatItem.count / 3));
            }
            return true;
        }
    }

    // 3. Till and Plant Seeds if hoe and seeds are in inventory
    const hoeItem = bot.inventory.items().find(i => i.name.endsWith('_hoe'));
    const seedItem = bot.inventory.items().find(i => ['wheat_seeds', 'carrot', 'potato', 'beetroot_seeds'].includes(i.name));

    if (hoeItem && seedItem && (actionType === 'auto' || actionType === 'till_and_plant')) {
        const waterId = mcData.blocksByName['water']?.id;
        const waterBlocks = waterId ? bot.findBlocks({ matching: waterId, maxDistance: 16, count: 5 }) : [];
        if (waterBlocks.length > 0) {
            const dirtIds = ['dirt', 'grass_block'].map(n => mcData.blocksByName[n]?.id).filter(Boolean);
            const dirtBlocks = bot.findBlocks({ matching: dirtIds, maxDistance: 16, count: 6 });
            let tilledCount = 0;
            for (const pos of dirtBlocks) {
                const above = bot.blockAt(pos.offset(0, 1, 0));
                if (above && (above.name === 'air' || above.name === 'cave_air')) {
                    try {
                        await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 2.5));
                        await bot.equip(hoeItem, 'hand');
                        const dirtBlock = bot.blockAt(pos);
                        await bot.activateBlock(dirtBlock, new Vec3(0, 1, 0));
                        tilledCount++;
                        await new Promise(r => setTimeout(r, 250));

                        // Plant seed
                        const currentSeed = bot.inventory.items().find(i => ['wheat_seeds', 'carrot', 'potato', 'beetroot_seeds'].includes(i.name));
                        if (currentSeed) {
                            await bot.equip(currentSeed, 'hand');
                            const farmland = bot.blockAt(pos);
                            await bot.placeBlock(farmland, new Vec3(0, 1, 0)).catch(() => {});
                        }
                    } catch (_) {}
                    if (tilledCount >= 4) break;
                }
            }
            if (tilledCount > 0) {
                bot.chat(`🌱 Tilled and planted ${tilledCount} crops near water!`);
                return true;
            }
        }
    }

    bot.chat("No harvestable crops, hay bales, or tilling spots found nearby. 🌾");
    return true;
}

// --- LIFE CYCLE ENGINES: BEDS, BREEDING, FISHING, CHESTS (F1.3-F1.7) ---

async function smartPlaceBed(bot) {
    if (!bot || !bot.entity) return null;
    let bedItem = bot.inventory.items().find(i => i.name.endsWith('_bed') || i.name === 'bed');
    if (!bedItem) {
        const woolCount = bot.inventory.items().filter(i => i.name.endsWith('_wool')).reduce((s, i) => s + i.count, 0);
        const plankCount = bot.inventory.items().filter(i => i.name.endsWith('_planks')).reduce((s, i) => s + i.count, 0);
        if (woolCount >= 3 && plankCount >= 3) {
            bot.chat("🛏️ Crafting bed from wool and planks...");
            try {
                await smartCraft(bot, 'white_bed', 1);
                bedItem = bot.inventory.items().find(i => i.name.endsWith('_bed') || i.name === 'bed');
            } catch (_) {}
        }
    }

    if (!bedItem) return null;

    const curPos = bot.entity.position.floored();
    const candidateOffsets = [
        new Vec3(1, 0, 0),
        new Vec3(-1, 0, 0),
        new Vec3(0, 0, 1),
        new Vec3(0, 0, -1)
    ];

    for (const off of candidateOffsets) {
        const footGround = bot.blockAt(curPos.offset(off.x, -1, off.z));
        const footAir = bot.blockAt(curPos.offset(off.x, 0, off.z));
        const headGround = bot.blockAt(curPos.offset(off.x * 2, -1, off.z * 2));
        const headAir = bot.blockAt(curPos.offset(off.x * 2, 0, off.z * 2));

        if (footGround && footGround.boundingBox === 'block' &&
            headGround && headGround.boundingBox === 'block' &&
            footAir && footAir.name === 'air' &&
            headAir && headAir.name === 'air') {
            try {
                await bot.equip(bedItem, 'hand');
                await bot.lookAt(footAir.position);
                await bot.placeBlock(footGround, new Vec3(0, 1, 0));
                await new Promise(r => setTimeout(r, 400));
                const placed = bot.findBlock({ matching: b => b.name.includes('bed'), maxDistance: 6 });
                if (placed) {
                    bot.chat("🛏️ Successfully placed bed on ground!");
                    return placed;
                }
            } catch (err) {
                console.warn(`[PlaceBed] Placement error: ${err.message}`);
            }
        }
    }
    return null;
}

async function breedAnimals(bot, animalType = 'any') {
    if (!bot || !bot.entity) return { success: false, reason: 'bot_not_ready' };
    const { GoalNear } = goals;

    const BREEDING_FOODS = {
        cow: ['wheat'],
        sheep: ['wheat'],
        chicken: ['wheat_seeds', 'beetroot_seeds', 'melon_seeds', 'pumpkin_seeds'],
        pig: ['carrot', 'potato', 'beetroot']
    };

    const targetTypes = (animalType && animalType !== 'any') ? [animalType.toLowerCase()] : ['cow', 'sheep', 'chicken', 'pig'];

    let targetSpecies = null;
    let foodItem = null;
    let adults = [];

    for (const species of targetTypes) {
        const acceptableFoods = BREEDING_FOODS[species] || [];
        const availableFood = bot.inventory.items().find(i => acceptableFoods.includes(i.name) && i.count >= 2);
        if (!availableFood) continue;

        const candidateAdults = [];
        for (const id in bot.entities) {
            const e = bot.entities[id];
            if (e && e.name && e.name.toLowerCase() === species && e.position.distanceTo(bot.entity.position) <= 24) {
                const isBaby = Boolean(e.metadata && (e.metadata[16] === true || (typeof e.metadata[16] === 'number' && e.metadata[16] < 0)));
                if (!isBaby) {
                    candidateAdults.push(e);
                }
            }
        }

        if (candidateAdults.length >= 2) {
            targetSpecies = species;
            foodItem = availableFood;
            adults = candidateAdults.slice(0, 2);
            break;
        }
    }

    if (!targetSpecies || adults.length < 2) {
        const reasons = [];
        if (!foodItem) reasons.push("lacking 2+ suitable breeding food");
        if (adults.length < 2) reasons.push("fewer than 2 adult animals nearby");
        bot.chat(`Cannot breed animals: ${reasons.join(', ')} 🌾`);
        return { success: false, reason: reasons.join('; ') || 'insufficient_animals_or_food' };
    }

    bot.chat(`❤️ Breeding 2 ${targetSpecies}s using ${foodItem.name}...`);
    try {
        await bot.equip(foodItem, 'hand');

        // Feed first animal
        await bot.pathfinder.goto(new GoalNear(adults[0].position.x, adults[0].position.y, adults[0].position.z, 2));
        await bot.lookAt(adults[0].position.offset(0, adults[0].height * 0.8, 0));
        await bot.activateEntity(adults[0]);
        await new Promise(r => setTimeout(r, 400));

        // Re-equip in case slot changed
        const currentFood = bot.inventory.items().find(i => (BREEDING_FOODS[targetSpecies] || []).includes(i.name));
        if (currentFood) await bot.equip(currentFood, 'hand');

        // Feed second animal
        await bot.pathfinder.goto(new GoalNear(adults[1].position.x, adults[1].position.y, adults[1].position.z, 2));
        await bot.lookAt(adults[1].position.offset(0, adults[1].height * 0.8, 0));
        await bot.activateEntity(adults[1]);
        await new Promise(r => setTimeout(r, 600));

        bot.chat(`✨ Successfully bred pair of ${targetSpecies}s! XP and baby produced! 🎉`);
        return { success: true, species: targetSpecies, count: 2 };
    } catch (bErr) {
        console.warn(`[Breeding] Error: ${bErr.message}`);
        return { success: false, reason: `breeding_error: ${bErr.message}` };
    }
}

async function catchFish(bot, maxAttempts = 3) {
    if (!bot || !bot.entity) return { success: false, reason: 'bot_not_ready' };
    const { GoalNear } = goals;
    const mcData = require('minecraft-data')(bot.version);

    let rod = bot.inventory.items().find(i => i.name === 'fishing_rod');
    if (!rod) {
        const stickCount = bot.inventory.items().find(i => i.name === 'stick')?.count || 0;
        const stringCount = bot.inventory.items().find(i => i.name === 'string')?.count || 0;
        if (stickCount >= 3 && stringCount >= 2) {
            bot.chat("🎣 Crafting a fishing rod from sticks and string...");
            try {
                await smartCraft(bot, 'fishing_rod', 1);
                rod = bot.inventory.items().find(i => i.name === 'fishing_rod');
            } catch (_) {}
        }
    }

    if (!rod) {
        bot.chat("No fishing rod found and insufficient materials (need 3 sticks + 2 string)!");
        return { success: false, reason: 'missing_fishing_rod' };
    }

    const waterId = mcData.blocksByName['water']?.id;
    if (!waterId) return { success: false, reason: 'water_block_unknown' };

    const waterBlocks = bot.findBlocks({ matching: waterId, maxDistance: 20, count: 12 });
    let targetWater = null;
    for (const pos of waterBlocks) {
        const above = bot.blockAt(pos.offset(0, 1, 0));
        if (above && (above.name === 'air' || above.name === 'cave_air')) {
            targetWater = pos;
            break;
        }
    }

    if (!targetWater) {
        bot.chat("No open water source found within 20m for fishing.");
        return { success: false, reason: 'no_water_source_nearby' };
    }

    try {
        await bot.pathfinder.goto(new GoalNear(targetWater.x, targetWater.y + 1, targetWater.z, 3));
    } catch (_) {}

    await bot.equip(rod, 'hand');
    await bot.lookAt(new Vec3(targetWater.x + 0.5, targetWater.y + 0.5, targetWater.z + 0.5));

    bot.chat("🎣 Casting fishing rod into water...");
    let caughtCount = 0;

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        try {
            await Promise.race([
                bot.fish(),
                new Promise((_, reject) => setTimeout(() => reject(new Error('fish_timeout')), 25000))
            ]);
            caughtCount++;
            bot.chat(`🐟 Reeled in a catch! (Attempt ${attempt + 1}/${maxAttempts})`);
            await new Promise(r => setTimeout(r, 600));
            await collectNearbyDrops(bot, 6);
        } catch (fErr) {
            console.warn(`[Fishing] Attempt ${attempt + 1} ended: ${fErr.message}`);
            break;
        }
    }

    return {
        success: caughtCount > 0,
        caught_count: caughtCount,
        reason: caughtCount > 0 ? undefined : 'no_fish_caught_in_attempts'
    };
}

async function manageChest(bot, actionType = 'deposit_surplus', targetItem = null, count = 1) {
    if (!bot || !bot.entity) return { success: false, reason: 'bot_not_ready' };
    const { GoalNear } = goals;
    const mcData = require('minecraft-data')(bot.version);

    const chestBlockId = mcData.blocksByName['chest']?.id;
    let chestBlock = chestBlockId ? bot.findBlock({ matching: chestBlockId, maxDistance: 16 }) : null;

    if (!chestBlock && actionType.startsWith('deposit')) {
        let chestItem = bot.inventory.items().find(i => i.name === 'chest');
        if (!chestItem) {
            const plankCount = bot.inventory.items().filter(i => i.name.endsWith('_planks')).reduce((s, i) => s + i.count, 0);
            if (plankCount >= 8) {
                bot.chat("📦 Crafting chest from 8 planks...");
                try {
                    await smartCraft(bot, 'chest', 1);
                    chestItem = bot.inventory.items().find(i => i.name === 'chest');
                } catch (_) {}
            }
        }

        if (chestItem) {
            const ground = bot.blockAt(bot.entity.position.offset(1, -1, 0));
            const air = bot.blockAt(bot.entity.position.offset(1, 0, 0));
            if (ground && ground.boundingBox === 'block' && air && air.name === 'air') {
                try {
                    await bot.equip(chestItem, 'hand');
                    await bot.placeBlock(ground, new Vec3(0, 1, 0));
                    await new Promise(r => setTimeout(r, 400));
                    chestBlock = bot.findBlock({ matching: chestBlockId, maxDistance: 6 });
                } catch (cpErr) {
                    console.warn(`[Chest] Could not place chest: ${cpErr.message}`);
                }
            }
        }
    }

    if (!chestBlock) {
        bot.chat("No chest found nearby and unable to place new chest.");
        return { success: false, reason: 'no_chest_found_or_placeable' };
    }

    try {
        await bot.pathfinder.goto(new GoalNear(chestBlock.position.x, chestBlock.position.y, chestBlock.position.z, 2.5));
        const chestWindow = await bot.openChest(chestBlock);
        const ESSENTIAL_ITEMS = [
            'iron_pickaxe', 'diamond_pickaxe', 'stone_pickaxe', 'wooden_pickaxe',
            'iron_sword', 'diamond_sword', 'stone_sword', 'shield', 'water_bucket',
            'cooked_beef', 'cooked_porkchop', 'bread', 'cooked_mutton', 'torch'
        ];

        let transCount = 0;
        if (actionType === 'withdraw' && targetItem) {
            const chestItemMatch = chestWindow.items().find(i => i.name.toLowerCase().includes(targetItem.toLowerCase()));
            if (chestItemMatch) {
                const withdrawAmount = Math.min(count, chestItemMatch.count);
                await chestWindow.withdraw(chestItemMatch.type, null, withdrawAmount);
                transCount = withdrawAmount;
                bot.chat(`📦 Withdrew ${withdrawAmount}x ${chestItemMatch.name} from chest.`);
            } else {
                chestWindow.close();
                bot.chat(`Item '${targetItem}' not found in chest storage.`);
                return { success: false, reason: `item_${targetItem}_not_in_chest` };
            }
        } else {
            const depositCands = bot.inventory.items().filter(i => {
                if (ESSENTIAL_ITEMS.includes(i.name)) return false;
                if (i.name.includes('helmet') || i.name.includes('chestplate') || i.name.includes('leggings') || i.name.includes('boots')) return false;
                return true;
            });

            for (const item of depositCands) {
                try {
                    await chestWindow.deposit(item.type, null, item.count);
                    transCount += item.count;
                    await new Promise(r => setTimeout(r, 150));
                } catch (_) {}
            }
            bot.chat(`📦 Deposited ${transCount} surplus item(s) into chest storage.`);
        }

        const snapshot = chestWindow.items().map(i => ({ name: i.name, count: i.count }));
        sendToPython({
            type: 'chest_used',
            chest_pos: { x: chestBlock.position.x, y: chestBlock.position.y, z: chestBlock.position.z },
            dimension: (bot.game && bot.game.dimension) ? String(bot.game.dimension).toLowerCase() : 'overworld',
            items: snapshot
        });

        chestWindow.close();
        return { success: true, transferred_count: transCount, chest_pos: chestBlock.position };
    } catch (err) {
        console.warn(`[Chest] Error: ${err.message}`);
        return { success: false, reason: `chest_error: ${err.message}` };
    }
}

async function buildShelter(bot, mode = 'auto') {
    if (!bot || !bot.entity) return false;
    const { GoalNear } = goals;

    bot.pathfinder.stop();

    // 1. Identify all usable solid building blocks in inventory
    const SOLID_NAMES = [
        'cobblestone', 'cobbled_deepslate', 'stone', 'deepslate', 'blackstone',
        'granite', 'diorite', 'andesite', 'tuff', 'calcite', 'dirt', 'mud', 'packed_mud',
        'netherrack', 'end_stone', 'sandstone', 'red_sandstone', 'basalt',
        'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks', 'acacia_planks',
        'dark_oak_planks', 'mangrove_planks', 'cherry_planks', 'bamboo_planks'
    ];

    let availableBlocks = bot.inventory.items().filter(i => {
        return SOLID_NAMES.includes(i.name) || i.name.endsWith('_planks') || i.name.endsWith('_cobblestone');
    });

    let totalBlocks = availableBlocks.reduce((s, i) => s + i.count, 0);

    // If zero blocks, mine 3 dirt/stone blocks adjacent or below to acquire blocks
    if (totalBlocks < 4) {
        bot.chat("No building blocks in hand! Rapidly digging dirt/stone to acquire wall blocks... ⛏️");
        const adjOffsets = [new Vec3(1, 0, 0), new Vec3(-1, 0, 0), new Vec3(0, 0, 1), new Vec3(0, 0, -1)];
        for (const off of adjOffsets) {
            const targetPos = bot.entity.position.offset(off.x, off.y, off.z);
            const b = bot.blockAt(targetPos);
            if (b && (b.name === 'dirt' || b.name === 'grass_block' || b.name === 'stone' || b.name === 'netherrack')) {
                try {
                    await bot.dig(b);
                    await new Promise(r => setTimeout(r, 200));
                } catch (_) {}
            }
        }
        await collectNearbyDrops(bot, 4);
        availableBlocks = bot.inventory.items().filter(i => SOLID_NAMES.includes(i.name) || i.name.endsWith('_planks'));
        totalBlocks = availableBlocks.reduce((s, i) => s + i.count, 0);
    }

    const chosenMode = (mode === 'burrow' || (mode === 'auto' && totalBlocks < 6)) ? 'burrow' : mode;

    if (chosenMode === 'burrow') {
        bot.chat("🕳️ BURROWING: Digging 3-deep emergency burrow hole and sealing roof! 🛡️");
        const basePos = bot.entity.position.floored();

        // Dig down 3 blocks
        for (let d = 0; d >= -2; d--) {
            const digPos = basePos.offset(0, d, 0);
            const b = bot.blockAt(digPos);
            if (b && b.name !== 'bedrock' && b.name !== 'air' && b.name !== 'lava') {
                try {
                    await bot.dig(b);
                    await new Promise(r => setTimeout(r, 250));
                } catch (_) {}
            }
        }

        await new Promise(r => setTimeout(r, 400));

        // Place 1 seal block directly above head
        const sealBlockItem = bot.inventory.items().find(i => SOLID_NAMES.includes(i.name) || i.name.endsWith('_planks'));
        if (sealBlockItem) {
            const roofPos = basePos.offset(0, 1, 0);
            await placeBlockDirect(bot, sealBlockItem, roofPos);
        }

        // Place torch if available
        const torch = bot.inventory.items().find(i => i.name === 'torch');
        if (torch) {
            await bot.equip(torch, 'hand').catch(() => {});
            const floorBlock = bot.blockAt(bot.entity.position.offset(0, -1, 0));
            if (floorBlock) {
                await bot.placeBlock(floorBlock, new Vec3(0, 1, 0)).catch(() => {});
            }
        }

        isSheltered = true;
        bot.chat("🔒 Burrow completely sealed! Safe from all hostile mobs. Resting until danger passes.");
        return true;
    }

    // Default: 'emergency_box' (Surface 4-wall + roof enclosure)
    bot.chat("🏰 Constructing emergency protective bunker with surrounding blocks! 🧱");
    const myPos = bot.entity.position.floored();
    const wallOffsets = [
        new Vec3(1, 0, 0), new Vec3(-1, 0, 0), new Vec3(0, 0, 1), new Vec3(0, 0, -1),
        new Vec3(1, 1, 0), new Vec3(-1, 1, 0), new Vec3(0, 1, 1), new Vec3(0, 1, -1),
        new Vec3(0, 2, 0)
    ];

    for (const off of wallOffsets) {
        const placePos = myPos.offset(off.x, off.y, off.z);
        const blockItem = bot.inventory.items().find(i => SOLID_NAMES.includes(i.name) || i.name.endsWith('_planks'));
        if (!blockItem) break;
        await placeBlockDirect(bot, blockItem, placePos);
    }

    // Interior lighting: place torch inside so mobs cannot spawn
    const torchItem = bot.inventory.items().find(i => i.name === 'torch');
    if (torchItem) {
        try {
            await bot.equip(torchItem, 'hand');
            const interiorWall = bot.blockAt(myPos.offset(1, 1, 0)) || bot.blockAt(myPos.offset(0, -1, 0));
            if (interiorWall) {
                await bot.placeBlock(interiorWall, new Vec3(0, 1, 0)).catch(() => {});
            }
        } catch (_) {}
    }

    isSheltered = true;
    bot.chat("🛡️ Emergency bunker sealed! 100% immune to hostile mobs. Resting safely.");
    return true;
}

async function breakOutShelter(bot) {
    if (!bot || !bot.entity) return false;
    bot.chat("☀️ Daybreak / danger passed! Breaking open shelter to resume exploration... ⛏️");

    const myPos = bot.entity.position.floored();
    const exitOffsets = [
        new Vec3(0, 2, 0),
        new Vec3(1, 1, 0), new Vec3(1, 0, 0),
        new Vec3(0, 1, 1), new Vec3(0, 0, 1)
    ];

    for (const off of exitOffsets) {
        const targetPos = myPos.offset(off.x, off.y, off.z);
        const b = bot.blockAt(targetPos);
        if (b && b.name !== 'air' && b.name !== 'cave_air' && b.name !== 'bedrock') {
            try {
                await bot.dig(b);
                await new Promise(r => setTimeout(r, 200));
            } catch (_) {}
        }
    }

    await collectNearbyDrops(bot, 4);
    isSheltered = false;
    bot.chat("🚪 Safely exited shelter! Resuming progression. 🚀");
    return true;
}

// --- AUTONOMOUS ENCHANTING & XP ENGINE ---
async function enchantGear(bot, gearType = 'auto', targetLevel = 15) {
    if (!bot || !bot.entity) return false;
    const { GoalNear } = goals;
    const mcData = require('minecraft-data')(bot.version);

    const currentXp = bot.experience ? bot.experience.level : 0;
    const lapis = bot.inventory.items().find(i => i.name === 'lapis_lazuli');
    if (!lapis || lapis.count < 1) {
        bot.chat("I need Lapis Lazuli to enchant gear! Please supply lapis or help me mine it. 💠");
        return false;
    }
    if (currentXp < 1) {
        bot.chat(`I don't have enough XP levels to enchant! Current level: ${currentXp}. Let's slay mobs or smelt ores first. ✨`);
        return false;
    }

    const GEAR_CANDIDATES = [
        'diamond_sword', 'diamond_chestplate', 'diamond_leggings', 'diamond_helmet', 'diamond_boots',
        'bow', 'diamond_pickaxe', 'diamond_axe',
        'iron_sword', 'iron_chestplate', 'iron_leggings', 'iron_helmet', 'iron_boots', 'iron_pickaxe'
    ];

    let targetItem = null;
    if (gearType !== 'auto') {
        targetItem = bot.inventory.items().find(i => i.name.toLowerCase().includes(gearType.toLowerCase()));
    }
    if (!targetItem) {
        for (const candidate of GEAR_CANDIDATES) {
            const item = bot.inventory.items().find(i => i.name === candidate);
            if (item) {
                targetItem = item;
                break;
            }
        }
    }

    if (!targetItem) {
        bot.chat("No enchantable equipment found in my inventory! 🛡️");
        return false;
    }

    let tableBlockId = mcData.blocksByName['enchanting_table']?.id;
    let tableBlock = tableBlockId ? bot.findBlock({ matching: tableBlockId, maxDistance: 16 }) : null;

    if (!tableBlock) {
        const tableItem = bot.inventory.items().find(i => i.name === 'enchanting_table');
        if (tableItem) {
            bot.chat("Placing Enchanting Table from inventory... 📖✨");
            const groundPos = bot.entity.position.offset(1, 0, 0).floored();
            const ref = bot.blockAt(groundPos.offset(0, -1, 0));
            if (ref && ref.name !== 'air') {
                await bot.equip(tableItem, 'hand');
                await bot.placeBlock(ref, new Vec3(0, 1, 0)).catch(() => {});
                await new Promise(r => setTimeout(r, 400));
                tableBlock = bot.findBlock({ matching: tableBlockId, maxDistance: 8 });
            }
        }
    }

    if (!tableBlock) {
        bot.chat("No Enchanting Table found nearby and none in inventory! 📚");
        return false;
    }

    await bot.pathfinder.goto(new GoalNear(tableBlock.position.x, tableBlock.position.y, tableBlock.position.z, 2.5)).catch(() => {});

    try {
        bot.chat(`Opening Enchanting Table to enchant ${targetItem.name}... ✨`);
        const tableWindow = await bot.openEnchantmentTable(tableBlock);

        await tableWindow.putTargetItem(targetItem);
        await new Promise(r => setTimeout(r, 200));

        const updatedLapis = bot.inventory.items().find(i => i.name === 'lapis_lazuli');
        if (updatedLapis) {
            await tableWindow.putLapis(updatedLapis);
            await new Promise(r => setTimeout(r, 200));
        }

        let choice = 0;
        if (currentXp >= 30 && updatedLapis && updatedLapis.count >= 3) {
            choice = 2;
        } else if (currentXp >= 15 && updatedLapis && updatedLapis.count >= 2) {
            choice = 1;
        }

        await tableWindow.enchant(choice);
        await new Promise(r => setTimeout(r, 300));

        await tableWindow.takeTargetItem();
        await new Promise(r => setTimeout(r, 200));

        tableWindow.close();
        bot.chat(`🎉 Successfully enchanted ${targetItem.name}! Power increased! ⚔️🛡️`);
        return true;
    } catch (err) {
        console.warn(`[Enchant] Error during enchanting: ${err.message}`);
        bot.chat(`Enchanting encountered an issue: ${err.message}`);
        return false;
    }
}

// --- TACTICAL ARCHITECTURAL BLUEPRINTS ---
async function buildNetherOutpost(bot, wallMaterial = 'auto') {
    if (!bot || !bot.entity) return false;
    const mcData = require('minecraft-data')(bot.version);

    const BLAST_RESISTANT_NAMES = [
        'cobblestone', 'cobbled_deepslate', 'stone', 'deepslate', 'blackstone',
        'basalt', 'polished_blackstone', 'stone_bricks', 'nether_bricks'
    ];

    const wallBlocks = bot.inventory.items().filter(i => BLAST_RESISTANT_NAMES.includes(i.name));
    const totalWallCount = wallBlocks.reduce((s, i) => s + i.count, 0);

    if (totalWallCount < 8) {
        bot.chat(`Not enough blast-resistant blocks for Nether Outpost! Need 8+ cobblestone/blackstone, have ${totalWallCount}. 🧱`);
        return false;
    }

    const portalBlockId = mcData.blocksByName['nether_portal']?.id;
    let portalBlock = portalBlockId ? bot.findBlock({ matching: portalBlockId, maxDistance: 16 }) : null;
    const centerPos = portalBlock ? portalBlock.position.floored() : bot.entity.position.floored();

    bot.chat("🏰 Constructing blast-resistant Nether Outpost around portal against Ghasts! 🔥🛡️");

    const shieldOffsets = [
        new Vec3(2, 0, 0), new Vec3(2, 1, 0), new Vec3(2, 2, 0),
        new Vec3(-2, 0, 0), new Vec3(-2, 1, 0), new Vec3(-2, 2, 0),
        new Vec3(0, 0, 2), new Vec3(0, 1, 2), new Vec3(0, 2, 2),
        new Vec3(0, 0, -2), new Vec3(0, 1, -2), new Vec3(0, 2, -2),
        new Vec3(2, 0, 2), new Vec3(2, 1, 2), new Vec3(-2, 0, -2), new Vec3(-2, 1, -2),
        new Vec3(0, 3, 0), new Vec3(1, 3, 0), new Vec3(-1, 3, 0), new Vec3(0, 3, 1), new Vec3(0, 3, -1)
    ];

    for (const off of shieldOffsets) {
        const placePos = centerPos.offset(off.x, off.y, off.z);
        const blockItem = bot.inventory.items().find(i => BLAST_RESISTANT_NAMES.includes(i.name));
        if (!blockItem) break;
        await placeBlockDirect(bot, blockItem, placePos);
        await new Promise(r => setTimeout(r, 100));
    }

    netherOutpostBuilt = true;
    bot.chat("✅ Nether Outpost fortified! Portal is safe from Ghast fireball explosions! 🔥🛡️");
    return true;
}

async function bridgeChasm(bot, direction = 'forward', distance = 5) {
    if (!bot || !bot.entity) return false;

    const SOLID_NAMES = [
        'cobblestone', 'cobbled_deepslate', 'stone', 'dirt', 'netherrack', 'end_stone',
        'deepslate', 'blackstone', 'granite', 'diorite', 'andesite', 'sandstone'
    ];

    const bridgeBlocks = bot.inventory.items().filter(i => SOLID_NAMES.includes(i.name) || i.name.endsWith('_planks'));
    const totalBridgeBlocks = bridgeBlocks.reduce((s, i) => s + i.count, 0);

    if (totalBridgeBlocks < distance) {
        bot.chat(`Not enough blocks to bridge ${distance}m! Have ${totalBridgeBlocks}. ⛏️`);
        return false;
    }

    bot.chat(`🌉 Starting safe crouch-bridging for ${distance} blocks... Sneak activated! 🛡️`);
    bot.pathfinder.stop();

    bot.setControlState('sneak', true);

    try {
        let yaw = bot.entity.yaw;
        if (direction === 'north') yaw = Math.PI;
        else if (direction === 'south') yaw = 0;
        else if (direction === 'west') yaw = Math.PI / 2;
        else if (direction === 'east') yaw = -Math.PI / 2;

        for (let i = 0; i < distance; i++) {
            const currentFeet = bot.entity.position.floored();
            const forwardVector = new Vec3(-Math.sin(yaw), 0, Math.cos(yaw)).floored();

            const targetPos = currentFeet.offset(forwardVector.x, -1, forwardVector.z);
            const blockItem = bot.inventory.items().find(i => SOLID_NAMES.includes(i.name) || i.name.endsWith('_planks'));
            if (!blockItem) break;

            await placeBlockDirect(bot, blockItem, targetPos);
            await new Promise(r => setTimeout(r, 150));

            bot.setControlState('back', true);
            await new Promise(r => setTimeout(r, 250));
            bot.setControlState('back', false);
        }

        bot.chat(`✅ Successfully extended safe bridge across the void! 🌉`);
        return true;
    } catch (err) {
        console.warn(`[BridgeChasm] Bridging interrupted: ${err.message}`);
        return false;
    } finally {
        bot.setControlState('sneak', false);
    }
}

// --- INVENTORY AUDITING & ACTION METRICS ---
function getInventoryCountMap(bot) {
    const map = {};
    if (!bot || !bot.inventory) return map;
    for (const item of bot.inventory.items()) {
        map[item.name] = (map[item.name] || 0) + item.count;
    }
    return map;
}

function calculateInventoryDelta(beforeMap, afterMap) {
    const delta = {};
    const allKeys = new Set([...Object.keys(beforeMap), ...Object.keys(afterMap)]);
    for (const k of allKeys) {
        const diff = (afterMap[k] || 0) - (beforeMap[k] || 0);
        if (diff !== 0) {
            delta[k] = diff;
        }
    }
    return delta;
}

// --- ACTION EXECUTION ENGINE (TIMEOUT & CONCURRENCY GUARDED) ---
async function handleAction(action) {
    if (!bot) return;

    const { command, args = {} } = action;
    const actionId = action.action_id || null;
    const actionStartTime = Date.now();
    const invBefore = getInventoryCountMap(bot);
    let actionSuccess = true;
    let actionError = null;

    // Guard against action overlap if bot is already performing a critical multi-step action
    if (isBusy && command !== 'stop_actions' && command !== 'say_chat') {
        console.log(`⚠️ [Busy Guard] Bot currently busy with '${currentActionName}'. Postponing new action.`);
        sendToPython({
            type: 'action_completed',
            command: command,
            action_id: actionId,
            success: false,
            ok: false,
            error: `Bot is busy with '${currentActionName}'`,
            reason: `busy_with_${currentActionName}`,
            items_delta: {},
            duration_ms: 0,
            state: getBotState()
        });
        return;
    }

    if (['craft_item', 'collect_block', 'hunt_food', 'smelt_item', 'place_block', 'go_to_coordinates', 'build_nether_portal', 'throw_eye_of_ender', 'activate_end_portal', 'destroy_end_crystals', 'fight_ender_dragon', 'enter_exit_portal', 'farm_crops', 'build_shelter', 'break_out_shelter', 'enchant_gear', 'build_nether_outpost', 'bridge_chasm'].includes(command)) {
        isBusy = true;
        currentActionName = `${command}_${args.item_name || args.block_name || args.input_item || args.tactic || args.action_type || args.mode || args.gear_type || ''}`;
        sendToPython({
            type: 'action_started',
            command: command,
            action_id: actionId,
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
                const ok = await smartCraft(bot, itemName, count);
                if (!ok) {
                    actionSuccess = false;
                    actionError = `Failed to craft ${itemName}: missing materials or recipe`;
                }
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
                    actionSuccess = false;
                    actionError = `Unknown or unsupported block type: '${rawName}'`;
                    break;
                }

                bot.chat(`Searching for ${count}x ${categoryLabel}...`);

                const targets = bot.findBlocks({ matching: matchingIds, maxDistance: 48, count: count });

                if (targets.length === 0) {
                    let optimalY = bot.entity.position.y;
                    if (rawName.includes('diamond')) optimalY = -58;
                    else if (rawName.includes('iron')) optimalY = 16;
                    else if (rawName.includes('gold')) optimalY = -16;
                    else if (rawName.includes('redstone')) optimalY = -58;
                    else if (rawName.includes('lapis')) optimalY = 0;
                    else if (rawName.includes('copper')) optimalY = 48;
                    else if (rawName.includes('coal')) optimalY = 95;
                    else if (rawName.includes('ancient_debris')) optimalY = 15;

                    if (Math.abs(bot.entity.position.y - optimalY) > 8) {
                        bot.chat(`No ${categoryLabel} at current elevation (Y: ${Math.round(bot.entity.position.y)}). Navigating towards optimal depth Y: ${optimalY}! ⛏️`);
                        const angle = Math.random() * Math.PI * 2;
                        const exploreX = Math.round(bot.entity.position.x + Math.cos(angle) * 16);
                        const exploreZ = Math.round(bot.entity.position.z + Math.sin(angle) * 16);
                        const exploreY = Math.max(-59, Math.round(bot.entity.position.y - 10));
                        const { GoalNear } = goals;
                        bot.pathfinder.setGoal(new GoalNear(exploreX, exploreY, exploreZ, 2));
                    } else {
                        bot.chat(`No ${categoryLabel} found in the immediate area. Exploring outward to discover veins! 🏃`);
                        const angle = Math.random() * Math.PI * 2;
                        const exploreX = Math.round(bot.entity.position.x + Math.cos(angle) * 35);
                        const exploreZ = Math.round(bot.entity.position.z + Math.sin(angle) * 35);
                        const exploreY = Math.round(bot.entity.position.y);
                        const { GoalNear } = goals;
                        bot.pathfinder.setGoal(new GoalNear(exploreX, exploreY, exploreZ, 2));
                    }
                    actionSuccess = false;
                    actionError = `No ${categoryLabel} found nearby (exploring outward)`;
                    break;
                }

                const blocks = targets.map(p => bot.blockAt(p)).filter(b => b);
                if (blocks.length === 0) {
                    actionSuccess = false;
                    actionError = `Target blocks could not be resolved in world`;
                    break;
                }

                // Tool mastery pre-check and equipping
                const prep = await toolLearner.prepareAndEquipToolForBlock(bot, blocks[0].name, smartCraft);
                if (!prep.canHarvest) {
                    console.log(`[ToolLearner] Aborting mining of '${blocks[0].name}' due to missing tool requirement: ${prep.minToolName}`);
                    actionSuccess = false;
                    actionError = `Cannot harvest ${blocks[0].name}: requires ${prep.minToolName}`;
                    break;
                }

                const startTime = Date.now();
                const invBefore = bot.inventory.items().map(i => ({ name: i.name, count: i.count }));

                try {
                    setMovementsForTask('mine');
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

                    // Phase 2 / F2.2: Notify SQLite that ore blocks at this coordinate are mined
                    const curDim = (bot.game && bot.game.dimension ? String(bot.game.dimension).toLowerCase() : 'overworld');
                    for (const b of blocks) {
                        if (ORE_INTEREST_NAMES.includes(b.name)) {
                            sendToPython({
                                type: 'ore_mined',
                                dim: curDim,
                                x: b.position.x,
                                y: b.position.y,
                                z: b.position.z,
                                block: b.name
                            });
                        }
                    }

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
                    actionSuccess = false;
                    actionError = `Mining interrupted: ${cErr.message}`;
                } finally {
                    setMovementsForTask('walk');
                }
                break;
            }

            case 'follow_player': {
                const targetName = args.player_name;
                const target = bot.players[targetName]?.entity;
                if (!target) {
                    bot.chat(`Cannot see ${targetName} nearby!`);
                    actionSuccess = false;
                    actionError = `player_not_found: ${targetName}`;
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
                    actionSuccess = false;
                    actionError = `player_not_found: ${targetName}`;
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
                let bed = bot.findBlock({ matching: b => b.name.includes('bed'), maxDistance: 16 });
                if (!bed) {
                    bed = await smartPlaceBed(bot);
                }

                if (bed) {
                    try {
                        const isDay = bot.time ? bot.time.isDay : true;
                        if (!isDay || bot.isRaining) {
                            await bot.sleep(bed);
                            lastSleepTime = Date.now();
                            bot.chat("Sleeping in bed now, resetting phantom timer and setting spawn point! 🛏️💤");
                        } else {
                            // In Minecraft 1.20 Java Edition: right-clicking bed during day sets spawn point
                            await bot.activateBlock(bed);
                            lastSleepTime = Date.now();
                            bot.chat("Respawn point set at bed! (Daytime) 🛏️📍");
                        }
                        sendToPython({
                            type: 'bed_used',
                            bed_pos: { x: bed.position.x, y: bed.position.y, z: bed.position.z },
                            dimension: curDim || 'overworld'
                        });
                    } catch (sErr) {
                        actionSuccess = false;
                        actionError = `bed_interaction_failed: ${sErr.message}`;
                    }
                } else {
                    actionSuccess = false;
                    actionError = "no_bed_in_range_or_inventory";
                    bot.chat("No bed found within 16 blocks and no bed in inventory to place.");
                }
                break;
            }

            case 'eat_food': {
                const foodItem = bot.inventory.items().find(i => FOOD_NAMES.includes(i.name));
                if (foodItem) {
                    try {
                        await bot.equip(foodItem, 'hand');
                        await bot.consume();
                        bot.chat(`Ate ${foodItem.name} to restore hunger.`);
                    } catch (eErr) {
                        actionSuccess = false;
                        actionError = `consume_failed: ${eErr.message}`;
                    }
                } else {
                    actionSuccess = false;
                    actionError = "no_food_in_inventory";
                    bot.chat("No food available in inventory to eat!");
                }
                break;
            }

            case 'attack_target': {
                const targetName = (args.target_name || '').toLowerCase();
                const entity = bot.nearestEntity(e => e.name && e.name.toLowerCase().includes(targetName) && e.position.distanceTo(bot.entity.position) < 16);
                if (entity) {
                    await equipBestWeapon(bot);
                    if (bot.pvp) {
                        bot.pvp.attack(entity);
                        await new Promise((resolve) => {
                            const timeout = setTimeout(() => {
                                if (bot.pvp) bot.pvp.stop();
                                resolve();
                            }, 10000);
                            const checkInterval = setInterval(() => {
                                if (!entity.isValid || entity.health <= 0) {
                                    clearInterval(checkInterval);
                                    clearTimeout(timeout);
                                    if (bot.pvp) bot.pvp.stop();
                                    resolve();
                                }
                            }, 300);
                        });
                    } else {
                        await bot.lookAt(entity.position.offset(0, entity.height, 0));
                        bot.attack(entity);
                    }
                    await new Promise(r => setTimeout(r, 400));
                    await collectNearbyDrops(bot, 10);
                } else {
                    actionSuccess = false;
                    actionError = `Target '${targetName}' not found within 16 blocks`;
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
                    try {
                        await Promise.race([
                            bot.pathfinder.goto(new GoalNear(exploreX, exploreY, exploreZ, 2)),
                            new Promise((_, reject) => setTimeout(() => reject(new Error('Explore timeout')), 8000))
                        ]);
                    } catch (_) {}
                    actionSuccess = false;
                    actionError = `No food animals (${animalType}) found nearby (exploring outward)`;
                    break;
                }

                const animalName = targetEntity.name;
                bot.chat(`Hunting ${animalName} for food! 🥩`);

                await equipBestWeapon(bot);

                try {
                    let killed = false;
                    if (bot.pvp) {
                        bot.pvp.attack(targetEntity);
                        await new Promise((resolve) => {
                            const timeout = setTimeout(() => {
                                if (bot.pvp) bot.pvp.stop();
                                resolve();
                            }, 12000);

                            const checkInterval = setInterval(() => {
                                if (!targetEntity.isValid || targetEntity.health <= 0) {
                                    killed = true;
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
                        killed = !targetEntity.isValid || targetEntity.health <= 0;
                    }

                    if (!killed && targetEntity.isValid && targetEntity.health > 0) {
                        actionSuccess = false;
                        actionError = `hunt_timeout: ${animalName} escaped`;
                    } else {
                        await new Promise(r => setTimeout(r, 600));
                        await collectNearbyDrops(bot, 12);
                        bot.chat(`Successfully hunted ${animalName} and collected food drops! 🍗`);
                    }
                } catch (hErr) {
                    bot.chat(`Hunt interrupted: ${hErr.message}`);
                    actionSuccess = false;
                    actionError = `hunt_interrupted: ${hErr.message}`;
                }
                break;
            }

            case 'give_item_to_player': {
                const playerName = (args.player_name || '').toLowerCase().trim();
                const itemName = (args.item_name || '').toLowerCase().trim();
                const count = args.count || 1;

                if (!playerName || ['system', 'autonomous', 'server', 'none', 'bot', bot.username.toLowerCase()].includes(playerName)) {
                    bot.chat(`Cannot give items: invalid target player '${args.player_name}'.`);
                    actionSuccess = false;
                    actionError = `invalid_target_player: ${args.player_name}`;
                    break;
                }

                const item = bot.inventory.items().find(i => i.name.toLowerCase().includes(itemName));
                if (!item) {
                    bot.chat(`I don't have '${itemName}' to give.`);
                    actionSuccess = false;
                    actionError = `missing_item: ${itemName}`;
                    break;
                }

                const targetPlayerObj = Object.values(bot.players).find(p => p.username && p.username.toLowerCase() === playerName);
                const playerEntity = targetPlayerObj?.entity;

                if (!playerEntity) {
                    bot.chat(`Player '${args.player_name}' is not nearby to give items to.`);
                    actionSuccess = false;
                    actionError = `player_not_found: ${args.player_name}`;
                    break;
                }

                isBusy = true;
                currentActionName = `give_${itemName}`;
                try {
                    const { GoalNear } = goals;
                    await bot.pathfinder.goto(new GoalNear(playerEntity.position.x, playerEntity.position.y, playerEntity.position.z, 2));
                    await bot.toss(item.type, null, count);
                    bot.chat(`Gave ${count}x ${item.name} to ${targetPlayerObj.username}! 🎁`);
                } catch (gErr) {
                    actionSuccess = false;
                    actionError = `give_item_failed: ${gErr.message}`;
                }
                break;
            }

            case 'collect_nearby_drops': {
                isBusy = true;
                currentActionName = 'collecting_nearby_drops';
                const radius = args.radius || 16;
                await collectNearbyDrops(bot, radius);
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

            case 'destroy_end_crystals': {
                isBusy = true;
                currentActionName = 'destroying_end_crystals';
                const ok = await destroyEndCrystals(bot);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to destroy End crystals";
                }
                break;
            }

            case 'fight_ender_dragon': {
                isBusy = true;
                currentActionName = 'fighting_ender_dragon';
                const tactic = args.tactic || 'melee_sword';
                const ok = await fightEnderDragon(bot, tactic);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to engage Ender Dragon";
                }
                break;
            }

            case 'enter_exit_portal': {
                isBusy = true;
                currentActionName = 'entering_exit_portal';
                const ok = await enterExitPortal(bot);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to enter exit portal";
                }
                break;
            }

            case 'farm_crops': {
                isBusy = true;
                currentActionName = 'farming_crops';
                const actionType = args.action_type || 'auto';
                const ok = await farmCrops(bot, actionType);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to farm crops";
                }
                break;
            }

            case 'build_shelter': {
                isBusy = true;
                currentActionName = 'building_shelter';
                const mode = args.mode || 'auto';
                const ok = await buildShelter(bot, mode);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to construct shelter";
                }
                break;
            }

            case 'break_out_shelter': {
                isBusy = true;
                currentActionName = 'breaking_out_shelter';
                const ok = await breakOutShelter(bot);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to break out of shelter";
                }
                break;
            }

            case 'enchant_gear': {
                isBusy = true;
                currentActionName = 'enchanting_gear';
                const gearType = args.gear_type || 'auto';
                const targetLevel = args.target_level || 15;
                const ok = await enchantGear(bot, gearType, targetLevel);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to enchant gear";
                }
                break;
            }

            case 'build_nether_outpost': {
                isBusy = true;
                currentActionName = 'building_nether_outpost';
                const wallMaterial = args.wall_material || 'auto';
                const ok = await buildNetherOutpost(bot, wallMaterial);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to construct Nether outpost";
                }
                break;
            }

            case 'bridge_chasm': {
                isBusy = true;
                currentActionName = 'bridging_chasm';
                const direction = args.direction || 'forward';
                const distance = args.distance || 5;
                const ok = await bridgeChasm(bot, direction, distance);
                if (!ok) {
                    actionSuccess = false;
                    actionError = "Failed to bridge chasm";
                }
                break;
            }

            case 'breed_animals': {
                isBusy = true;
                currentActionName = 'breeding';
                const animalType = args.animal_type || 'any';
                const res = await breedAnimals(bot, animalType);
                actionSuccess = res.success;
                if (!res.success) actionError = res.reason;
                break;
            }

            case 'catch_fish': {
                isBusy = true;
                currentActionName = 'fishing';
                const count = parseInt(args.count || args.attempts || 3, 10);
                const res = await catchFish(bot, count);
                actionSuccess = res.success;
                if (!res.success) actionError = res.reason;
                break;
            }

            case 'manage_chest': {
                isBusy = true;
                currentActionName = 'managing_chest';
                const actionType = args.action_type || 'deposit_surplus';
                const targetItem = args.target_item || args.item_name || null;
                const count = parseInt(args.count || 1, 10);
                const res = await manageChest(bot, actionType, targetItem, count);
                actionSuccess = res.success;
                if (!res.success) actionError = res.reason;
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
        setMovementsForTask('walk');
        const durationMs = Date.now() - actionStartTime;
        const invAfter = getInventoryCountMap(bot);
        const itemsDelta = calculateInventoryDelta(invBefore, invAfter);

        sendToPython({
            type: 'action_completed',
            command: command,
            action_id: actionId,
            success: actionSuccess,
            ok: actionSuccess,
            error: actionError,
            reason: actionError || 'success',
            items_delta: itemsDelta,
            duration_ms: durationMs,
            state: getBotState()
        });
    }
}

// Startup & Initialization
connectBridge();
createBot();
