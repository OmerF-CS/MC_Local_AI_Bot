/**
 * Minecraft Universal Knowledge & Registry Exporter
 * Extracts ALL official items, blocks, recipes, and utilities directly from minecraft-data.
 */
const fs = require('fs');
const path = require('path');
const mcData = require('minecraft-data')('1.20.4') || require('minecraft-data')('1.20.1');

console.log('[DataExporter] Extracting official Minecraft component registry...');

const registry = {
    items: {},
    blocks: {},
    recipes: {},
    foods: {},
    biomes: {},
    mobs: {}
};

// 1. Process All Items
for (const item of mcData.itemsArray) {
    registry.items[item.name] = {
        id: item.id,
        displayName: item.displayName,
        stackSize: item.stackSize,
        category: categorizeItem(item.name)
    };
}

// 2. Process All Blocks (Harvest levels, hardness, drops)
for (const block of mcData.blocksArray) {
    registry.blocks[block.name] = {
        id: block.id,
        displayName: block.displayName,
        hardness: block.hardness,
        diggable: block.diggable,
        material: block.material || 'stone',
        harvestTools: block.harvestTools ? Object.keys(block.harvestTools) : []
    };
}

// 3. Process All Foods & Nutritional Values
for (const food of mcData.foodsArray) {
    registry.foods[food.name] = {
        foodPoints: food.foodPoints,
        saturation: food.saturation
    };
}

// 4. Process All Mobs / Entities
for (const entity of mcData.entitiesArray) {
    if (entity.type === 'mob' || entity.type === 'hostile' || entity.type === 'passive') {
        registry.mobs[entity.name] = {
            displayName: entity.displayName,
            type: entity.type,
            category: entity.category
        };
    }
}

function categorizeItem(name) {
    if (name.includes('pickaxe') || name.includes('axe') || name.includes('shovel') || name.includes('hoe')) return 'tool';
    if (name.includes('sword') || name.includes('bow') || name.includes('shield') || name.includes('helmet') || name.includes('chestplate') || name.includes('leggings') || name.includes('boots')) return 'combat';
    if (name.includes('ore') || name.includes('raw_') || name.includes('ingot') || name.includes('diamond') || name.includes('nugget')) return 'mineral';
    if (name.includes('log') || name.includes('wood') || name.includes('planks') || name.includes('slab') || name.includes('stairs')) return 'building';
    if (name.includes('redstone') || name.includes('piston') || name.includes('repeater') || name.includes('comparator') || name.includes('hopper')) return 'redstone';
    if (name.includes('potion') || name.includes('brew') || name.includes('wart') || name.includes('powder')) return 'alchemy';
    return 'misc';
}

const outputPath = path.join(__dirname, '..', 'data', 'minecraft_knowledge_graph.json');
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(registry, null, 2), 'utf8');

console.log(`[DataExporter] ✅ Successfully exported ${Object.keys(registry.items).length} items and ${Object.keys(registry.blocks).length} blocks to: ${outputPath}`);
