"""M4: GRPO with a calibration-aware reward (RLCR style) on top of the SFT model. NOT RUN YET: written and
statically checked only. No GPU here. The reward functions below are plain stdlib Python and are unit-tested
on toy outputs (test_grpo.py); the trainer wiring (TRL GRPOTrainer, ROCm) is unverified until the first droplet run.

Idea (RLCR, "Beyond Binary Rewards: Training LMs to Reason About Their Uncertainty", arXiv:2507.16806): add a
Brier penalty on the model's stated confidence to the correctness reward, so the model gets more accurate and
better calibrated at once. Here the unit is one extracted entity:

    reward = 1.0 * F1(entity set vs gold, HPO id)
           + 0.25 * grounding            share of predicted quotes that are verbatim in the diary
           + 0.25 * flag accuracy        negation and family_history right on matched entities
           - 0.50 * hallucination rate   share of predicted entities with an ungrounded quote
           - 0.50 * Brier                mean (confidence - correct)^2 over predicted entities; a missing
                                         confidence counts as Brier 1, so the model must emit it
           - 1.00 if the output is not valid extraction JSON (then every other term is 0)

An entity is "correct" when it is a true positive under the HPO-id match used by eval.py.

Run on the droplet, starting from the merged SFT weights (see train_rocm.py --merge):

    python train_grpo.py --model out/a4b-r16/merged --data data/v3/train.jsonl --out out/a4b-grpo
    python train_grpo.py --dry-run          # no torch, no model: build the dataset rows and score toy completions
"""
import argparse
import json
import os

from eval import _prf, calibration, ekey, grounded, match_counts, pair_entities, pred_correct
from prompt import build_messages, from_dataset_entities, parse

WEIGHTS = {"f1": 1.0, "grounding": 0.25, "flags": 0.25, "halluc": 0.5, "brier": 0.5, "format": 1.0}


def completion_text(c):
    """TRL passes a string (standard format) or a list of chat messages (conversational format)."""
    if isinstance(c, str):
        return c
    if isinstance(c, (list, tuple)) and c:
        last = c[-1]
        return last.get("content", "") if isinstance(last, dict) else str(last)
    return ""


def components(diary, gold, text):
    """Reward terms for one completion. All in [0, 1] except `valid`; penalties are returned as positive rates."""
    pred = parse(text)
    if pred is None:
        return {"valid": 0.0, "f1": 0.0, "grounding": 0.0, "flags": 0.0, "halluc": 0.0, "brier": 0.0}
    _, _, f1 = _prf(*match_counts(gold, pred, ekey))
    if pred:
        ground = [grounded(diary, e["quote"]) for e in pred]
        grounding = sum(ground) / len(pred)
        halluc = 1.0 - grounding
        flags = flag_accuracy(gold, pred)
        correct = pred_correct(gold, pred)
        brier = brier_of(pred, correct)
    else:
        grounding, halluc, brier = 1.0, 0.0, 0.0
        flags = 1.0 if not gold else 0.0
    return {"valid": 1.0, "f1": f1, "grounding": grounding, "flags": flags, "halluc": halluc, "brier": brier}


def brier_of(pred, correct):
    """Mean (confidence - correct)^2 over predicted entities; a missing confidence counts as 1 (worst case)."""
    return sum(1.0 if e["confidence"] is None else (e["confidence"] - ok) ** 2
               for e, ok in zip(pred, correct)) / len(pred)


def flag_accuracy(gold, pred):
    """Share of matched (gold, pred) pairs whose negated and family_history flags both agree. 0 when nothing matches
    but gold has entities, 1 when both are empty."""
    pairs = pair_entities(gold, pred)
    if not pairs:
        return 1.0 if not gold and not pred else 0.0
    return sum(bool(g.get("negated")) == bool(p.get("negated")) and bool(g.get("family_history")) == bool(p.get("family_history"))
               for g, p in pairs) / len(pairs)


def total(comp, w=WEIGHTS):
    if not comp["valid"]:
        return -w["format"]
    return (w["f1"] * comp["f1"] + w["grounding"] * comp["grounding"] + w["flags"] * comp["flags"]
            - w["halluc"] * comp["halluc"] - w["brier"] * comp["brier"])


def reward_total(diary, gold, text, w=WEIGHTS):
    return total(components(diary, gold, text), w)


def _gold(g):
    return from_dataset_entities(json.loads(g) if isinstance(g, str) else g)


def _make(term):
    """Build one TRL reward function that returns a single component, so each shows up in the training logs."""
    sign = -1.0 if term in ("halluc", "brier") else 1.0

    def fn(prompts=None, completions=None, diary=None, gold=None, **kw):
        out = []
        for d, g, c in zip(diary, gold, completions):
            comp = components(d, _gold(g), completion_text(c))
            out.append(-WEIGHTS["format"] if term == "format" and not comp["valid"] else
                       0.0 if term == "format" else sign * comp[term])
        return out
    fn.__name__ = f"reward_{term}"
    return fn


# Order matches REWARD_WEIGHTS; pass both to GRPOTrainer / GRPOConfig(reward_weights=...)
REWARD_FUNCS = [_make(t) for t in ("f1", "grounding", "flags", "halluc", "brier", "format")]
REWARD_WEIGHTS = [WEIGHTS["f1"], WEIGHTS["grounding"], WEIGHTS["flags"], WEIGHTS["halluc"], WEIGHTS["brier"], 1.0]


def reward_calibration(diary, gold, completions):
    """Diagnostic, not a reward: ECE of stated confidence over a batch (None if no confidence was stated)."""
    pts = []
    for d, g, c in zip(diary, gold, completions):
        pred = parse(completion_text(c))
        if pred:
            pts += [(e["confidence"], int(ok)) for e, ok in zip(pred, pred_correct(_gold(g), pred)) if e["confidence"] is not None]
    return calibration(pts)[0]


def load_rows(path, limit=0):
    """data/v3/train.jsonl -> GRPO rows: conversational prompt (with the confidence prompt), diary, gold as JSON text."""
    rows = []
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append({"prompt": build_messages(r["diary"], confidence=True), "diary": r["diary"],
                     "gold": json.dumps(from_dataset_entities(r["target"]["entities"]), ensure_ascii=False)})
        if limit and len(rows) >= limit:
            break
    return rows


def dry_run(path):
    rows = load_rows(path, 3) if os.path.exists(path) else []
    toy_gold = [{"quote": "red cheeks", "canonical": "Malar rash", "hpo_id": "HP:0000469", "type": "symptom",
                 "negated": False, "family_history": False, "onset_hint": None, "severity": None, "confidence": None}]
    diary = "red cheeks since Tuesday, no fever"
    good = json.dumps({"entities": [{**toy_gold[0], "confidence": 0.9}]})
    bad = json.dumps({"entities": [{**toy_gold[0], "hpo_id": "HP:0001945", "confidence": 0.9}]})
    print("rows loaded:", len(rows))
    for name, txt in (("correct, confident", good), ("wrong id, confident", bad), ("not json", "no")):
        print(f"{name:22s} reward {reward_total(diary, toy_gold, txt):+.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="out/a4b-r16/merged", help="merged SFT weights (train_rocm.py --merge) or a hub id")
    ap.add_argument("--data", default="data/v3/train.jsonl")
    ap.add_argument("--out", default="out/grpo")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rank", type=int, default=16); ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--num-generations", type=int, default=8)
    ap.add_argument("--bsz", type=int, default=8, help="per-device; bsz * grad-accum must be divisible by --num-generations")
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--max-completion", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--beta", type=float, default=0.0, help="KL weight; 0 skips the reference model")
    ap.add_argument("--use-vllm", action="store_true", help="colocated vLLM generation (needs a working vLLM ROCm build; unverified)")
    ap.add_argument("--attn", default="sdpa")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--dry-run", action="store_true", help="no torch: build rows and score toy completions")
    a = ap.parse_args()
    if a.dry_run:
        return dry_run(a.data)

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import GRPOConfig, GRPOTrainer

    os.makedirs(a.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(a.model)
    kw = dict(torch_dtype=torch.bfloat16, attn_implementation=a.attn)
    try:
        model = AutoModelForCausalLM.from_pretrained(a.model, **kw)
    except Exception as e:  # Gemma 4 card loads with AutoModelForMultimodalLM
        print("AutoModelForCausalLM failed:", repr(e)[:200], "-> AutoModelForMultimodalLM")
        from transformers import AutoModelForMultimodalLM
        model = AutoModelForMultimodalLM.from_pretrained(a.model, **kw)
    ds = Dataset.from_list(load_rows(a.data, a.limit))
    cfg = GRPOConfig(output_dir=a.out, learning_rate=a.lr, max_steps=a.steps, per_device_train_batch_size=a.bsz,
                     gradient_accumulation_steps=a.grad_accum, num_generations=a.num_generations,
                     max_completion_length=a.max_completion, temperature=a.temperature, beta=a.beta,
                     reward_weights=REWARD_WEIGHTS, bf16=True, logging_steps=5, save_steps=100, save_total_limit=2,
                     gradient_checkpointing=True, seed=a.seed, report_to="none", log_completions=True,
                     use_vllm=a.use_vllm, **({"vllm_mode": "colocate"} if a.use_vllm else {}))
    peft_cfg = LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.0, target_modules="all-linear",
                          task_type="CAUSAL_LM", bias="none")
    trainer = GRPOTrainer(model=model, reward_funcs=REWARD_FUNCS, args=cfg, train_dataset=ds,
                          processing_class=tok, peft_config=peft_cfg)
    res = trainer.train()
    trainer.save_model(os.path.join(a.out, "adapter")); tok.save_pretrained(os.path.join(a.out, "adapter"))
    json.dump({"model": a.model, "steps": a.steps, "train_loss": res.training_loss, "weights": WEIGHTS,
               "gpu": torch.cuda.get_device_name(0), "log_history": trainer.state.log_history},
              open(os.path.join(a.out, "metrics.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
