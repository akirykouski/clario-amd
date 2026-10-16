# Дообучение модели Clario: инструкция (своя видеокарта или Kaggle)

Для того, кто дообучает модель. **На входе** — датасет из `docs/ENRICHMENT_RU.md` (папка `train/data/v3/`). **На выходе** — LoRA-адаптер и честное сравнение «база против дообученной».

```
оценка базы  →  дообучение (LoRA, 4 бита)  →  оценка дообученной  →  сравнение  →  отдать результаты
```

**Перед стартом:** `git pull`. 16.10 в `train/train_rocm.py` добавлен режим для карт на 16 ГБ (`--load-in-4bit`, точность выбирается сама), а в `train/eval.py` — оценка прямо на видеокарте (`--hf-model`), без всякого API.

---

## 1. Что дообучаем (1 минута)

- **Модель:** Gemma 4 E4B (`google/gemma-4-E4B-it`), маленькая и рассчитана на работу на устройстве пациента.
- **Задача:** запись дневника на бытовом языке → JSON по контракту `backend/clario/schemas/extraction_v3.json`. В нём дословная цитата, медицинский термин и его ID в HPO, а также отметки «нет симптома», «у родственника», начало и тяжесть.
- **Способ:** QLoRA. Базовая модель загружается в 4 битах, учится маленький адаптер (rank 16). Так всё влезает в 16 ГБ видеопамяти. В прошлый раз было так же, но на 343 примерах, теперь их около 2400 и они качественнее.

---

## 2. Что нужно заранее

- [ ] **Датасет:** папка `v3` от того, кто делал обогащение (`train.jsonl`, `val.jsonl`, `test.jsonl`, `train_sft.jsonl`, `val_sft.jsonl`, `test_sft.jsonl`, `SPLIT.md`).
- [ ] **Hugging Face:** read-токен, и на https://huggingface.co/google/gemma-4-E4B-it нажато «принять лицензию». Без этого скачивание упадёт с 401/403.
- [ ] **Видеокарта:**
  - **Вариант А, своя NVIDIA карта** от 16 ГБ, лучше серии RTX 30xx и новее (там есть bf16). **Рекомендуется.**
  - **Вариант Б, Kaggle:** бесплатная T4 на 16 ГБ, до 30 часов в неделю. На T4 нет bf16, только fp16: работает, но медленнее и капризнее (см. раздел 8).

---

## 3. Вариант А: своя видеокарта

**3.1 Окружение (один раз)**

```powershell
git clone https://github.com/akirykouski/clario-amd.git   # или git pull, если уже есть
cd clario-amd\train
python -m venv .venv-train
.\.venv-train\Scripts\activate                              # macOS/Linux: source .venv-train/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu128   # версию CUDA подбери: https://pytorch.org/get-started/locally/
pip install -r requirements-cuda.txt
huggingface-cli login                                       # вставить HF read-токен
python -c "import torch;print(torch.cuda.get_device_name(0), torch.cuda.is_bf16_supported())"
```

**3.2 Датасет:** положи полученную папку так, чтобы был путь `clario-amd/train/data/v3/train_sft.jsonl`.

**3.3 Пробный прогон (10–15 минут):** проверяет, что весь стек работает.

```powershell
python eval.py --hf-model google/gemma-4-E4B-it --load-in-4bit --label smoke-base --limit 5
python train_rocm.py --model google/gemma-4-E4B-it --out out/smoke --epochs 0.05 --load-in-4bit --bsz 2 --grad-accum 4
python eval.py --hf-model google/gemma-4-E4B-it --adapter out/smoke/adapter --load-in-4bit --label smoke-ft --limit 5
```

Всё прошло без ошибок → удали пробное: `out/smoke`, `../eval/results/extraction_smoke-*.json`, `../eval/results/train_smoke.json`.

**3.4 Основной прогон**

```powershell
# 1. база: как модель справляется без дообучения (примерно 20–40 мин)
python eval.py --hf-model google/gemma-4-E4B-it --load-in-4bit --label base-e4b --confidence

# 2. дообучение (примерно 1–2 часа на RTX)
python train_rocm.py --model google/gemma-4-E4B-it --out out/e4b-r16 --epochs 2 --load-in-4bit --bsz 2 --grad-accum 8

# 3. дообученная модель на том же тесте
python eval.py --hf-model google/gemma-4-E4B-it --adapter out/e4b-r16/adapter --load-in-4bit --label ft-e4b-r16 --confidence
```

`--confidence` просит модель вернуть уверенность. Из этого потом строится график «сколько терминов уходит врачу на проверку».

---

## 4. Вариант Б: Kaggle

**4.1 Настройка ноутбука**
1. Kaggle → **Create → New Notebook**.
2. Справа в **Settings**: Accelerator **GPU T4 x2** (используется одна), **Internet: On**.
3. **Add-ons → Secrets** → добавь `HF_TOKEN` со своим read-токеном.
4. **Add Input** → твой приватный Kaggle Dataset с папкой `v3`.

**4.2 Ячейки ноутбука по порядку**

```python
!git clone https://github.com/akirykouski/clario-amd.git
%cd clario-amd/train
!pip install -q -U -r requirements-cuda.txt
```
```python
from kaggle_secrets import UserSecretsClient
import os
os.environ["HF_TOKEN"] = UserSecretsClient().get_secret("HF_TOKEN")
```
```python
# путь к датасету посмотри в правой панели (Input); обычно /kaggle/input/<имя-датасета>/v3
!mkdir -p data && cp -r /kaggle/input/<имя-датасета>/v3 data/v3 && ls data/v3
```
```python
!python eval.py --hf-model google/gemma-4-E4B-it --load-in-4bit --label smoke-base --limit 5
!python train_rocm.py --model google/gemma-4-E4B-it --out out/smoke --epochs 0.05 --load-in-4bit --bsz 2 --grad-accum 4
```

Пробный прогон прошёл → основной:

```python
!python eval.py --hf-model google/gemma-4-E4B-it --load-in-4bit --label base-e4b --confidence --limit 150
!python train_rocm.py --model google/gemma-4-E4B-it --out out/e4b-r16 --epochs 2 --load-in-4bit --bsz 2 --grad-accum 8
!python eval.py --hf-model google/gemma-4-E4B-it --adapter out/e4b-r16/adapter --load-in-4bit --label ft-e4b-r16 --confidence --limit 150
```

`--limit 150`: на T4 генерация медленная, 150 тестовых записей хватит для сравнения. В README честно пишем `n=150`.

**4.3 Сохранить результат:** сессия Kaggle исчезает после закрытия.

```python
!mkdir -p /kaggle/working/out && cp -r out/e4b-r16 /kaggle/working/out/ && cp -r ../eval/results /kaggle/working/results
```

Потом справа **Output** → скачать `out/e4b-r16` (адаптер) и `results`.

Сессия Kaggle ограничена 12 часами. При обрыве `train_rocm.py` сохраняет чекпоинт каждую эпоху в `out/e4b-r16/checkpoint-*`.

---

## 5. Дополнительно: сравнение с Gemma 4 31B на AMD (с ноутбука, 5 минут)

Сильная строка для слайда: «маленькая дообученная модель на устройстве против большой Gemma 4 31B на AMD». Запускается с любого компьютера через Token Factory, переменные `TF_API_KEY` и `TF_BASE_URL` см. в `docs/ENRICHMENT_RU.md`:

```powershell
cd clario-amd\train
uv run --project ../backend python eval.py --base-url $env:TF_BASE_URL --api-key-env TF_API_KEY --model Gemma-4-31B-IT --label tf-gemma4-31b --backend amd-token-factory --confidence --concurrency 2 --limit 150
```

Лимиты ключа общие на команду: не запускай одновременно с генерацией данных.

---

## 6. Как читать результаты

```powershell
cd clario-amd
python -c "import json;[print(l, {k: json.load(open(f'eval/results/extraction_{l}.json')).get(k) for k in ('entity_f1','hpo_id_accuracy','negation_accuracy','json_validity_rate','quote_grounding_rate','n')}) for l in ('base-e4b','ft-e4b-r16','tf-gemma4-31b')]"
python -c "import json;m=json.load(open('eval/results/train_e4b-r16.json'));print({k:m.get(k) for k in ('train_wall_s','train_loss','peak_mem_gb','gpu','precision')})"
```

| Метрика | Что значит | Хотим |
|---|---|---|
| `entity_f1` | Насколько точно найдены симптомы | ft заметно выше base |
| `hpo_id_accuracy` | Правильный ли ID термина | ft выше base |
| `negation_accuracy` | «Температуры нет» не путается с температурой | высоко |
| `json_validity_rate` | Ответ в правильном JSON | около 1.0 |
| `quote_grounding_rate` | Цитата действительно есть в тексте | около 1.0 |

**Правило решения:** дообученную модель берём, только если она **лучше базы** по F1 и HPO. Если нет, честно показываем как есть.

**Лосс при обучении:** для E4B по данным Unsloth нормально около 13–15, главное, чтобы он **падал** (`log_history` в `out/e4b-r16/metrics.json`).

---

## 7. Отдать результаты

1. **В git** (маленькие JSON, источник всех цифр в README и на слайдах):
   ```powershell
   git add eval/results/extraction_base-e4b.json eval/results/extraction_ft-e4b-r16.json eval/results/train_e4b-r16.json
   git add eval/results/extraction_tf-gemma4-31b.json     # если делал раздел 5
   git commit -m "Fine-tune results: base vs LoRA (Gemma 4 E4B)"
   git push
   ```
2. **Адаптер на Hugging Face** (в git **не кладём**, он большой):
   ```powershell
   huggingface-cli upload <твой-hf-аккаунт>/clario-extract-e4b-lora train/out/e4b-r16/adapter --private
   ```
   Для загрузки нужен токен с правом записи.
3. **Скинь в чат:** три файла результатов и строчку «на чём учил» (видеокарта или Kaggle T4, время).

---

## 8. Частые проблемы

| Симптом | Что сделать |
|---|---|
| 401/403 при скачивании модели | Не принята лицензия Gemma 4 E4B на HF или не выполнен вход (`huggingface-cli login` / `HF_TOKEN`) |
| Ошибка «Gemma 4 / gemma4 не поддерживается» | `pip install -U transformers` (нужна свежая версия) |
| Нехватка памяти (CUDA out of memory) | `--bsz 1 --grad-accum 16`; если не помогло, добавь `--max-len 1024` |
| На Kaggle лосс стал `nan` | fp16 на T4 и Gemma иногда не дружат. Попробуй `--lr 1e-4`; если не помогло, учим на своей карте |
| У ft `json_validity_rate` около 0, у base нормальный | Известная проблема Gemma 4 E4B с кэшем, см. `train/README.md` («Unsloth Gemma 4 gotchas»). Пришли лог |
| `bitsandbytes` не ставится на Windows | `pip install -U bitsandbytes`; если не вышло, Kaggle или WSL |
| Оценка идёт очень долго | `--limit 150` (и в README честно указать n) |

## 9. Правила

- **Только синтетические данные** из `data/v3`. Никаких реальных медданных.
- **Токены только в переменных окружения или Kaggle Secrets**, не в коде и не в git.
- **Любая цифра в README и на слайдах берётся из `eval/results/*.json`.**

---

*Если всё-таки дадут сервер AMD MI300X, тот же пайплайн запускается одной командой на нём: см. `deploy/amd/README.md` (`bootstrap.sh --lay --synth 3000 --train --eval`).*
