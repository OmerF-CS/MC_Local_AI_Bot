"""CLI tool to display recorded Minecraft AI decisions in markdown table format."""

import os
import sys
import json
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def format_table(limit: int = 15):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(base_dir, "data", "minecraft_decisions.jsonl")

    if not os.path.exists(log_file):
        print(f"⚠️ Henüz kaydedilmiş karar logu bulunamadı: {log_file}")
        print("Botu 'python main.py' ile çalıştırıp oyunda birkaç eylem gerçekleştirdikten sonra tekrar deneyin.")
        return

    records = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue

    if not records:
        print(f"ℹ️ {log_file} dosyası boş.")
        return

    selected = records[-limit:] if limit > 0 else records
    start_no = len(records) - len(selected) + 1

    print(f"\n📊 Toplam Kaydedilen Karar: {len(records)} | Gösterilen: Son {len(selected)} Karar\n")
    print("| karar_no | durum_özeti | model_çıktısı | inventory_delta | başarılı_mı | hata_türü |")
    print("|:---:|:---|:---|:---|:---:|:---|")

    errors_count = 0
    progress_count = 0

    for idx, rec in enumerate(selected, start=start_no):
        st = rec.get("state", {})
        ms = rec.get("milestone", {})
        dec = rec.get("decision", {})
        ex = rec.get("execution", {})

        # 1. Durum özeti
        hp = st.get("health", "?")
        food = st.get("food", "?")
        target = ms.get("target", "?")
        state_summary = f"HP:{hp} Açlık:{food} Hedef:{target}"

        # 2. Model çıktısı
        tool_name = dec.get("tool_name", "?")
        args = dec.get("arguments", {})
        args_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
        model_output = f"`{tool_name}({args_str})`"

        # 3. Inventory delta
        delta = ex.get("inventory_delta", {})
        if delta:
            delta_str = ", ".join(f"{k} {'+' if v > 0 else ''}{v}" for k, v in delta.items())
        else:
            delta_str = "Değişmedi"

        # 4. Başarılı mı
        progress = ex.get("progress_made", False)
        bridge_ok = ex.get("bridge_success", False)
        if progress:
            success_str = "✅ Evet"
            progress_count += 1
        elif bridge_ok:
            success_str = "⚠️ Etkisiz"
        else:
            success_str = "❌ Hayır"
            errors_count += 1

        # 5. Hata türü
        err = ex.get("error")
        if not err:
            if not progress and bridge_ok:
                error_type = "İlerleme yok (Envanter değişmedi)"
            elif not progress and not bridge_ok:
                error_type = "Eylem başarısız"
            else:
                error_type = "-"
        else:
            err_lower = str(err).lower()
            if "parameter" in err_lower or "missing" in err_lower or "invalid argument" in err_lower:
                error_type = f"Parametre Hatası ({err[:40]})"
            elif "craft" in err_lower or "recipe" in err_lower:
                error_type = f"Zanaat Hatası ({err[:40]})"
            else:
                error_type = f"{err[:40]}"

        print(f"| {idx} | {state_summary} | {model_output} | {delta_str} | {success_str} | {error_type} |")

    success_pct = (progress_count / len(selected)) * 100 if selected else 0
    print(f"\n📈 Başarı Oranı: %{success_pct:.1f} ({progress_count}/{len(selected)}) | Hata/Etkisiz Sayısı: {len(selected) - progress_count}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minecraft Karar Tablosu Gösterici")
    parser.add_argument("--limit", type=int, default=15, help="Gösterilecek son karar sayısı (varsayılan: 15)")
    args = parser.parse_args()
    format_table(args.limit)
