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

    wooden_sword: 1,
    golden_sword: 1,
    stone_sword: 2,
    iron_sword: 3,
    diamond_sword: 4,
    netherite_sword: 5
};

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

    let optimalCategory = 'hand';
    if (b.material) {
        if (b.material.includes('pickaxe')) optimalCategory = 'pickaxe';
        else if (b.material.includes('axe')) optimalCategory = 'axe';
        else if (b.material.includes('shovel')) optimalCategory = 'shovel';
        else if (b.material.includes('hoe')) optimalCategory = 'hoe';
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

function getBestToolInInventory(bot, validToolNames = null, preferredCategory = null) {
    if (!bot || !bot.inventory) return null;

    const items = bot.inventory.items();
    let bestItem = null;
    let highestTier = -1;

    for (const item of items) {
        const name = item.name;
        const tier = TOOL_TIERS[name] || 0;

        if (validToolNames && validToolNames.length > 0) {
            if (validToolNames.includes(name) && tier > highestTier) {
                highestTier = tier;
                bestItem = item;
            }
        } else if (preferredCategory) {
            if (name.includes(preferredCategory) && tier > highestTier) {
                highestTier = tier;
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
                    bot.chat("⛏️ Harvesting iron ore requires a stone pickaxe! Crafting one first...");
                    const crafted = await smartCraftFn(bot, 'stone_pickaxe', 1);
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

    // 2. Blocks that drop without tools (Wood, Dirt, Sand), but break faster with optimal tool
    if (analysis.optimalCategory === 'axe') {
        const axe = getBestToolInInventory(bot, null, 'axe');
        if (axe) await bot.equip(axe, 'hand').catch(() => {});
    } else if (analysis.optimalCategory === 'shovel') {
        const shovel = getBestToolInInventory(bot, null, 'shovel');
        if (shovel) await bot.equip(shovel, 'hand').catch(() => {});
    }

    return {
        canHarvest: true,
        toolEquipped: bot.heldItem ? bot.heldItem.name : 'hand'
    };
}

function recordExperience(blockName, toolUsed, durationMs, success, itemsGained = []) {
    try {
        let memory = { experiences: [], learned_lessons: [] };
        if (fs.existsSync(MEMORY_FILE)) {
            memory = JSON.parse(fs.readFileSync(MEMORY_FILE, 'utf8'));
        }

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

        fs.writeFileSync(MEMORY_FILE, JSON.stringify(memory, null, 2), 'utf8');
        return lesson;
    } catch (err) {
        console.warn(`[ToolLearner] Error recording experience: ${err.message}`);
        return null;
    }
}

module.exports = {
    TOOL_TIERS,
    analyzeBlockHarvest,
    getBestToolInInventory,
    getCarriedToolsSummary,
    prepareAndEquipToolForBlock,
    recordExperience
};
