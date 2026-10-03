# 🎮 MC Local AI Bot (Ollama + Mineflayer Autonomous Co-op Player)

Bu proje, Minecraft dünyasında size yol arkadaşlığı yapan, sohbet eden, oyuncuyu takip eden, maden ve kaynak toplayan, canavarlardan koruyan, yemek avlayan ve tüm kararlarını **Lokal Yapay Zeka (Ollama)** ile alan otonom bir Minecraft insan-benzeri co-op oyuncu botudur.

---

## 📐 Sistem Mimarisi

```
+-------------------------------------------------------------+
|                     Minecraft Sunucusu                      |
+-------------------------------------------------------------+
                              ▲
                              │ Minecraft Protokolü (TCP)
                              ▼
+-------------------------------------------------------------+
|              Mineflayer Bot Worker (Node.js)                |
|  - mineflayer, mineflayer-pathfinder, collectblock           |
|  - Anlık durum (sağlık, envanter, etraftaki bloklar)       |
|  - Eylem icrası (git, topla, saldır, chat yap, takip et)    |
+-------------------------------------------------------------+
                              ▲
                              │ WebSocket Köprüsü (JSON)
                              ▼
+-------------------------------------------------------------+
|                Python AI Orkestratörü (Beyin)               |
|  - Karar Motoru & Eylem Yönlendirici (Skill Dispatcher)     |
|  - Oyuncu Hafızası & Dünya Koordinatları (SQLite)          |
|  - Ollama LLM Client (Tool Calling / Function Calling)      |
+-------------------------------------------------------------+
                              ▲
                              │ HTTP REST (http://localhost:11434)
                              ▼
+-------------------------------------------------------------+
|                   Ollama (Lokal AI Modeli)                  |
|          (qwen2.5:7b, llama3.1:8b, mistral vb.)             |
+-------------------------------------------------------------+
```

---

## 🚀 Temel Yetenekler

* **Lokal ve Ücretsiz Yapay Zeka:** Bulut API anahtarlarına ihtiyaç duymadan Ollama üzerinden çalışır (`qwen2.5:7b`, `llama3.1:8b` vb.).
* **Tool Calling (Fonksiyon Çağırma):** Model metin üretmenin yanı sıra doğrudan oyun içi eylemleri (odun kırma, takip etme, eşya verme) JSON komutu olarak çağırır.
* **Gelişmiş Yol Bulma (Pathfinding):** A* algoritması ile engebeleri, çukurları ve engelleri aşarak hedefine ulaşır.
* **Akıllı Kaynak Toplama:** "5 tane odun topla", "bana taş kaz" gibi emirlere göre yakındaki blokları otonom şekilde kırıp envanterine katar.
* **Dünya & Oyuncu Hafızası:** SQLite veritabanı sayesinde ev, maden koordinatlarını ve oyuncu geçmişini saklar.

---

## 🛠️ Kurulum

### 1. Gereksinimler
- Python 3.10+
- Node.js 18+
- [Ollama](https://ollama.ai) (ve kurulu bir model, örn: `ollama run qwen2.5:7b` veya `ollama run llama3.1:8b`)

### 2. Python Bağımlılıkları
```bash
pip install -r requirements.txt
```

### 3. Mineflayer (Node.js) Bağımlılıkları
```bash
cd minecraft_bot
npm install
cd ..
```

### 4. Yapılandırma (.env)
`.env.example` dosyasını `.env` olarak kopyalayın ve sunucu bilgilerinizi girin:
```env
MINECRAFT_HOST=localhost
MINECRAFT_PORT=25565
MINECRAFT_USERNAME=AIAssistant
BOT_OWNER=Omer
OLLAMA_MODEL=qwen2.5:7b
```

### 5. Başlatma
```bash
python main.py
```
*(Node.js Mineflayer botu Python tarafından otomatik olarak başlatılır. Dilerseniz ayrı bir terminalde `node minecraft_bot/bot.js` olarak da çalıştırabilirsiniz).*
