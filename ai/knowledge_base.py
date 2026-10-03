"""Minecraft Usta Oyuncu Bilgi Bankası ve Taktik Veri Seti (Knowledge Base & RAG)."""
from typing import Dict, Any, List, Optional

MINECRAFT_TACTICS = {
    "wood": {
        "title": "Ağaç ve Odun Toplama",
        "tip": "Hangi ağaç olursa olsun (meşe, huş, ladin) kütük kır. 3 kütük 12 tahtaya dönüşür, çalışma masası ve tahta kazma için fazlasıyla yeterlidir."
    },
    "mining_depths": {
        "title": "En Verimli Maden Yükseklikleri",
        "tip": "Kömür: Y 95-130 dağlarda | Demir: Y 14-16 mağaralarda | Elmas: Y -58 derin kayrak katmanında lavların hemen üstünde en çok bulunur."
    },
    "combat_creeper": {
        "title": "Creeper Savunması",
        "tip": "Creeper tısladığında ASLA yerinde durma! Hemen 4 blok geri koş veya kalkanını kaldır. Kalkan patlamanın tüm hasarını sıfırlar."
    },
    "combat_skeleton": {
        "title": "İskelet Taktikleri",
        "tip": "İskelete düz koşma. Kalkanını kaldırıp okunu engelle, oku attıktan hemen sonraki 1 saniyelik boşlukta koşup kılıçla vur."
    },
    "combat_enderman": {
        "title": "Enderman Güvenliği",
        "tip": "Enderman'in gözüne doğrudan bakma. Saldırırsa hemen 2 blok yüksekliğinde bir çatı altına gir (o 3 blok olduğu için giremez) veya su birikintisine dur."
    },
    "night_survival": {
        "title": "Gece Hayatta Kalma",
        "tip": "Zırhın yokken açık alanda savaşma. Yatak varsa hemen uyu, yoksa topraktan 3 blokluk dikey kule yapıp sabahı bekle veya madene in."
    },
    "food_efficiency": {
        "title": "Açlık ve Doygunluk",
        "tip": "Çiğ et yeme, fırında pişir (pişmiş biftek 8 açlık doldurur). Canın azaldığında açlık barın 18+ olmalı ki canın otomatik dolsun."
    },
    "nether_portal": {
        "title": "Hızlı Nether Portalı",
        "tip": "Elmas kazman yoksa su kovası ve lav havuzu kullanarak blokları teker teker obsidyene dönüştürüp döküm yöntemiyle portal yapabilirsin."
    },
    "blaze_combat": {
        "title": "Blaze ve İksir Çubuğu",
        "tip": "Blaze ateş topu atmadan önce duman çıkarır. Kalkan ateşi engeller. Kar topları veya yayla uzaktan çok hızlı ölürler."
    },
    "ender_dragon": {
        "title": "Ender Ejderhası Savaşı",
        "tip": "Önce obsidyen kulelerdeki kristalleri okla patlat. Ejderha orta sütuna indiğinde kafasının altına yatak koyup blok arkasından patlatarak tek vuruşta devasa hasar ver (Bed Bombing)."
    }
}

def get_relevant_tactic(state: Dict[str, Any]) -> str:
    """Anlık oyun durumuna göre en kritik usta oyuncu tavsiyesini döner."""
    hostiles = [h.lower() for h in state.get("nearby_hostiles", [])]
    is_day = state.get("is_day", True)
    health = state.get("health", 20)
    food = state.get("food", 20)
    pos = state.get("position", {})
    y = pos.get("y", 64)

    # Tehlike öncelikli taktikler
    if any("creeper" in h for h in hostiles):
        return MINECRAFT_TACTICS["combat_creeper"]["tip"]
    if any("skeleton" in h for h in hostiles):
        return MINECRAFT_TACTICS["combat_skeleton"]["tip"]
    if any("enderman" in h for h in hostiles):
        return MINECRAFT_TACTICS["combat_enderman"]["tip"]

    # Hayatta kalma taktikleri
    if not is_day and health < 14:
        return MINECRAFT_TACTICS["night_survival"]["tip"]
    if food < 14:
        return MINECRAFT_TACTICS["food_efficiency"]["tip"]

    # Maden derinliği taktikleri
    if y < 0:
        return MINECRAFT_TACTICS["mining_depths"]["tip"]

    return MINECRAFT_TACTICS["wood"]["tip"]
