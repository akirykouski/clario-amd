"""PEFT LoRA SFT (TRL) for Gemma 4. Runs on ROCm (MI300X, bf16) and on CUDA (a 16 GB card or Kaggle, 4-bit QLoRA).
Trains on the extraction_v3 chat files written by prep.py (data/v3/*_sft.jsonl). Older-format files are refused.
  python train_rocm.py --model google/gemma-4-E4B-it --out out/e4b-r16 --epochs 3                      # big GPU, bf16
  python train_rocm.py --model google/gemma-4-E4B-it --out out/e4b-r16 --epochs 2 --load-in-4bit --bsz 2 --grad-accum 8   # 16 GB
Precision: --precision auto uses bf16 when the GPU supports it (MI300X, RTX 30xx+), else fp16 (Kaggle T4/P100).
"""
import argparse, json, os, time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/gemma-4-26B-A4B-it")
    ap.add_argument("--data", default="data/v3/train_sft.jsonl")
    ap.add_argument("--val-data", default="data/v3/val_sft.jsonl", help="optional eval loss; '' to disable")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rank", type=int, default=16); ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--epochs", type=float, default=3); ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-len", type=int, default=1536)
    ap.add_argument("--bsz", type=int, default=4); ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--target-modules", default="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj",
                    help="comma list or 'all-linear'. For the MoE model, expert weights may be fused params that LoRA skips; attention+dense MLP still get adapted.")
    ap.add_argument("--bf16", action="store_true", default=True, help=argparse.SUPPRESS)  # kept for old commands
    ap.add_argument("--precision", default="auto", choices=["auto", "bf16", "fp16"])
    ap.add_argument("--load-in-4bit", action="store_true", help="QLoRA: 4-bit NF4 base (bitsandbytes, CUDA) for 16 GB GPUs")
    ap.add_argument("--attn", default="sdpa", help="sdpa (default, safe on ROCm) | eager | flash_attention_2 if installed")
    ap.add_argument("--merge", action="store_true", help="also save merged bf16 weights for vLLM")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--results-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "results"),
                    help="provenance copy train_<label>.json goes here ('' to skip)")
    ap.add_argument("--skip-data-check", action="store_true", help="do not verify the files are extraction_v3 chat files")
    a = ap.parse_args()

    from prep import check_sft  # stdlib only; fails fast on old-format or malformed data before any GPU work
    if not a.skip_data_check:
        for p in (a.data, a.val_data):
            if p and os.path.exists(p):
                print(p, check_sft(p))

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainerCallback
    from trl import SFTConfig, SFTTrainer

    os.makedirs(a.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(a.model)
    bf16_ok = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    use_bf16 = a.precision == "bf16" or (a.precision == "auto" and bf16_ok)
    dtype = torch.bfloat16 if use_bf16 else torch.float16
    print(f"GPU {torch.cuda.get_device_name(0)}  precision {'bf16' if use_bf16 else 'fp16'}  4-bit {a.load_in_4bit}")
    kw = dict(torch_dtype=dtype, attn_implementation=a.attn)
    if a.load_in_4bit:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
        kw["device_map"] = {"": 0}
        if a.merge:
            print("note: --merge is skipped with --load-in-4bit (merging into a 4-bit base is lossy); "
                  "use export.py merge on the bf16 base instead")
            a.merge = False
    try:
        model = AutoModelForCausalLM.from_pretrained(a.model, **kw)
    except Exception as e:  # Gemma 4 card loads with AutoModelForMultimodalLM
        print("AutoModelForCausalLM failed:", repr(e)[:200], "-> AutoModelForMultimodalLM")
        from transformers import AutoModelForMultimodalLM
        model = AutoModelForMultimodalLM.from_pretrained(a.model, **kw)
    model.config.use_cache = False  # E2B/E4B: KV-shared layers misbehave without cache in some versions; see README
    if a.load_in_4bit:
        from peft import prepare_model_for_kbit_training
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    def conv(ex):  # prompt/completion => loss on the assistant JSON only
        m = ex["messages"]
        return {"prompt": m[:-1], "completion": m[-1:]}
    ds = load_dataset("json", data_files=a.data, split="train")
    ds = ds.map(conv, remove_columns=ds.column_names)
    ev = None
    if a.val_data and os.path.exists(a.val_data):
        ev = load_dataset("json", data_files=a.val_data, split="train")
        ev = ev.map(conv, remove_columns=ev.column_names)

    tm = "all-linear" if a.target_modules == "all-linear" else a.target_modules.split(",")
    peft_cfg = LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=a.dropout, target_modules=tm,
                          task_type="CAUSAL_LM", bias="none")

    class Metrics(TrainerCallback):
        def __init__(self): self.t0 = None; self.step_t = []; self.last = None; self.tokens = 0
        def on_train_begin(self, args, state, control, **k):
            self.t0 = time.time(); self.last = self.t0; torch.cuda.reset_peak_memory_stats()
        def on_step_end(self, args, state, control, **k):
            torch.cuda.synchronize(); now = time.time(); self.step_t.append(now - self.last); self.last = now

    cb = Metrics()
    cfg = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs, learning_rate=a.lr, lr_scheduler_type="cosine",
                    warmup_ratio=0.05, per_device_train_batch_size=a.bsz, gradient_accumulation_steps=a.grad_accum,
                    bf16=use_bf16, fp16=not use_bf16, max_length=a.max_len, logging_steps=5, save_strategy="epoch", save_total_limit=2,
                    eval_strategy="epoch" if ev is not None else "no", per_device_eval_batch_size=a.bsz,
                    gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
                    seed=a.seed, report_to="none", completion_only_loss=True)
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, eval_dataset=ev, processing_class=tok,
                         peft_config=peft_cfg, callbacks=[cb])
    trainer.model.print_trainable_parameters()
    t0 = time.time()
    res = trainer.train()
    wall = time.time() - t0
    # token count: sum of tokenised train examples * epochs (non-padded estimate)
    ntok = sum(len(x) for x in trainer.train_dataset["input_ids"]) if "input_ids" in trainer.train_dataset.column_names else 0
    ntok_total = ntok * a.epochs
    steps = sorted(cb.step_t)
    metrics = {
        "model": a.model, "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__,
        "hip": getattr(torch.version, "hip", None), "cuda": torch.version.cuda, "precision": "bf16" if use_bf16 else "fp16",
        "load_in_4bit": a.load_in_4bit, "rank": a.rank, "alpha": a.alpha, "epochs": a.epochs,
        "lr": a.lr, "max_len": a.max_len, "bsz": a.bsz, "grad_accum": a.grad_accum,
        "train_wall_s": wall, "train_loss": res.training_loss,
        "step_time_mean_s": sum(cb.step_t) / max(1, len(cb.step_t)),
        "step_time_p50_s": steps[len(steps) // 2] if steps else None,
        "tokens_trained_est": ntok_total, "tokens_per_s_est": ntok_total / wall if wall and ntok_total else None,
        "peak_mem_gb": torch.cuda.max_memory_allocated() / 2**30,
        "log_history": trainer.state.log_history,
    }
    hip = getattr(torch.version, "hip", None)
    metrics.update({"n": len(ds), "dataset": a.data, "backend": f"rocm-hip-{hip}" if hip else f"cuda-{torch.version.cuda}",
                    "date": __import__("datetime").date.today().isoformat()})  # provenance, same fields as every eval/results file
    json.dump(metrics, open(os.path.join(a.out, "metrics.json"), "w"), indent=2)
    if a.results_dir:
        os.makedirs(a.results_dir, exist_ok=True)
        label = os.path.basename(os.path.normpath(a.out))
        json.dump({**{k: v for k, v in metrics.items() if k != "log_history"}, "label": label},
                  open(os.path.join(a.results_dir, f"train_{label}.json"), "w"), indent=2)
    trainer.save_model(os.path.join(a.out, "adapter")); tok.save_pretrained(os.path.join(a.out, "adapter"))
    print({k: v for k, v in metrics.items() if k != "log_history"})
    if a.merge:
        merged = trainer.model.merge_and_unload()
        merged.save_pretrained(os.path.join(a.out, "merged"), safe_serialization=True)
        tok.save_pretrained(os.path.join(a.out, "merged"))


if __name__ == "__main__":
    main()
