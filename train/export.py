"""M5: export the trained model. NOT RUN YET: written and statically checked only (no GPU, no weights here).

Two targets from the same LoRA adapter:
  1. bf16 merged weights for vLLM on the MI300X (clinic server and the demo deployment).
  2. GGUF Q4_K_M for a laptop (Ollama / llama.cpp), converted from those merged weights.

    # 1. merge the adapter into the base model (needs the base weights and a GPU or lots of RAM)
    python export.py merge --base google/gemma-4-26B-A4B-it --adapter out/a4b-r16/adapter --out out/a4b-r16/merged
    vllm serve out/a4b-r16/merged --max-model-len 4096 --port 8000          # then eval.py against it

    # 2. laptop build, from a llama.cpp checkout (https://github.com/ggml-org/llama.cpp), merged weights as input
    python convert_hf_to_gguf.py out/a4b-r16/merged --outfile clario-extract-v3-f16.gguf --outtype f16
    ./llama-quantize clario-extract-v3-f16.gguf clario-extract-v3-Q4_K_M.gguf Q4_K_M
    python export.py modelfile --gguf clario-extract-v3-Q4_K_M.gguf --out Modelfile
    ollama create clario-extract-v3 -f Modelfile                             # then eval.py --base-url :11434/v1

Unverified: that llama.cpp converts the Gemma 4 architecture in use (MoE 26B-A4B or the E4B variant) at the
time of the run, and that Q4_K_M keeps extraction quality. Run eval.py on the GGUF and report the drop; do not
assume it. A Q4 laptop result is a separate eval row (backend ollama), never merged with the bf16 numbers.
"""
import argparse
import datetime
import json
import os

from prompt import SYSTEM_PROMPT

REQUIRED_MERGED = ("config.json", "tokenizer_config.json")


def merged_ok(path):
    """Sanity check of a merged directory: config, tokenizer and at least one safetensors shard. Returns missing items."""
    missing = [f for f in REQUIRED_MERGED if not os.path.exists(os.path.join(path, f))]
    if not any(n.endswith(".safetensors") for n in (os.listdir(path) if os.path.isdir(path) else [])):
        missing.append("*.safetensors")
    return missing


def modelfile_text(gguf, temperature=0.0, num_ctx=4096):
    """Ollama Modelfile: the extraction system prompt baked in, deterministic decoding. The chat template is taken
    from the GGUF metadata that convert_hf_to_gguf.py copies from the tokenizer."""
    sysprompt = SYSTEM_PROMPT.replace('"""', "'''")
    return (f"FROM {gguf}\nPARAMETER temperature {temperature}\nPARAMETER num_ctx {num_ctx}\n"
            f'SYSTEM """{sysprompt}"""\n')


def merge(base, adapter, out, attn="auto"):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    kw = dict(torch_dtype=torch.bfloat16)
    if attn != "auto":  # newer transformers has no sdpa for Gemma 4's audio encoder: let it choose per module
        kw["attn_implementation"] = attn
    try:
        model = AutoModelForCausalLM.from_pretrained(base, **kw)
    except Exception as e:  # Gemma 4 card loads with AutoModelForMultimodalLM
        print("AutoModelForCausalLM failed:", repr(e)[:200], "-> AutoModelForMultimodalLM")
        from transformers import AutoModelForMultimodalLM
        model = AutoModelForMultimodalLM.from_pretrained(base, **kw)
    merged = PeftModel.from_pretrained(model, adapter).merge_and_unload()
    os.makedirs(out, exist_ok=True)
    merged.save_pretrained(out, safe_serialization=True)
    AutoTokenizer.from_pretrained(adapter if os.path.exists(os.path.join(adapter, "tokenizer_config.json")) else base).save_pretrained(out)
    json.dump({"base": base, "adapter": adapter, "dtype": "bfloat16", "torch": torch.__version__,
               "date": datetime.date.today().isoformat()}, open(os.path.join(out, "export_meta.json"), "w"), indent=2)
    missing = merged_ok(out)
    if missing:
        raise SystemExit(f"merged directory incomplete, missing {missing}")
    print("merged bf16 weights in", out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="LoRA adapter -> merged bf16 weights for vLLM")
    m.add_argument("--base", required=True); m.add_argument("--adapter", required=True); m.add_argument("--out", required=True)
    m.add_argument("--attn", default="auto")
    f = sub.add_parser("modelfile", help="write an Ollama Modelfile for a converted GGUF")
    f.add_argument("--gguf", required=True); f.add_argument("--out", default="Modelfile")
    c = sub.add_parser("check", help="check a merged directory is complete")
    c.add_argument("path")
    a = ap.parse_args()
    if a.cmd == "merge":
        merge(a.base, a.adapter, a.out, a.attn)
    elif a.cmd == "modelfile":
        open(a.out, "w").write(modelfile_text(a.gguf))
        print("wrote", a.out)
    else:
        miss = merged_ok(a.path)
        print("ok" if not miss else f"missing {miss}")
        raise SystemExit(1 if miss else 0)


if __name__ == "__main__":
    main()
