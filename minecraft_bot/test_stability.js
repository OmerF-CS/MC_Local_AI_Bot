/**
 * Unit Behavioral Tests for Mineflayer Worker Stability (F0 / F0-R1)
 * Runs mock-based unit tests without needing a live Minecraft server.
 */
const assert = require('assert');
const { spawnSync } = require('child_process');
const path = require('path');
const { Vec3 } = require('vec3');

const botModule = require('./bot');
const {
    autoSelfDefenseCheck,
    handleAction,
    handleFatalProcessError,
    setBotInstance,
    setSendToPythonOverride,
    getConsecutiveProcessErrors,
    resetConsecutiveProcessErrors,
    verifyAndRepairBunker,
    getDefenseRetreatState,
    resetDefenseRetreatState,
    farmCrops,
    autoEatCheck,
    getBotState
} = botModule;

let passedTests = 0;
let totalTests = 0;

function runTest(testName, testFn) {
    totalTests++;
    try {
        const res = testFn();
        if (res && typeof res.then === 'function') {
            return res.then(() => {
                passedTests++;
                console.log(`  ✅ PASS: ${testName}`);
            }).catch((err) => {
                console.error(`  ❌ FAIL: ${testName} ->`, err.message);
                throw err;
            });
        } else {
            passedTests++;
            console.log(`  ✅ PASS: ${testName}`);
        }
    } catch (err) {
        console.error(`  ❌ FAIL: ${testName} ->`, err.message);
        throw err;
    }
}

async function runAllTests() {
    console.log("=================================================");
    console.log("🧪 Running Mineflayer Worker Stability Tests (F0)");
    console.log("=================================================");

    // ------------------------------------------------------------------
    // TEST SUITE 1: autoSelfDefenseCheck Null Safety Guards (F0-2 / F0-R1)
    // ------------------------------------------------------------------
    console.log("\n[Suite 1] autoSelfDefenseCheck Null Guards (F0-2 / F0-R1):");

    await runTest("autoSelfDefenseCheck: bot is null -> does not throw", async () => {
        setBotInstance(null);
        await autoSelfDefenseCheck();
    });

    await runTest("autoSelfDefenseCheck: bot.entity is null -> does not throw", async () => {
        setBotInstance({ entity: null, entities: {} });
        await autoSelfDefenseCheck();
    });

    await runTest("autoSelfDefenseCheck: bot.entity.position is null -> does not throw", async () => {
        setBotInstance({ entity: { position: null }, entities: {} });
        await autoSelfDefenseCheck();
    });

    await runTest("autoSelfDefenseCheck: hostile mob with null position -> does not throw", async () => {
        const mockBot = {
            entity: {
                position: {
                    x: 0, y: 64, z: 0,
                    distanceTo: () => 5.0,
                    minus: () => ({ normalize: () => ({ scaled: () => ({ x: 0, y: 0, z: 0 }) }) }),
                    plus: () => ({ x: 0, y: 64, z: 0 }),
                    offset: () => ({ x: 0, y: 64, z: 0 })
                },
                yaw: 0, pitch: 0
            },
            entities: {
                '101': { name: 'zombie', position: null }, // Null position on hostile
                '102': { name: 'skeleton', position: undefined }
            },
            inventory: { items: () => [], slots: {} },
            health: 20
        };
        setBotInstance(mockBot);
        await autoSelfDefenseCheck();
    });

    // ------------------------------------------------------------------
    // TEST SUITE 2: Immediate bot_not_ready Return When Disconnected (F0-4 / F0-R1)
    // ------------------------------------------------------------------
    console.log("\n[Suite 2] Immediate bot_not_ready When Worker Not Ready / Connected (F0-4 / F0-R1):");

    await runTest("handleAction: when bot is not spawned -> returns bot_not_ready immediately (<50ms)", async () => {
        setBotInstance(null); // Bot is not connected or spawned
        const t0 = Date.now();

        const actionPromise = handleAction({
            command: 'collect_block',
            args: { block_name: 'stone', count: 3 },
            action_id: 'test_action_001'
        });

        await actionPromise;
        const elapsedMs = Date.now() - t0;

        assert.ok(elapsedMs < 100, `Execution took ${elapsedMs}ms, should be immediate (<100ms) without 60s timeout`);
    });

    await runTest("Python Bridge Contract: send_action_and_wait without connected worker returns bot_not_ready immediately", () => {
        const pythonCode = `
import asyncio, time
from core.bridge import MinecraftBridge

async def check():
    bridge = MinecraftBridge(host="127.0.0.1", port=8777)
    # Bridge has no connected clients
    t0 = time.time()
    res = await bridge.send_action_and_wait("collect_block", {"block_name": "wood"}, timeout=35.0)
    elapsed = time.time() - t0
    assert elapsed < 0.2, f"Took {elapsed}s, expected < 0.2s"
    assert res.get("error") == "bot_not_ready", f"Unexpected error: {res}"
    assert res.get("reason") == "bot_not_ready", f"Unexpected reason: {res}"
    print("BRIDGE_OK")

asyncio.run(check())
`;
        const pyProc = spawnSync("python", ["-c", pythonCode], {
            cwd: path.resolve(__dirname, '..'),
            encoding: 'utf-8'
        });

        assert.strictEqual(pyProc.status, 0, `Python test failed: ${pyProc.stderr || pyProc.stdout}`);
        assert.ok(pyProc.stdout.includes("BRIDGE_OK"), `Python output missing BRIDGE_OK: ${pyProc.stdout}`);
    });

    // ------------------------------------------------------------------
    // TEST SUITE 3: Honest smelt_item failure when raw_iron missing (F0-6 / F0-R1)
    // ------------------------------------------------------------------
    console.log("\n[Suite 3] Honest smelt_item Failure When Materials Missing (F0-6 / F0-R1):");

    await runTest("smelt_item: raw_iron missing from inventory -> returns success = false and populated error", async () => {
        let sentMessage = null;
        setSendToPythonOverride((payload) => {
            if (payload && payload.type === 'action_completed') {
                sentMessage = payload;
            }
        });

        const mockBot = {
            version: '1.20.4',
            entity: {
                position: { x: 0, y: 64, z: 0 }
            },
            inventory: {
                items: () => [{ name: 'cobblestone', count: 16 }] // No raw_iron!
            },
            chat: () => {}
        };
        setBotInstance(mockBot);

        await handleAction({
            command: 'smelt_item',
            args: { input_item: 'raw_iron', count: 1 },
            action_id: 'test_smelt_action_001'
        });

        // Reset override
        setSendToPythonOverride(null);

        assert.ok(sentMessage !== null, "Expected action_completed payload to be sent to Python");
        assert.strictEqual(sentMessage.success, false, "Expected success to be false when raw_iron is missing");
        assert.strictEqual(sentMessage.ok, false, "Expected ok to be false when raw_iron is missing");
        assert.ok(sentMessage.error && sentMessage.error.length > 0, "Expected error message to be populated");
        assert.ok(sentMessage.error.includes("raw_iron"), `Expected error mentioning raw_iron, got: ${sentMessage.error}`);
    });

    // ------------------------------------------------------------------
    // TEST SUITE 4: Fatal Error Crash Guard (3-strike clean exit) (F0-3 / F0-R2)
    // ------------------------------------------------------------------
    console.log("\n[Suite 4] Fatal Error Crash Guard (3 strikes before exit) (F0-3 / F0-R2):");

    await runTest("handleFatalProcessError: first 2 errors do not exit; 3rd error triggers clean process.exit(1)", () => {
        resetConsecutiveProcessErrors();
        let exitCalledWith = null;
        const originalExit = process.exit;
        process.exit = (code) => { exitCalledWith = code; };

        try {
            // 1st error: should not exit
            handleFatalProcessError('TestError', new Error('Fail 1'));
            assert.strictEqual(getConsecutiveProcessErrors(), 1);
            assert.strictEqual(exitCalledWith, null, "1st error should not exit process");

            // 2nd error: should not exit
            handleFatalProcessError('TestError', new Error('Fail 2'));
            assert.strictEqual(getConsecutiveProcessErrors(), 2);
            assert.strictEqual(exitCalledWith, null, "2nd error should not exit process");

            // 3rd error: should call process.exit(1)
            handleFatalProcessError('TestError', new Error('Fail 3'));
            assert.strictEqual(getConsecutiveProcessErrors(), 3);
            assert.strictEqual(exitCalledWith, 1, "3rd error must call process.exit(1)");
        } finally {
            process.exit = originalExit;
            resetConsecutiveProcessErrors();
        }
    });

    // ------------------------------------------------------------------
    // TEST SUITE 5: "Retreating" Throttle (F1-3)
    // ------------------------------------------------------------------
    console.log("\n[Suite 5] Retreating Log Throttle & Escape Guards (F1-3):");

    await runTest("autoSelfDefenseCheck: throttles Retreating log for same threat state to 15s interval", async () => {
        resetDefenseRetreatState();
        let logOutput = [];
        const originalLog = console.log;
        console.log = (...args) => {
            logOutput.push(args.join(' '));
            originalLog(...args);
        };

        try {
            const mockBot = {
                entity: {
                    position: {
                        x: 0, y: 64, z: 0,
                        distanceTo: () => 4.0,
                        minus: () => ({ normalize: () => ({ scaled: () => ({ x: 0, y: 0, z: 0 }) }) }),
                        plus: () => ({ x: 0, y: 64, z: 0 }),
                        floored: () => ({
                            x: 0, y: 64, z: 0,
                            plus: (d) => ({ x: d.x, y: 64 + d.y, z: d.z, offset: (ox, oy, oz) => ({ x: d.x + ox, y: 64 + oy, z: d.z + oz }) })
                        })
                    },
                    yaw: 0, pitch: 0
                },
                entities: {
                    '101': { id: 101, name: 'zombie', position: { x: 3, y: 64, z: 0, distanceTo: () => 4.0 } }
                },
                pathfinder: { setGoal: () => {} },
                pvp: { stop: () => {} },
                inventory: { items: () => [], slots: {} },
                blockAt: () => ({ boundingBox: 'empty', name: 'air' }),
                health: 4 // Critical health <= 6
            };
            setBotInstance(mockBot);

            // 1st check: should trigger retreat and log
            await autoSelfDefenseCheck();
            const firstRetreatCount = logOutput.filter(l => l.includes("Retreating...")).length;
            assert.strictEqual(firstRetreatCount, 1, "First retreat must log 'Retreating...'");

            // Immediate 2nd check with identical threat: must NOT log 'Retreating...' again (throttled)
            await autoSelfDefenseCheck();
            const secondRetreatCount = logOutput.filter(l => l.includes("Retreating...")).length;
            assert.strictEqual(secondRetreatCount, 1, "Subsequent check within 15s must NOT log 'Retreating...' again");
        } finally {
            console.log = originalLog;
            resetDefenseRetreatState();
        }
    });

    await runTest("autoSelfDefenseCheck: trapped bot marks cannotEscape and avoids repeated retreat attempts", async () => {
        resetDefenseRetreatState();
        try {
            const mockBot = {
                entity: {
                    position: {
                        x: 0, y: 64, z: 0,
                        distanceTo: () => 3.0,
                        minus: () => ({ normalize: () => ({ scaled: () => ({ x: 0, y: 0, z: 0 }) }) }),
                        plus: () => ({ x: 0, y: 64, z: 0 }),
                        floored: () => ({
                            x: 0, y: 64, z: 0,
                            plus: (d) => ({ x: d.x, y: 64, z: d.z, offset: () => ({ x: d.x, y: 65, z: d.z }) })
                        })
                    },
                    yaw: 0, pitch: 0
                },
                entities: {
                    '102': { id: 102, name: 'skeleton', position: { x: 2, y: 64, z: 0, distanceTo: () => 3.0 } }
                },
                pathfinder: { setGoal: () => {} },
                pvp: { stop: () => {} },
                inventory: { items: () => [], slots: {} },
                // Trapped by solid blocks on all sides:
                blockAt: () => ({ boundingBox: 'block', name: 'stone' }),
                health: 5
            };
            setBotInstance(mockBot);

            await autoSelfDefenseCheck();
            const retreatState = getDefenseRetreatState();
            assert.strictEqual(retreatState.lastRetreatCannotEscape, true, "Trapped bot should have lastRetreatCannotEscape = true");
        } finally {
            resetDefenseRetreatState();
        }
    });

    // ------------------------------------------------------------------
    // TEST SUITE 6: Bunker Verification & Repair (F1-4)
    // ------------------------------------------------------------------
    console.log("\n[Suite 6] Bunker Verification & Auto-Repair (F1-4):");

    await runTest("verifyAndRepairBunker: detects missing wall/roof block and places repair block", async () => {
        const placedBlocks = [];
        const mockBot = {
            entity: {
                position: new Vec3(10, 64, 10)
            },
            inventory: {
                items: () => [{ name: 'cobblestone', count: 5 }]
            },
            equip: async () => {},
            placeBlock: async (refBlock, faceVec) => {
                placedBlocks.push({ ref: refBlock, face: faceVec });
            },
            blockAt: (pos) => {
                // If pos is (+1, 0, 0) relative to bot: pretend it's air (gap) initially, unless already repaired
                if (pos.x === 11 && pos.y === 64 && pos.z === 10) {
                    if (placedBlocks.length > 0) return { name: 'cobblestone', boundingBox: 'block' };
                    return { name: 'air', boundingBox: 'empty' };
                }
                return { name: 'cobblestone', boundingBox: 'block' };
            }
        };

        const result = await verifyAndRepairBunker(mockBot);
        assert.ok(result.gaps >= 1, "Expected at least 1 gap to be detected");
        assert.ok(result.repaired >= 1, "Expected at least 1 gap to be successfully repaired");
        assert.strictEqual(result.sealed, true, "Expected bunker to be sealed after repair");
    });

    await runTest("verifyAndRepairBunker: 100% sealed bunker reports sealed=true and 0 gaps", async () => {
        const mockBot = {
            entity: {
                position: {
                    x: 0, y: 64, z: 0,
                    floored: () => new Vec3(0, 64, 0)
                }
            },
            inventory: { items: () => [] },
            blockAt: () => ({ name: 'cobblestone', boundingBox: 'block' })
        };

        const result = await verifyAndRepairBunker(mockBot);
        assert.strictEqual(result.gaps, 0, "Sealed bunker should have 0 gaps");
        assert.strictEqual(result.sealed, true, "Sealed bunker should have sealed=true");
    });

    await runTest("verifyAndRepairBunker: partial repair (remaining gaps > 0) reports sealed=false and remaining count", async () => {
        const placedBlocks = [];
        const mockBot = {
            entity: { position: new Vec3(20, 64, 20) },
            inventory: {
                items: () => [{ name: 'cobblestone', count: 1 }] // Only 1 block to repair 2 gaps
            },
            equip: async () => {},
            placeBlock: async (refBlock, faceVec) => {
                placedBlocks.push({ ref: refBlock, face: faceVec });
            },
            blockAt: (pos) => {
                // Gap 1 at (21, 64, 20) gets repaired
                if (pos.x === 21 && pos.y === 64 && pos.z === 20) {
                    if (placedBlocks.length > 0) return { name: 'cobblestone', boundingBox: 'block' };
                    return { name: 'air', boundingBox: 'empty' };
                }
                // Gap 2 at (19, 64, 20) remains open (no materials)
                if (pos.x === 19 && pos.y === 64 && pos.z === 20) {
                    return { name: 'air', boundingBox: 'empty' };
                }
                return { name: 'cobblestone', boundingBox: 'block' };
            }
        };

        const result = await verifyAndRepairBunker(mockBot);
        assert.strictEqual(result.sealed, false, "Partial repair must report sealed=false");
        assert.strictEqual(result.remaining, 1, "Must report remaining=1");
        assert.strictEqual(result.repaired, 1, "Must report repaired=1");
    });

    // ------------------------------------------------------------------
    // TEST SUITE 7: Eat & Eat Food Action Handling (F1-1)
    // ------------------------------------------------------------------
    console.log("\n[Suite 7] Eat & Eat Food Action Handling (F1-1):");

    await runTest("handleAction: 'eat' equips and consumes food from inventory", async () => {
        let consumed = false;
        let equippedItem = null;
        const mockBot = {
            entity: { position: { x: 0, y: 64, z: 0 } },
            inventory: {
                items: () => [{ name: 'bread', count: 3 }]
            },
            equip: async (item, slot) => { equippedItem = item.name; },
            consume: async () => { consumed = true; },
            chat: () => {},
            pathfinder: { stop: () => {} }
        };
        setBotInstance(mockBot);

        let sentResult = null;
        setSendToPythonOverride((payload) => {
            if (payload.type === 'action_completed') sentResult = payload;
        });

        try {
            await handleAction({ command: 'eat', args: {}, action_id: 'test_eat_1' });
            assert.strictEqual(equippedItem, 'bread', "Expected bread to be equipped");
            assert.strictEqual(consumed, true, "Expected bot.consume() to be called");
            assert.ok(sentResult !== null, "Expected action_completed result");
            assert.strictEqual(sentResult.success, true);
        } finally {
            setSendToPythonOverride(null);
        }
    });

    await runTest("handleAction: 'eat_food' returns error when no food in inventory", async () => {
        const mockBot = {
            entity: { position: { x: 0, y: 64, z: 0 } },
            inventory: {
                items: () => [{ name: 'dirt', count: 10 }] // No food
            },
            chat: () => {},
            pathfinder: { stop: () => {} }
        };
        setBotInstance(mockBot);

        let sentResult = null;
        setSendToPythonOverride((payload) => {
            if (payload.type === 'action_completed') sentResult = payload;
        });

        try {
            await handleAction({ command: 'eat_food', args: {}, action_id: 'test_eat_2' });
            assert.ok(sentResult !== null, "Expected action_completed result");
            assert.strictEqual(sentResult.success, false, "Expected failure when no food");
            assert.strictEqual(sentResult.error, "no_food_in_inventory");
        } finally {
            setSendToPythonOverride(null);
        }
    });

    console.log("\n[Suite 8] Kick/End Reason Logging (F1-7):");
    const { formatDisconnectReason } = botModule;

    await runTest("formatDisconnectReason: empty/undefined/null reason -> 'unknown'", () => {
        assert.strictEqual(formatDisconnectReason(undefined), 'unknown');
        assert.strictEqual(formatDisconnectReason(null), 'unknown');
        assert.strictEqual(formatDisconnectReason(''), 'unknown');
        assert.strictEqual(formatDisconnectReason({}), 'unknown');
    });

    await runTest("formatDisconnectReason: plain string, JSON chat string and chat component -> single-line text", () => {
        assert.strictEqual(formatDisconnectReason('socketClosed'), 'socketClosed');
        assert.strictEqual(formatDisconnectReason('{"text":"Server closed"}'), 'Server closed');
        assert.strictEqual(
            formatDisconnectReason({ text: 'You have been ', extra: [{ text: 'idle' }, { text: '\n too long' }] }),
            'You have been idle too long'
        );
    });

    await runTest("formatDisconnectReason: 1.20.4 NBT-style kick reason -> plain text (no [object Object])", () => {
        const nbtReason = {
            type: 'compound',
            value: { translate: { type: 'string', value: 'multiplayer.disconnect.kicked' } }
        };
        const out = formatDisconnectReason(nbtReason);
        assert.strictEqual(out, 'multiplayer.disconnect.kicked');
        assert.ok(!out.includes('[object Object]'));
    });

    // ------------------------------------------------------------------
    // TEST SUITE 9: Honest Action Outcomes (F1 Close Fixes)
    // ------------------------------------------------------------------
    console.log("\n[Suite 9] Honest Action Outcomes (farm_crops & go_to_coordinates):");

    await runTest("farm_crops: returns success=false and reason=no_crop_found when no crops available", async () => {
        const mockBot = {
            entity: { position: { x: 0, y: 64, z: 0 } },
            version: '1.20.4',
            inventory: { items: () => [] },
            findBlocks: () => [],
            chat: () => {},
            pathfinder: { stop: () => {} }
        };
        setBotInstance(mockBot);

        let sentResult = null;
        setSendToPythonOverride((payload) => {
            if (payload.type === 'action_completed') sentResult = payload;
        });

        try {
            await handleAction({ command: 'farm_crops', args: {}, action_id: 'test_farm_honest_1' });
            assert.ok(sentResult !== null, "Expected action_completed payload");
            assert.strictEqual(sentResult.success, false, "Expected success=false when no crops found");
            assert.strictEqual(sentResult.reason, "no_crop_found", "Expected reason=no_crop_found");
            assert.strictEqual(sentResult.error, "no_crop_found", "Expected error=no_crop_found");
        } finally {
            setSendToPythonOverride(null);
        }
    });

    await runTest("go_to_coordinates: returns success=false when bot did not arrive within range", async () => {
        const mockBot = {
            entity: {
                position: {
                    x: 0, y: 64, z: 0,
                    distanceTo: (target) => Math.sqrt((target.x - 0)**2 + (target.y - 64)**2 + (target.z - 0)**2)
                }
            },
            version: '1.20.4',
            pathfinder: {
                goto: async () => {}, // Mock pathfinder resolves but bot position stayed at (0, 64, 0)
                stop: () => {}
            },
            chat: () => {}
        };
        setBotInstance(mockBot);

        let sentResult = null;
        setSendToPythonOverride((payload) => {
            if (payload.type === 'action_completed') sentResult = payload;
        });

        try {
            // Target is at (50, 64, 50) with range 2m. Distance is ~70.7m > 2m threshold
            await handleAction({
                command: 'go_to_coordinates',
                args: { x: 50, y: 64, z: 50, range: 2 },
                action_id: 'test_goto_fail_1'
            });
            assert.ok(sentResult !== null, "Expected action_completed payload");
            assert.strictEqual(sentResult.success, false, "Must return success=false when distance > range");
            assert.ok(sentResult.error && sentResult.error.includes("did_not_reach_destination"), "Expected did_not_reach_destination error");
        } finally {
            setSendToPythonOverride(null);
        }
    });

    await runTest("go_to_coordinates: returns success=true and reason=arrived when destination reached", async () => {
        const mockBot = {
            entity: {
                position: {
                    x: 50.5, y: 64, z: 50.5,
                    distanceTo: (target) => Math.sqrt((target.x - 50.5)**2 + (target.y - 64)**2 + (target.z - 50.5)**2)
                }
            },
            version: '1.20.4',
            pathfinder: {
                goto: async () => {},
                stop: () => {}
            },
            chat: () => {}
        };
        setBotInstance(mockBot);

        let sentResult = null;
        setSendToPythonOverride((payload) => {
            if (payload.type === 'action_completed') sentResult = payload;
        });

        try {
            // Target is at (50, 64, 50) with range 2m. Distance is ~0.7m <= 2m threshold
            await handleAction({
                command: 'go_to_coordinates',
                args: { x: 50, y: 64, z: 50, range: 2 },
                action_id: 'test_goto_success_1'
            });
            assert.ok(sentResult !== null, "Expected action_completed payload");
            assert.strictEqual(sentResult.success, true, "Must return success=true when distance <= range");
            assert.strictEqual(sentResult.reason, "arrived", "Expected reason=arrived");
        } finally {
            setSendToPythonOverride(null);
        }
    });

    // ------------------------------------------------------------------
    // TEST SUITE 10: F1-R9 Precision Fixes (farmCrops empty area, 0 food/health, autoEatCheck 18 threshold)
    // ------------------------------------------------------------------
    console.log("\n[Suite 10] F1-R9 Precision Fixes (farmCrops empty, 0 food/health, autoEatCheck 18 threshold):");

    await runTest("farmCrops: returns false when no harvestable crops or tilling spots found", async () => {
        const mockBot = {
            findBlocks: () => [],
            inventory: { items: () => [] },
            chat: () => {}
        };
        const res = await farmCrops(mockBot);
        assert.strictEqual(res, false, "farmCrops must return false in empty area");
    });

    await runTest("getBotState: preserves health=0 and food=0 exactly without defaulting to 20", () => {
        const mockBot = {
            health: 0,
            food: 0,
            entity: {
                position: { x: 10, y: 64, z: 20 },
                yaw: 0, pitch: 0,
                velocity: { x: 0, y: 0, z: 0 }
            },
            inventory: { items: () => [], slots: {} },
            entities: {},
            players: {},
            blockAt: () => null,
            time: { timeOfDay: 6000, isDay: true },
            heldItem: null,
            game: { dimension: 'overworld' }
        };
        setBotInstance(mockBot);
        const state = getBotState();
        assert.strictEqual(state.health, 0, "health=0 must be preserved");
        assert.strictEqual(state.food, 0, "food=0 must be preserved");
    });

    await runTest("autoEatCheck: does not consume food when hunger is 18 or 19", async () => {
        let consumeCallCount = 0;
        const mockBot = {
            health: 15,
            food: 18,
            entity: { position: { x: 0, y: 64, z: 0 } },
            inventory: {
                items: () => [{ name: 'bread', count: 5 }]
            },
            consume: async () => { consumeCallCount++; },
            equip: async () => {},
            chat: () => {}
        };
        setBotInstance(mockBot);

        // Test at hunger 18 (should NOT eat)
        await autoEatCheck();
        assert.strictEqual(consumeCallCount, 0, "autoEatCheck should NOT consume food when hunger is 18");

        // Test at hunger 19 (should NOT eat)
        mockBot.food = 19;
        await autoEatCheck();
        assert.strictEqual(consumeCallCount, 0, "autoEatCheck should NOT consume food when hunger is 19");

        // Test at hunger 17 with health 15 (SHOULD eat for healing)
        mockBot.food = 17;
        await autoEatCheck();
        assert.strictEqual(consumeCallCount, 1, "autoEatCheck SHOULD consume food when health < 20 and hunger < 18");

        // Test at hunger 13 with full health 20 (SHOULD eat for starvation prevention)
        mockBot.health = 20;
        mockBot.food = 13;
        await autoEatCheck();
        assert.strictEqual(consumeCallCount, 2, "autoEatCheck SHOULD consume food when hunger < 14 regardless of health");
    });

    console.log("\n=================================================");
    console.log(`🎉 All ${passedTests}/${totalTests} unit stability tests PASSED!`);
    console.log("=================================================\n");
}

runAllTests().then(() => {
    process.exit(0);
}).catch((err) => {
    console.error("Test execution terminated with error:", err);
    process.exit(1);
});
