"""Minecraft Eşya ve Zanaat (Crafting) Bilgi Bankası."""
from typing import Optional, Dict, Any

RECIPES: Dict[str, Dict[str, Any]] = {
    "torch": {
        "name": "Meşale",
        "ingredients": "1 Kömür (Coal) veya Odun Kömürü + 1 Çubuk (Stick)",
        "output_count": 4,
        "description": "Karanlık yerleri ve madenleri aydınlatmak, yaratık doğmasını engellemek için kullanılır."
    },
    "crafting_table": {
        "name": "Çalışma Masası (Crafting Table)",
        "ingredients": "4 Tahta (Planks)",
        "output_count": 1,
        "description": "3x3 üretim ızgarası sağlar, neredeyse tüm karmaşık eşyalar için zorunludur."
    },
    "furnace": {
        "name": "Fırın (Furnace)",
        "ingredients": "8 Kırıktaş (Cobblestone)",
        "output_count": 1,
        "description": "Madenleri eritmek ve yemek pişirmek için kullanılır."
    },
    "chest": {
        "name": "Sandık (Chest)",
        "ingredients": "8 Tahta (Planks)",
        "output_count": 1,
        "description": "27 yuvalık depolama alanı sağlar."
    },
    "bed": {
        "name": "Yatak (Bed)",
        "ingredients": "3 Yün (Wool) + 3 Tahta (Planks)",
        "output_count": 1,
        "description": "Geceyi atlamak ve yeniden doğma noktasını ayarlamak için kullanılır."
    },
    "wooden_pickaxe": {
        "name": "Tahta Kazma",
        "ingredients": "3 Tahta + 2 Çubuk",
        "output_count": 1,
        "description": "Taş ve kömür kazmak için gereken en temel alet."
    },
    "stone_pickaxe": {
        "name": "Taş Kazma",
        "ingredients": "3 Kırıktaş + 2 Çubuk",
        "output_count": 1,
        "description": "Demir cevheri kazmak için gereken alet."
    },
    "iron_pickaxe": {
        "name": "Demir Kazma",
        "ingredients": "3 Demir Külçesi (Iron Ingot) + 2 Çubuk",
        "output_count": 1,
        "description": "Altın, kızıltaş ve elmas cevheri kazabilir."
    },
    "shield": {
        "name": "Kalkan (Shield)",
        "ingredients": "1 Demir Külçesi + 6 Tahta",
        "output_count": 1,
        "description": "Okları ve creeper patlamalarını engellemek için hayat kurtarıcıdır."
    },
    "iron_sword": {
        "name": "Demir Kılıç",
        "ingredients": "2 Demir Külçesi + 1 Çubuk",
        "output_count": 1,
        "description": "6 saldırı hasarı verir."
    },
    "iron_chestplate": {
        "name": "Demir Göğüslük",
        "ingredients": "8 Demir Külçesi",
        "output_count": 1,
        "description": "Güçlü zırh koruması sağlar."
    },
    "bucket": {
        "name": "Kova (Bucket)",
        "ingredients": "3 Demir Külçesi",
        "output_count": 1,
        "description": "Su, lav veya süt taşımak için kullanılır."
    }
}

def get_recipe(query: str) -> Optional[Dict[str, Any]]:
    """Girilen sorguya göre en uygun crafting tarifini döner."""
    clean = query.lower().strip().replace(" ", "_")
    # Doğrudan eşleşme
    if clean in RECIPES:
        return RECIPES[clean]
    # Kısmi eşleşme
    for key, val in RECIPES.items():
        if clean in key or key in clean or clean in val["name"].lower():
            return val
    return None
