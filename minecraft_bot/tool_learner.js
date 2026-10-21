/**
 * Tool Mastery & Adaptive Learning Engine
 * Determines correct harvesting tools, enforces tier restrictions, and logs mining experiences.
 */
const fs = require('fs');
const path = require('path');

const TOOL_TIERS = {
    wooden_pickaxe: 1,
    golden_pickaxe: 1,
    stone_pickaxe: 2,
    iron_pickaxe: 3,
    diamond_pickaxe: 4,
    netherite_pickaxe: 5,

    wooden_axe: 1,
    golden_axe: 1,
    stone_axe: 2,
    iron_axe: 3,
    diamond_axe: 4,
    netherite_axe: 5,

    wooden_shovel: 1,
    golden_shovel: 1,
    stone_shovel: 2,
    iron_shovel: 3,
    diamond_shovel: 4,
    netherite_shovel: 5,

    wooden_hoe: 1,
    golden_hoe: 1,
    stone_hoe: 2,
    iron_hoe: 3,
    diamond_hoe: 4,
    netherite_hoe: 5,

    wooden_sword: 1,
    golden_sword: 1,
    stone_sword: 2,
    iron_sword: 3,
    diamond_sword: 4,
    netherite_sword: 5,

    shears: 2,
    flint_and_steel: 2,
    fishing_rod: 2,
    bucket: 2,
    water_bucket: 3,
    lava_bucket: 3,
    shield: 3,
    bow: 3,
    crossbow: 4,
    trident: 5
};

const CORE_TOOL_CATEGORIES = ['pickaxe', 'axe', 'shovel', 'hoe', 'sword'];
const UTILITY_TOOL_NAMES = [
    'shield', 'water_bucket', 'bucket', 'lava_bucket',
    'shears', 'flint_and_steel', 'fishing_rod', 'bow', 'crossbow'
];

const MEMORY_FILE = path.resolve(__dirname, '../data/tool_learning_memory.json');

function analyzeBlockHarvest(botVersion, blockName) {
    const mcData = require('minecraft-data')(botVersion);
    const b = mcData.blocksByName[blockName];
    if (!b) return null;

    const validTools = [];
    if (b.harvestTools) {
        for (const id in b.harvestTools) {
            if (mcData.items[id]) validTools.push(mcData.items[id].name);
        }
    }

    let minTier = 0;
    let minToolName = 'hand';
    if (validTools.length > 0) {
        let lowestTier = 99;
        for (const t of validTools) {
            const tier = TOOL_TIERS[t] || 99;
            if (tier < lowestTier) {
                lowestTier = tier;
                minToolName = t;
            }
        }
        minTier = lowestTier;
    }

    // Determine optimal tool from harvestTools
    let optimalCategory = 'hand';
    if (b.harvestTools) {
        const toolIds = Object.keys(b.harvestTools).map(id => {
            const item = mcData.items[parseInt(id)];
            return item ? item.name : '';
        });
        if (toolIds.some(n => n.includes('pickaxe'))) optimalCategory = 'pickaxe';
        else if (toolIds.some(n => n.includes('axe'))) optimalCategory = 'axe';
        else if (toolIds.some(n => n.includes('shovel'))) optimalCategory = 'shovel';
        else if (toolIds.some(n => n.includes('hoe'))) optimalCategory = 'hoe';
        else if (toolIds.some(n => n.includes('shears'))) optimalCategory = 'shears';
    } else if (['hay_block', 'sponge', 'wet_sponge', 'sculk', 'target', 'shroomlight', 'moss_block'].some(h => blockName.includes(h)) || blockName.includes('wart_block')) {
        optimalCategory = 'hoe';
    } else if (blockName.includes('wool') || blockName.includes('leaves') || blockName === 'cobweb') {
        optimalCategory = 'shears';
    } else if (b.material) {
        // Fallback to material-based heuristic
        if (['rock', 'stone', 'metal', 'iron', 'ore'].some(m => b.material.includes(m))) optimalCategory = 'pickaxe';
        else if (['wood', 'plant'].some(m => b.material.includes(m))) optimalCategory = 'axe';
        else if (['dirt', 'sand', 'clay', 'gravel'].some(m => b.material.includes(m))) optimalCategory = 'shovel';
    }

    return {
        name: blockName,
        displayName: b.displayName,
        hardness: b.hardness,
        material: b.material,
        requiresTool: validTools.length > 0,
        minTier: minTier,
        minToolName: minToolName,
        optimalCategory: optimalCategory,
        validTools: validTools
    };
}

function getToolRemainingUses(item) {
    if (!item || !item.maxDurability) return Infinity;
    return Math.max(0, item.maxDurability - (item.durabilityUsed || 0));
}

function getBestToolInInventory(bot, validToolNames = null, preferredCategory = null) {
    if (!bot || !bot.inventory) return null;

    const items = bot.inventory.items();
    let bestItem = null;
    let highestScore = -1;

    for (const item of items) {
        const name = item.name;
        const tier = TOOL_TIERS[name] || 0;
        const remUses = getToolRemainingUses(item);
        // GP-6: Deprioritize tools about to shatter (<= 3 uses left) when a healthy tool is available
        const score = (remUses <= 3) ? (tier * 0.1) : tier;

        if (validToolNames && validToolNames.length > 0) {
            if (validToolNames.includes(name) && score > highestScore) {
                highestScore = score;
                bestItem = item;
            }
        } else if (preferredCategory) {
            if (name.includes(preferredCategory) && score > highestScore) {
                highestScore = score;
                bestItem = item;
            }
        }
    }

    return bestItem;
}

function getCarriedToolsSummary(bot) {
    if (!bot || !bot.inventory) return 'None';
    const tools = bot.inventory.items().filter(i => TOOL_TIERS[i.name]);
    if (tools.length === 0) return 'None (bare hands only)';
    return tools.map(t => `${t.name} (x${t.count})`).join(', ');
}

function getFullToolBaseStatus(bot) {
    const emptyStatus = {
        core_tools: {
            pickaxe: { best: null, tier: 0, durability_pct: 0, count: 0 },
            axe: { best: null, tier: 0, durability_pct: 0, count: 0 },
            shovel: { best: null, tier: 0, durability_pct: 0, count: 0 },
            hoe: { best: null, tier: 0, durability_pct: 0, count: 0 },
            sword: { best: null, tier: 0, durability_pct: 0, count: 0 }
        },
        utility_tools: {
            shield: false,
            water_bucket: false,
            bucket: false,
            lava_bucket: false,
            shears: false,
            flint_and_steel: false,
            fishing_rod: false,
            bow: false,
            crossbow: false,
            arrows: 0
        },
        missing_core_tools: [...CORE_TOOL_CATEGORIES],
        missing_utility_tools: ['shield', 'water_bucket', 'shears', 'flint_and_steel'],
        critically_damaged_tools: [],
        completeness_pct: 0
    };
    if (!bot || !bot.inventory || typeof bot.inventory.items !== 'function') return emptyStatus;

    const items = bot.inventory.items();
    const offhandItem = (bot.inventory.slots && bot.inventory.slots[45]) ? bot.inventory.slots[45] : null;
    const allItems = offhandItem ? [...items, offhandItem] : items;

    const criticallyDamaged = [];
    for (const item of allItems) {
        if (item && item.maxDurability) {
            const rem = getToolRemainingUses(item);
            const pct = Math.round((rem / item.maxDurability) * 100);
            if (rem <= 10 || pct <= 10) {
                criticallyDamaged.push({ name: item.name, remaining_uses: rem, durability_pct: pct });
            }
        }
    }

    const coreTools = {};
    for (const cat of CORE_TOOL_CATEGORIES) {
        const matching = allItems.filter(i => i && i.name && i.name.endsWith(`_${cat}`));
        let bestItem = null;
        let bestTier = 0;
        for (const m of matching) {
            const t = TOOL_TIERS[m.name] || 0;
            if (t > bestTier) {
                bestTier = t;
                bestItem = m;
            }
        }
        let durPct = 100;
        if (bestItem && bestItem.maxDurability) {
            const rem = Math.max(0, bestItem.maxDurability - (bestItem.durabilityUsed || 0));
            durPct = Math.round((rem / bestItem.maxDurability) * 100);
        }
        coreTools[cat] = {
            best: bestItem ? bestItem.name : null,
            tier: bestTier,
            durability_pct: bestItem ? durPct : 0,
            count: matching.reduce((s, i) => s + (i.count || 1), 0)
        };
    }

    const hasName = (nm) => allItems.some(i => i && i.name === nm);
    const arrowCount = allItems
        .filter(i => i && i.name && i.name.includes('arrow'))
        .reduce((s, i) => s + (i.count || 0), 0);

    const utilityTools = {
        shield: hasName('shield'),
        water_bucket: hasName('water_bucket'),
        bucket: hasName('bucket'),
        lava_bucket: hasName('lava_bucket'),
        shears: hasName('shears'),
        flint_and_steel: hasName('flint_and_steel'),
        fishing_rod: hasName('fishing_rod'),
        bow: hasName('bow'),
        crossbow: hasName('crossbow'),
        arrows: arrowCount
    };

    const missingCore = CORE_TOOL_CATEGORIES.filter(c => !coreTools[c].best);
    const keyUtilities = ['shield', 'water_bucket', 'shears', 'flint_and_steel'];
    const missingUtil = keyUtilities.filter(u => !utilityTools[u]);
    const totalTargets = CORE_TOOL_CATEGORIES.length + keyUtilities.length;
    const presentCount = (CORE_TOOL_CATEGORIES.length - missingCore.length) + (keyUtilities.length - missingUtil.length);

    return {
        core_tools: coreTools,
        utility_tools: utilityTools,
        missing_core_tools: missingCore,
        missing_utility_tools: missingUtil,
        critically_damaged_tools: criticallyDamaged,
        completeness_pct: Math.round((presentCount / totalTargets) * 100)
    };
}

async function prepareAndEquipToolForBlock(bot, blockName, smartCraftFn) {
    const analysis = analyzeBlockHarvest(bot.version, blockName);
    if (!analysis) {
        return { canHarvest: true, toolEquipped: 'hand' };
    }

    // 1. Blocks requiring specific tools to drop (Stone, Ores, Obsidian)
    if (analysis.requiresTool) {
        let tool = getBestToolInInventory(bot, analysis.validTools);

        if (tool) {
            await bot.equip(tool, 'hand').catch(() => {});
            return { canHarvest: true, toolEquipped: tool.name };
        }

        // Tool missing! Check if bot can autonomously craft it
        if (typeof smartCraftFn === 'function') {
            if (analysis.minToolName === 'wooden_pickaxe') {
                bot.chat("⛏️ Harvesting stone requires a wooden pickaxe! Crafting one first...");
                const crafted = await smartCraftFn(bot, 'wooden_pickaxe', 1);
                if (crafted) {
                    tool = getBestToolInInventory(bot, analysis.validTools);
                    if (tool) {
                        await bot.equip(tool, 'hand').catch(() => {});
                        return { canHarvest: true, toolEquipped: tool.name };
                    }
                }
            } else if (analysis.minToolName === 'stone_pickaxe') {
                const cobbleCount = bot.inventory.items().filter(i => 
                    ['cobblestone', 'cobbled_deepslate', 'blackstone'].includes(i.name)
                ).reduce((s, i) => s + i.count, 0);

                if (cobbleCount >= 3) {
                    bot.chat("⛏️ Harvesting iron/copper/lapis ore requires a stone pickaxe! Crafting one first...");
                    const crafted = await smartCraftFn(bot, 'stone_pickaxe', 1);
                    if (crafted) {
                        tool = getBestToolInInventory(bot, analysis.validTools);
                        if (tool) {
                            await bot.equip(tool, 'hand').catch(() => {});
                            return { canHarvest: true, toolEquipped: tool.name };
                        }
                    }
                }
            } else if (analysis.minToolName === 'iron_pickaxe') {
                const ironCount = bot.inventory.items().filter(i => i.name === 'iron_ingot').reduce((s, i) => s + i.count, 0);
                if (ironCount >= 3) {
                    bot.chat("⛏️ Harvesting precious ore requires an iron pickaxe! Crafting one first...");
                    const crafted = await smartCraftFn(bot, 'iron_pickaxe', 1);
                    if (crafted) {
                        tool = getBestToolInInventory(bot, analysis.validTools);
                        if (tool) {
                            await bot.equip(tool, 'hand').catch(() => {});
                            return { canHarvest: true, toolEquipped: tool.name };
                        }
                    }
                }
            } else if (analysis.minToolName === 'diamond_pickaxe') {
                const diamondCount = bot.inventory.items().filter(i => i.name === 'diamond').reduce((s, i) => s + i.count, 0);
                if (diamondCount >= 3) {
                    bot.chat("⛏️ Harvesting obsidian/ancient debris requires a diamond pickaxe! Crafting one first...");
                    const crafted = await smartCraftFn(bot, 'diamond_pickaxe', 1);
                    if (crafted) {
                        tool = getBestToolInInventory(bot, analysis.validTools);
                        if (tool) {
                            await bot.equip(tool, 'hand').catch(() => {});
                            return { canHarvest: true, toolEquipped: tool.name };
                        }
                    }
                }
            }
        }

        // Could not obtain tool: ABORT MINING to prevent destroying resource without drops!
        bot.chat(`⚠️ Cannot harvest ${blockName}! It requires at least a ${analysis.minToolName} to drop items. I must get a ${analysis.minToolName} first.`);
        return {
            canHarvest: false,
            reason: 'missing_tool',
            minToolName: analysis.minToolName
        };
    }

    // 2. Blocks that drop without tools (Wood, Dirt, Sand, Hay, Leaves), but break faster with optimal tool
    if (analysis.optimalCategory === 'axe') {
        const axe = getBestToolInInventory(bot, null, 'axe');
        if (axe) await bot.equip(axe, 'hand').catch(() => {});
    } else if (analysis.optimalCategory === 'shovel') {
        const shovel = getBestToolInInventory(bot, null, 'shovel');
        if (shovel) await bot.equip(shovel, 'hand').catch(() => {});
    } else if (analysis.optimalCategory === 'hoe') {
        const hoe = getBestToolInInventory(bot, null, 'hoe');
        if (hoe) await bot.equip(hoe, 'hand').catch(() => {});
    } else if (analysis.optimalCategory === 'shears') {
        const shears = getBestToolInInventory(bot, ['shears'], null);
        if (shears) await bot.equip(shears, 'hand').catch(() => {});
    }

    return {
        canHarvest: true,
        toolEquipped: bot.heldItem ? bot.heldItem.name : 'hand'
    };
}

let _memoryCache = null;
let _memorySaveTimer = null;
function _debouncedSaveMemory() {
    if (_memorySaveTimer) clearTimeout(_memorySaveTimer);
    _memorySaveTimer = setTimeout(() => {
        if (_memoryCache) {
            const fs = require('fs');
            fs.writeFile(MEMORY_FILE, JSON.stringify(_memoryCache, null, 2), (err) => {
                if (err) console.log(`[ToolLearner] Memory save error: ${err.message}`);
            });
        }
    }, 10000); // Save at most every 10 seconds
}

function recordExperience(blockName, toolUsed, durationMs, success, itemsGained = []) {
    try {
        if (!_memoryCache) {
            if (fs.existsSync(MEMORY_FILE)) {
                _memoryCache = JSON.parse(fs.readFileSync(MEMORY_FILE, 'utf8'));
            } else {
                _memoryCache = { experiences: [], learned_lessons: [] };
            }
        }
        
        let memory = _memoryCache;

        const lesson = success 
            ? `Successfully harvested '${blockName}' using '${toolUsed}' in ${(durationMs / 1000).toFixed(1)}s (Obtained: ${itemsGained.join(', ') || 'item'}).`
            : `Attempted to mine '${blockName}' with '${toolUsed}', but failed to drop items! Lesson: Use higher tier tool.`;

        memory.experiences.push({
            timestamp: new Date().toISOString(),
            block: blockName,
            tool_used: toolUsed,
            duration_ms: durationMs,
            success: success,
            items_gained: itemsGained
        });

        if (!memory.learned_lessons.includes(lesson)) {
            memory.learned_lessons.push(lesson);
        }

        // Limit memory history to 50 entries
        if (memory.experiences.length > 50) {
            memory.experiences = memory.experiences.slice(-50);
        }

        _debouncedSaveMemory();
        return lesson;
    } catch (err) {
        console.warn(`[ToolLearner] Error recording experience: ${err.message}`);
        return null;
    }
}

module.exports = {
    TOOL_TIERS,
    CORE_TOOL_CATEGORIES,
    UTILITY_TOOL_NAMES,
    analyzeBlockHarvest,
    getBestToolInInventory,
    getCarriedToolsSummary,
    getFullToolBaseStatus,
    prepareAndEquipToolForBlock,
    recordExperience
};
