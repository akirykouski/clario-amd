# Дообучение модели Clario на AMD MI300X: инструкция

Для того, кто запускает дообучение. Читать сверху вниз. Если коротко: **поднять GPU-сервер → одна команда → проверить цифры → скопировать результаты → удалить сервер.**

**Перед стартом:** сделай `git pull`. В `deploy/amd/bootstrap.sh` 16.10 исправлены пути: без этого `--train` падал с «файл не найден» уже после сборки контейнера.

---

## 1. Что мы дообучаем и зачем (за 2 минуты)

**Задача модели.** Пациент пишет бытовым языком: *«Mi fanno male le ginocchia la mattina, niente febbre, mia madre ha il lupus»* («по утрам болят колени, температуры нет, у мамы волчанка»). Модель должна вернуть JSON по контракту `backend/clario/schemas/extraction_v3.json`:
- дословную цитату;
- клинический термин и его ID в онтологии HPO;
- отметки отрицания («температуры нет»), семейного анамнеза («у мамы»), начала и тяжести симптома.

**Модель.** Базовая — **Gemma 4 E4B** (`google/gemma-4-E4B-it`). Она маленькая, работает и на ноутбуке пациента. Дообучаем её LoRA-адаптером.

**Откуда данные.** Готового датасета «бытовой текст → HPO» нет: проверяли, в `docs/DATA_SOURCES.md`. Поэтому **генерируем сами, метки известны заранее**:
1. Берём болезнь из базы редких болезней (HPO + аннотации `phenotype.hpoa`, это Orphanet и OMIM).
2. Выбираем её симптомы и бытовые формулировки к ним (`train/lay_terms.json`).
3. Большая модель **Gemma 4 31B** на том же MI300X пишет запись дневника на английском или итальянском. Подмешиваем отрицания, родственников, жизненный шум и ловушки.
4. Код проверяет каждую строку. Если симптомы не выражены или есть лишние, строка отбрасывается, причина записывается.

Так правильный ответ известен до генерации, а не угадывается моделью-учителем. Это главное отличие от прошлого раза.

**Про «сначала нагенерить семплов» — да, именно так.** Порядок такой:

```
synth.py  →  prep.py  →  eval (база)  →  train_rocm.py (LoRA)  →  eval (LoRA)  →  сравнение
генерация    разбиение    до обучения     дообучение              после           base vs LoRA
```

`prep.py` делит данные так, что **одна болезнь попадает только в одну часть** (train, val или test). Тест проверяет, работает ли модель на болезнях, которых она не видела.

---

## 2. Что нужно заранее

- [ ] **Доступ к AMD Developer Cloud** (https://devcloud.amd.com) с кредитами (~$100), добавлен SSH-ключ.
- [ ] **Токен Hugging Face** (read-only), и на страницах моделей нажато **«принять лицензию»**:
  - https://huggingface.co/google/gemma-4-31B-it
  - https://huggingface.co/google/gemma-4-E4B-it

  Без этого скачивание весов упадёт с 401/403.
- [ ] **Бюджет.** MI300X стоит примерно **$2/час**, и **выключение сервера не останавливает оплату**, его нужно **удалить**. Полный прогон этой инструкции занимает около 2,5–4,5 часа, то есть примерно $5–9.

---

## 3. Поднять сервер

1. https://devcloud.amd.com → **Create GPU Droplet** → **1× MI300X**, образ **ROCm** или **vLLM Quick Start** (там уже есть Docker).
2. Firewall: входящие только 22 (твой IP), 80 и 443.
3. Подключиться:

```bash
ssh root@<IP_СЕРВЕРА>
git clone https://github.com/akirykouski/clario-amd.git clario && cd clario
export HF_TOKEN=hf_...        # только в переменную окружения, никогда не в файл и не в git
amd-smi || rocm-smi           # должен показать MI300X
```

---

## 4. Вариант А (рекомендуется): одна команда

```bash
deploy/amd/bootstrap.sh --synth 3000 --train --eval
```

Что произойдёт по шагам. Лог пишется в `deploy/amd/logs/bootstrap-<время>.log`.

| Этап | Что делает | Сколько (оценка) | Как понять, что всё хорошо |
|---|---|---|---|
| core | Проверяет GPU и Docker, качает образ vLLM, поднимает **Gemma 4 31B** (первый раз качает ~62 ГБ весов) | 30–60 мин | В логе `vllm-big healthy`, smoke-тест прошёл |
| `--synth 3000` | `train/synth.py` генерирует 3000 принятых строк через 31B, потом `prep.py` делит их | 30–60 мин | Есть `train/data/v3/train_sft.jsonl`, `val_sft.jsonl`, `test.jsonl` и `train/data/v3/SPLIT.md` |
| `--train` | Собирает контейнер `train/Dockerfile.rocm` и учит LoRA r16 на **E4B**, 3 эпохи, bf16 | 30–90 мин | Есть `train/out/e4b-r16/adapter/adapter_config.json` и `train/out/e4b-r16/metrics.json` |
| `--eval` | Поднимает E4B с адаптером и прогоняет тест для базы и для LoRA | ~15 мин | Есть `eval/results/extraction_base-e4b.json` и `extraction_ft-e4b-r16.json` |

Повторный запуск **пропускает готовые этапы**. Если что-то упало посередине, исправь и запусти ту же команду ещё раз. `FORCE=1` переделывает всё заново.

**Совет:** сначала сделай пробный запуск на 300 строк, чтобы убедиться, что весь стек работает, и только потом запускай 3000. Пробный запуск занимает минут 10 поверх core:

```bash
deploy/amd/bootstrap.sh --synth 300 --train --eval
# всё прошло → удаляем пробные данные, адаптер и результаты eval и запускаем полный прогон
rm -rf train/data/synth train/data/v3 train/out/e4b-r16 eval/results/extraction_*e4b*.json
deploy/amd/bootstrap.sh --synth 3000 --train --eval
```

Без удаления адаптера и результатов eval `--train` и `--eval` пропустятся как «уже готовые» после пробного запуска.

---

## 5. Как читать результаты

### 5.1 Данные (`synth`)

```bash
cat train/data/synth/synth.jsonl.stats.json   # сколько принято и отброшено и почему
cat train/data/v3/SPLIT.md                    # train/val/test, болезни не пересекаются
```

Если отбрасывается больше ~50%, пришли файл со статистикой. Значит, модель плохо следует инструкции, и стоит смотреть промпт.

### 5.2 Обучение (`train`)

```bash
cat train/out/e4b-r16/metrics.json   # train_wall_s, tokens_per_s, peak_mem_gb, train_loss
```

- **Loss должен падать** (`log_history` внутри файла).
- Для E2B/E4B лосс порядка **13–15** считается нормальным (это особенность Gemma 4 по данным Unsloth). Для 26B/31B норма **1–3**.

### 5.3 Сравнение моделей (`eval`), главное

```bash
python3 -c "import json;[print(l, {k: json.load(open(f'eval/results/extraction_{l}.json')).get(k) for k in ('entity_f1','hpo_id_accuracy','json_validity_rate','quote_grounding_rate','n')}) for l in ('base-e4b','ft-e4b-r16')]"
```

| Метрика | Что значит | Хотим |
|---|---|---|
| `entity_f1` | Насколько точно найдены симптомы | ft заметно выше base |
| `hpo_id_accuracy` | Правильный ли ID в онтологии | ft выше base |
| `json_validity_rate` | Доля ответов в правильном JSON | около 1.0 |
| `quote_grounding_rate` | Цитата действительно есть в тексте | около 1.0 |

**Правило решения.** Подключаем дообученную модель в демо, только если **ft лучше base** по F1 и HPO. Если нет, остаёмся на базовой Gemma 4 E4B, а результат честно показываем как есть.

### 5.4 ⚠️ Если на выходе мусор

Известная проблема Gemma 4 E2B/E4B: при выключенном кэше (`use_cache=False`) модель может отвечать бессмыслицей, см. `train/README.md`, раздел «Unsloth Gemma 4 gotchas». Если `json_validity_rate` у ft около 0, а у base нормальный, причина скорее всего здесь. Пришли лог, разберём.

---

## 6. Обязательно: забрать результаты и удалить сервер

**С ноутбука** (не с сервера) скопировать:

```bash
scp -r root@<IP>:clario/eval/results       ./results-eval     # extraction_base-e4b.json, extraction_ft-e4b-r16.json, train_e4b-r16.json
scp -r root@<IP>:clario/train/out/e4b-r16  ./e4b-r16          # адаптер + metrics.json
scp    root@<IP>:clario/train/data/v3/SPLIT.md ./SPLIT.md
scp    root@<IP>:clario/train/data/synth/synth.jsonl.stats.json ./synth-stats.json
scp -r root@<IP>:clario/deploy/amd/logs    ./bootstrap-logs
```

**Адаптер сохранить на Hugging Face.** Он понадобится позже для демо, а сервер мы удалим:

```bash
# на сервере, пока он жив (токен должен иметь право записи; можно отдельный)
pip install -U "huggingface_hub[cli]"   # если команды huggingface-cli нет
huggingface-cli upload <твой-hf-аккаунт>/clario-extract-e4b-lora train/out/e4b-r16/adapter --private
```

**В репозиторий закоммитить** только JSON-результаты: `eval/results/*.json` (эти маленькие файлы — источник всех цифр в README и на слайдах). Сами данные и адаптер в git **не кладём**: `train/data/` и `train/out/` и так в `.gitignore`.

Потом:
1. В панели AMD Developer Cloud → **Destroy droplet**. Не Power off, именно Destroy.
2. Проверить в панели, что сервер исчез и списание остановилось.

---

## 7. Вариант Б: вручную по шагам (если bootstrap упал и нужно разобраться)

Подробно описано в `train/README.md`, раздел «MI300X droplet, step by step». Коротко:

```bash
# 1. контейнер для обучения
cd train
docker build -f Dockerfile.rocm -t clario-train .
docker run -it --rm --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host --shm-size 64G \
  --security-opt seccomp=unconfined -v $PWD:/workspace/train -v $HOME/hf-cache:/workspace/hf-cache -e HF_TOKEN clario-train
python -c "import torch;print(torch.__version__, torch.version.hip, torch.cuda.get_device_name(0))"   # должен показать MI300X

# 2. генерация (нужен поднятый vLLM с Gemma 4 31B на :8000, его поднимает bootstrap core)
python synth.py --base-url http://localhost:8000/v1 --model google/gemma-4-31B-it --api-key-env VLLM_API_KEY --n 3000 --concurrency 32
python prep.py

# 3. обучение
python train_rocm.py --model google/gemma-4-E4B-it --out out/e4b-r16 --epochs 3 --bf16

# 4. оценка (vLLM с адаптером)
vllm serve google/gemma-4-E4B-it --enable-lora --max-lora-rank 16 --lora-modules clario-extract=out/e4b-r16/adapter --max-model-len 8192 --port 8001
python eval.py --base-url http://localhost:8001/v1 --model google/gemma-4-E4B-it --label base-e4b --backend vllm-rocm-mi300x --confidence
python eval.py --base-url http://localhost:8001/v1 --model clario-extract     --label ft-e4b-r16 --backend vllm-rocm-mi300x --confidence
```

`--confidence` просит модель вернуть уверенность. Из этого строится график «сколько терминов уходит врачу на проверку при допустимой ошибке 1/2/5%»: `python ../eval/review_curve.py`. Это сильная цифра для питча, если успеваем.

**Если остаётся время и кредиты** (не обязательно):
- **Больше данных:** `--synth 10000`.
- **Модель побольше:** `--model google/gemma-4-26B-A4B-it` (MoE), см. шаг 7 в `train/README.md`.
- **GRPO с наградой за калибровку** (`train_grpo.py`, шаг 9 в `train/README.md`). Это рискованно по времени.

---

## 8. Частые проблемы

| Симптом | Что сделать |
|---|---|
| 401/403 при скачивании модели | Не принята лицензия Gemma на HF или не экспортирован `HF_TOKEN` |
| vLLM падает на старте из-за attention | `export VLLM_ATTENTION_BACKEND=TRITON_ATTN` и перезапустить bootstrap |
| Образ vLLM не запускает Gemma 4 | `export VLLM_IMAGE=vllm/vllm-openai-rocm:latest` |
| Модель долго грузится, таймаут | `export WAIT_SECS=4000`; логи: `docker compose -f deploy/amd/docker-compose.yml logs vllm-big` |
| vLLM не принимает LoRA-адаптер | Обучить с `--merge` и подать склеенную модель `train/out/e4b-r16/merged` (см. Troubleshooting в `deploy/amd/README.md`) |
| Нехватка памяти GPU (OOM) | Убедиться, что `vllm-small` остановлен во время обучения (bootstrap делает это сам); уменьшить `--max-len` |
| `json_validity_rate` у ft около 0 | См. раздел 5.4 (кэш у Gemma 4 E4B) |

---

## 9. Правила (важно для судей)

- **Только синтетические данные.** Никаких реальных медицинских данных.
- **Обучающие данные генерирует только Gemma на нашем vLLM.** Claude используется лишь как строка сравнения в оценке, его ответы никогда не попадают в обучение (`synth.py` сам отказывается работать с эндпоинтами Anthropic).
- **Токены и ключи только в переменных окружения**, никогда в файлах и в git.
- **Любая цифра в README и на слайдах берётся из `eval/results/*.json`.** Нет файла, нет цифры.
- **Сервер удалить сразу после копирования результатов.**

После прогона пришли в чат четыре файла: `extraction_base-e4b.json`, `extraction_ft-e4b-r16.json`, `train_e4b-r16.json` и `synth-stats.json`. По ним заполним README и слайды.
