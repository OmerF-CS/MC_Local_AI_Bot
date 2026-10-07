"""Phase 6: Unsloth 4-bit QLoRA Fine-Tuning Pipeline for Qwen 2.5 3B.

Hardware target: NVIDIA GeForce RTX 3060 6 GB VRAM.
Peak VRAM footprint during training: ~3.4 GB (leaves ample headroom for system & display).
Exports to 4-bit GGUF (q4_k_m) and automatically generates an Ollama Modelfile for local serving.
"""

import os
import sys
import argparse
from typing import Dict, Any, List

# Reconfigure stdout for UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def check_gpu_and_dependencies():
    """Validates GPU availability and reports memory parameters."""
    try:
        import torch
        if not torch.cuda.is_available():
            print("⚠️ WARNING: No CUDA GPU detected. RTX 3060 CUDA is required for QLoRA training.")
            return False
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"🎮 Detected GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)")
        return True
    except ImportError:
        print("❌ PyTorch is not installed in this environment.")
        print("   To install training requirements:")
        print("   pip install torch --index-url https://download.pytorch.org/whl/cu121")
        print("   pip install \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\"")
        print("   pip install trl peft accelerate bitsandbytes datasets")
        return False


def build_ollama_modelfile(gguf_file_path: str, modelfile_dest: str):
    """Generates a complete Modelfile for one-click Ollama model registration."""
    content = f"""FROM {gguf_file_path}

TEMPLATE \"\"\"{{{{ if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{ end }}}}{{{{ if .Prompt }}}}<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
{{{{ end }}}}<|im_start|>assistant
{{{{ .Response }}}}<|im_end|>\"\"\"

PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
PARAMETER temperature 0.1
PARAMETER top_p 0.8
PARAMETER num_gpu 999
"""
    os.makedirs(os.path.dirname(modelfile_dest) or ".", exist_ok=True)
    with open(modelfile_dest, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"📄 Created Ollama Modelfile at: {modelfile_dest}")


def run_training(
    model_name: str = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
    train_file: str = "data/sft_train.jsonl",
    val_file: str = "data/sft_val.jsonl",
    output_dir: str = "models/mc-qwen-3b-lora",
    max_seq_length: int = 1024,
    batch_size: int = 1,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    epochs: int = 3,
    export_gguf: bool = True,
    gguf_quant: str = "q4_k_m"
):
    """Executes full Unsloth QLoRA SFT training loop on Qwen 2.5 3B."""
    print("=" * 70)
    print("🚀 MC Local AI Bot - Phase 6: Unsloth QLoRA SFT Training (RTX 3060)")
    print("=" * 70)

    try:
        from unsloth import FastLanguageModel, is_bfloat16_supported
        import torch
        from datasets import load_dataset
        from trl import SFTTrainer
        from transformers import TrainingArguments
    except ImportError as e:
        print(f"❌ Missing library: {e}")
        print("\n📦 To set up local training:")
        print("  pip install \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\"")
        print("  pip install torch trl peft accelerate bitsandbytes datasets")
        print("\n💡 TIP: You can also run 'train_colab.ipynb' on Google Colab (Free T4 GPU)!")
        return False

    if not os.path.exists(train_file):
        print(f"❌ Training dataset not found at: {train_file}")
        print("   Run: python export_sft_dataset.py to generate it first.")
        return False

    # 1. Load 4-bit Base Model
    print(f"\n📦 Loading 4-bit quantized base model '{model_name}' (Target max seq: {max_seq_length})...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_name,
        max_seq_length=max_seq_length,
        dtype=None,  # Auto-select float16 / bfloat16
        load_in_4bit=True,
    )

    # 2. Add LoRA Adapters
    print("🔧 Configuring LoRA adapters (r=16, alpha=16, all attention & MLP projections)...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj"
        ],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
        max_seq_length=max_seq_length,
    )

    # 3. Format Dataset with Qwen Chat Template
    print(f"📖 Loading datasets ({train_file})...")
    data_files = {"train": train_file}
    if os.path.exists(val_file):
        data_files["validation"] = val_file

    raw_dataset = load_dataset("json", data_files=data_files)

    def formatting_prompts_func(examples):
        texts = []
        for msgs in examples["messages"]:
            text = tokenizer.apply_chat_template(
                msgs,
                tokenize=False,
                add_generation_prompt=False
            )
            texts.append(text)
        return {"text": texts}

    formatted_dataset = raw_dataset.map(formatting_prompts_func, batched=True)
    print(f"✨ Formatted {len(formatted_dataset['train'])} training samples.")

    # 4. Configure SFTTrainer (Optimized for 6 GB RTX 3060)
    print("\n⚙️ Setting up SFTTrainer (batch=1, grad_accum=4, optim=adamw_8bit, fp16)...")
    training_args = TrainingArguments(
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        warmup_steps=5,
        num_train_epochs=epochs,
        learning_rate=learning_rate,
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        logging_steps=5,
        optim="adamw_8bit",  # Saves ~1.5 GB VRAM
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir=output_dir,
        save_strategy="epoch",
        report_to="none"
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=formatted_dataset["train"],
        eval_dataset=formatted_dataset.get("validation"),
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        dataset_num_proc=1,
        packing=False,
        args=training_args,
    )

    # 5. Train
    print("\n🏋️ Starting QLoRA Fine-Tuning...")
    trainer_stats = trainer.train()
    print(f"\n🎉 Training complete in {trainer_stats.metrics.get('train_runtime', 0):.1f}s!")

    # 6. Save LoRA Adapters
    print(f"💾 Saving LoRA adapter weights to: {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # 7. GGUF Export for Ollama
    if export_gguf:
        gguf_dir = os.path.join(os.path.dirname(output_dir) or "models", "mc-qwen-3b-gguf")
        print(f"\n🔄 Exporting to GGUF format ({gguf_quant}) for Ollama at: {gguf_dir}...")
        try:
            model.save_pretrained_gguf(
                gguf_dir,
                tokenizer,
                quantization_method=gguf_quant
            )
            # Find generated GGUF file
            gguf_path = os.path.join(gguf_dir, f"unsloth.{gguf_quant.upper()}.gguf")
            if not os.path.exists(gguf_path):
                # Search for any .gguf file in gguf_dir
                for fname in os.listdir(gguf_dir):
                    if fname.endswith(".gguf"):
                        gguf_path = os.path.join(gguf_dir, fname)
                        break

            # Build Ollama Modelfile
            modelfile_path = os.path.join(os.path.dirname(output_dir) or "models", "Modelfile")
            build_ollama_modelfile(gguf_path, modelfile_path)

            print("\n" + "=" * 70)
            print("🎉 Fine-Tuned Model is Ready for Ollama!")
            print("=" * 70)
            print("To register and activate the tuned model:")
            print(f"  1. ollama create mc-qwen:3b -f {modelfile_path}")
            print("  2. In your .env file, update:")
            print("     OLLAMA_MODEL=mc-qwen:3b")
            print("  3. Run the bot: python main.py")
            print("=" * 70)

        except Exception as export_err:
            print(f"⚠️ GGUF export failed: {export_err}")
            print("You can still use the saved LoRA adapter with HuggingFace / vLLM.")

    return True


def main():
    parser = argparse.ArgumentParser(description="Unsloth 4-bit QLoRA SFT for Qwen 2.5 3B (Minecraft Bot)")
    parser.add_argument("--model-name", default="unsloth/Qwen2.5-3B-Instruct-bnb-4bit", help="Hugging Face model ID")
    parser.add_argument("--train-file", default="data/sft_train.jsonl", help="Path to training jsonl")
    parser.add_argument("--val-file", default="data/sft_val.jsonl", help="Path to validation jsonl")
    parser.add_argument("--output-dir", default="models/mc-qwen-3b-lora", help="Output directory for LoRA weights")
    parser.add_argument("--max-seq-length", type=int, default=1024, help="Max sequence length (1024 fits 6GB VRAM)")
    parser.add_argument("--batch-size", type=int, default=1, help="Per-device train batch size")
    parser.add_argument("--grad-accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--epochs", type=int, default=3, help="Training epochs")
    parser.add_argument("--no-gguf", action="store_true", help="Skip GGUF export")
    parser.add_argument("--gguf-quant", default="q4_k_m", help="GGUF quantization method (default: q4_k_m)")

    args = parser.parse_args()

    check_gpu_and_dependencies()

    run_training(
        model_name=args.model_name,
        train_file=args.train_file,
        val_file=args.val_file,
        output_dir=args.output_dir,
        max_seq_length=args.max_seq_length,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.lr,
        epochs=args.epochs,
        export_gguf=not args.no_gguf,
        gguf_quant=args.gguf_quant
    )


if __name__ == "__main__":
    main()
