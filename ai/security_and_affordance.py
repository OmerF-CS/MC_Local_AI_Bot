"""Security, Sanitization, Multilingual Aliasing, and Affordance Engine.

Handles chat security, prompt injection rejection, anti-troll detection,
CJK character stripping, multilingual Minecraft item alias normalization,
and inventory affordance calculation for LLM prompts.
"""
from typing import Dict, Any, List, Optional, Tuple
import re
from ai.progression_tree import TECH_TREE, resolve_missing_ingredients

# Regex pattern for CJK (Chinese, Japanese, Korean) characters
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")

# Secret masking patterns (GitHub PAT, OpenAI API keys, Google API keys, Bearer tokens)
SECRET_PATTERNS = [
    re.compile(r"gh[oprs]_[A-Za-z0-9_]{36,255}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,255}"),
    re.compile(r"AIza[0-9A-Za-z-_]{30,45}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
]

# Multilingual Alias Map (Turkish + English to Minecraft 1.20.4 Canonical Names)
MULTILINGUAL_ALIAS_MAP: Dict[str, str] = {
    # --- Tools, Weapons, Armor & Utility ---
    "tahta kazma": "wooden_pickaxe",
    "taş kazma": "stone_pickaxe",
    "tas kazma": "stone_pickaxe",
    "demir kazma": "iron_pickaxe",
    "elmas kazma": "diamond_pickaxe",
    "netherite kazma": "netherite_pickaxe",
    "tahta kılıç": "wooden_sword",
    "tahta kilic": "wooden_sword",
    "taş kılıç": "stone_sword",
    "tas kilic": "stone_sword",
    "demir kılıç": "iron_sword",
    "demir kilic": "iron_sword",
    "elmas kılıç": "diamond_sword",
    "elmas kilic": "diamond_sword",
    "demir balta": "iron_axe",
    "demir kürek": "iron_shovel",
    "demir kurek": "iron_shovel",
    "demir çapa": "iron_hoe",
    "demir capa": "iron_hoe",
    "kalkan": "shield",
    "makas": "shears",
    "olta": "fishing_rod",
    "yay": "bow",
    "çakmaktaşı ve çelik": "flint_and_steel",
    "cakmaktasi ve celik": "flint_and_steel",
    "cakmaktasi": "flint_and_steel",
    "çakmaktaşı": "flint_and_steel",
    "kova": "bucket",
    "su kovası": "water_bucket",
    "su kovasi": "water_bucket",
    "lav kovası": "lava_bucket",
    "lav kovasi": "lava_bucket",

    # --- Blocks, Ores & Items ---
    "odun": "log",
    "meşe odunu": "oak_log",
    "mese odunu": "oak_log",
    "ağaç": "log",
    "agac": "log" ,
    "tahta": "planks",
    "çubuk": "stick",
    "cubuk": "stick",
    "çalışma masası": "crafting_table",
    "calisma masasi": "crafting_table",
    "fırın": "furnace",
    "firin": "furnace",
    "sandık": "chest",
    "sandik": "chest",
    "yatak": "bed",
    "meşale": "torch",
    "mesale": "torch",
    "taş": "stone",
    "tas": "stone",
    "kırık taş": "cobblestone",
    "kirik tas": "cobblestone",
    "kömür": "coal",
    "komur": "coal",
    "demir": "iron_ore",
    "ham demir": "raw_iron",
    "demir külçesi": "iron_ingot",
    "demir kulcesi": "iron_ingot",
    "demir blok": "iron_block",
    "altın": "gold_ore",
    "altin": "gold_ore",
    "ham altın": "raw_gold",
    "ham altin": "raw_gold",
    "altın külçesi": "gold_ingot",
    "altin kulcesi": "gold_ingot",
    "elmas": "diamond",
    "zümrüt": "emerald",
    "zumrut": "emerald",
    "obsidyen": "obsidian",
    "balkabağı": "carved_pumpkin",
    "balkabagi": "carved_pumpkin",
    "kar bloğu": "snow_block",
    "kar blogu": "snow_block",

    # --- Entities & Food ---
    "inek": "cow",
    "koyun": "sheep",
    "domuz": "pig",
    "tavuk": "chicken",
    "tavşan": "rabbit",
    "tavsan": "rabbit",
    "zombi": "zombie",
    "iskelet": "skeleton",
    "örümcek": "spider",
    "orumcek": "spider",
    "ekmek": "bread",
    "elma": "apple",
    "biftek": "cooked_beef",
    "çiğ biftek": "beef",
    "cig biftek": "beef",

    # --- Common English Aliases ---
    "wood": "log",
    "logs": "log",
    "oak log": "oak_log",
    "crafting table": "crafting_table",
    "furnace": "furnace",
    "stick": "stick",
    "sticks": "stick",
    "wooden pickaxe": "wooden_pickaxe",
    "stone pickaxe": "stone_pickaxe",
    "iron pickaxe": "iron_pickaxe",
    "diamond pickaxe": "diamond_pickaxe",
    "raw iron": "raw_iron",
    "iron ingot": "iron_ingot",
    "raw gold": "raw_gold",
    "gold ingot": "gold_ingot",
    "water bucket": "water_bucket",
    "lava bucket": "lava_bucket",
    "flint and steel": "flint_and_steel",
}

def strip_cjk(text: str) -> str:
    """Removes CJK (Chinese, Japanese, Korean) characters from text."""
    if not isinstance(text, str):
        return text
    return CJK_PATTERN.sub("", text)

def normalize_item_alias(raw_name: str) -> str:
    """Normalizes item/block/mob alias from Turkish or informal English to canonical Minecraft ID."""
    if not raw_name or not isinstance(raw_name, str):
        return ""
    clean = strip_cjk(raw_name).strip().lower()
    if not clean:
        return ""
    clean = clean.strip("\"'`.,:;!?()[]{}")
    if clean in MULTILINGUAL_ALIAS_MAP:
        return MULTILINGUAL_ALIAS_MAP[clean]

    space_form = clean.replace("_", " ")
    if space_form in MULTILINGUAL_ALIAS_MAP:
        return MULTILINGUAL_ALIAS_MAP[space_form]

    underscore_form = clean.replace(" ", "_")
    if underscore_form in MULTILINGUAL_ALIAS_MAP:
        return MULTILINGUAL_ALIAS_MAP[underscore_form]

    return underscore_form

class SecurityGuard:
    """Guards against prompt injections, shell execution attempts, secrets leakage, and in-game troll commands."""

    SHELL_AND_PROMPT_INJECTION_PATTERNS = [
        re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
        re.compile(r"\bdel\s+/[fs]\b", re.IGNORECASE),
        re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
        re.compile(r"\bpowershell(\.exe)?\s+(-enc|-encodedcommand)\b", re.IGNORECASE),
        re.compile(r"\bignore\s+previous\s+instructions\b", re.IGNORECASE),
        re.compile(r"\bsystem\s+prompt\s*:", re.IGNORECASE),
        re.compile(r"\bos\.system\b", re.IGNORECASE),
        re.compile(r"\bsubprocess\.", re.IGNORECASE),
        re.compile(r"\beval\s*\(", re.IGNORECASE),
        re.compile(r"\bexec\s*\(", re.IGNORECASE),
    ]

    IN_GAME_TROLL_PATTERNS = [
        "lava atla", "lavda yüz", "lavda yuz", "kendini yak", "lava gir",
        "swim in lava", "jump in lava", "jump into lava",
        "eşyalarını at", "esyalarini at", "itemleri at", "q ya bas", "q bas",
        "kazmanı at", "kazmani at", "silahını at", "silahini at",
        "drop all items", "throw away your",
        "uçurumdan atla", "ucurumdan atla", "boşluğa atla", "bosluga atla",
        "jump into the void", "intihar", "kill yourself", "alt+f4", "alt f4"
    ]

    def sanitize_chat_input(self, username: str, content: str) -> Tuple[bool, str, Optional[str]]:
        """Validates incoming chat for dangerous shell commands or prompt injection attacks.

        Returns:
            (is_safe, cleaned_text, reject_reason)
        """
        if not content:
            return True, "", None

        cleaned = strip_cjk(content).strip()

        for pattern in self.SHELL_AND_PROMPT_INJECTION_PATTERNS:
            if pattern.search(cleaned):
                return False, cleaned, f"Rejected potential prompt/command injection pattern: {pattern.pattern}"

        return True, cleaned, None

    def check_in_game_troll(self, content: str) -> Tuple[bool, Optional[str]]:
        """Detects in-game suicide, lava-diving, or item-dropping troll commands in Turkish or English.

        Returns:
            (is_troll, reason)
        """
        if not content:
            return False, None

        normalized = content.lower().strip()
        for troll_phrase in self.IN_GAME_TROLL_PATTERNS:
            if troll_phrase in normalized:
                return True, f"Detected in-game troll command: '{troll_phrase}'"

        return False, None

    def redact_secrets(self, text: str) -> str:
        """Masks sensitive authentication tokens, GitHub PATs, and API keys with [REDACTED]."""
        if not text or not isinstance(text, str):
            return text

        redacted = text
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)

        return redacted

class AffordanceEngine:
    """Analyzes inventory to identify instantly actionable crafting recipes and smelting opportunities."""

    KEY_SURVIVAL_CRAFTS = [
        "wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe",
        "crafting_table", "furnace", "torch", "shield", "bucket",
        "bow", "fishing_rod", "shears", "iron_block", "snow_block", "carved_pumpkin"
    ]

    SMELTABLE_ITEMS = [
        "raw_iron", "iron_ore", "deepslate_iron_ore",
        "raw_gold", "gold_ore", "deepslate_gold_ore",
        "raw_copper", "copper_ore", "deepslate_copper_ore",
        "beef", "porkchop", "chicken", "mutton", "potato", "cod", "salmon", "kelp"
    ]

    SINGLE_COPY_TOOLS = {
        "wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "diamond_pickaxe",
        "crafting_table", "furnace", "shield", "bucket", "shears", "fishing_rod", "bow"
    }

    def get_affordances(self, inv_dict: Dict[str, int]) -> Dict[str, List[str]]:
        """Returns lists of currently craftable and smeltable items based on inventory contents."""
        craftable_now: List[str] = []
        smeltable_now: List[str] = []

        if not inv_dict:
            return {"craftable_now": [], "smeltable_now": []}

        # Check craftable recipes
        for item in self.KEY_SURVIVAL_CRAFTS:
            if item in TECH_TREE:
                # If tool/station already present, skip duplicate suggestion
                if item in self.SINGLE_COPY_TOOLS and inv_dict.get(item, 0) >= 1:
                    continue
                missing = resolve_missing_ingredients(item, inv_dict)
                if len(missing) == 0:
                    craftable_now.append(item)

        # Check smeltable items
        for item in self.SMELTABLE_ITEMS:
            if inv_dict.get(item, 0) > 0:
                smeltable_now.append(item)

        return {
            "craftable_now": craftable_now,
            "smeltable_now": smeltable_now
        }

    def format_affordances_context(self, inv_dict: Dict[str, int]) -> str:
        """Produces a concise, single-line prompt hint summarizing craftable/smeltable items."""
        affordances = self.get_affordances(inv_dict)
        craftable = affordances.get("craftable_now", [])
        smeltable = affordances.get("smeltable_now", [])

        parts = []
        if craftable:
            parts.append(f"CraftReady={','.join(craftable[:4])}")
        if smeltable:
            parts.append(f"SmeltReady={','.join(smeltable[:3])}")

        if not parts:
            return ""

        return f"[Affordances: {' | '.join(parts)}]"
