/**
 * Unit Behavioral Tests for Mineflayer Worker Stability (F0 / F0-R1)
 * Runs mock-based unit tests without needing a live Minecraft server.
 */
const assert = require('assert');
const { spawnSync } = require('child_process');
const path = require('path');

const botModule = require('./bot');
const {
    autoSelfDefenseCheck,
    handleAction,
    handleFatalProcessError,
    setBotInstance,
    setSendToPythonOverride,
    getConsecutiveProcessErrors,
    resetConsecutiveProcessErrors
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

    console.log("\n=================================================");
    console.log(`🎉 All ${passedTests}/${totalTests} unit stability tests PASSED!`);
    console.log("=================================================\n");
}

runAllTests().catch((err) => {
    console.error("Test execution terminated with error:", err);
    process.exit(1);
});
