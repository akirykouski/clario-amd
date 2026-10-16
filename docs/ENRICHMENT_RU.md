# Обогащение и генерация данных через AMD Token Factory: инструкция

Для того, кто готовит данные для дообучения. Результат этой части — **готовый датасет**, который потом забирает тот, кто дообучает модель (см. `docs/FINETUNE_RU.md`).

**Что нужно:** обычный ноутбук. **GPU не нужен:** всю тяжёлую работу делает Gemma 4 31B на серверах AMD через API Token Factory. Это бонус для судей: данные сгенерированы на AMD.

```
lay_expand.py      →      synth.py      →      prep.py      →   передать датасет
бытовой словарь           записи дневника       train/val/test     тому, кто дообучает
(~800 терминов)           (~3000 записей)
```

---

## 1. Зачем это всё (2 минуты)

Модель должна понимать бытовую речь пациента («my knee is so itchy», «fingers go white in the cold») и превращать её в медицинские термины HPO. Готового датасета «бытовой текст → HPO» нет, поэтому делаем свой, **с правильными ответами по построению**:

1. **Бытовой словарь** (`train/lay_expand.py`). В HPO на термин в среднем 1,8 «бытовых» синонима, и они звучат по-врачебному. Gemma пишет по ~10 вариантов, как термин описал бы обычный человек: подросток, пенсионер, с привязкой к месту, с опечатками. Каждый вариант проходит две проверки:
   - **код:** нет медицинских слов и копии термина;
   - **слепая обратная проверка:** модель видит фразу и 5 похожих терминов вперемешку и должна угадать исходный.

   Что не прошло, выбрасывается.
2. **Записи дневника** (`train/synth.py`). Берём болезнь из базы редких болезней (HPO + Orphanet/OMIM), её симптомы, формулировки из словаря и «голос» автора. Gemma пишет запись, код проверяет, что каждый симптом процитирован дословно, отрицания и родственники распознаются правильно, лишнего нет.
3. **Разбиение** (`train/prep.py`). Одна болезнь попадает только в одну часть: train, val или test. Так тест честно проверяет болезни, которых модель не видела.

---

## 2. Подготовка (один раз)

**2.1 Код и окружение**

```powershell
git clone https://github.com/akirykouski/clario-amd.git
cd clario-amd\backend
uv sync
cd ..\train
```

Если репозиторий уже есть, достаточно `git pull`. Нужен `uv` (`pip install uv`) и Python 3.12.

**2.2 Ключ и адрес Token Factory**

- **Ключ:** https://notebooks.amd.com/tokenfactory → «Your API key». Ключ один на команду.
- **Адрес API (base URL) и точное имя модели:** в «User Manual» на той же странице.

Ключ **только в переменную окружения**, никогда не в файл, не в git и не в общий чат.

```powershell
# PowerShell (Windows)
$env:TF_API_KEY  = "rc-..."
$env:TF_BASE_URL = "<base URL из User Manual, обычно оканчивается на /v1>"
```
```bash
# macOS / Linux
export TF_API_KEY=rc-...
export TF_BASE_URL="<base URL из User Manual>"
```

**2.3 Проверка, что всё работает (1 минута)**

```powershell
uv run --project ../backend python -c "import os; from openai import OpenAI; c=OpenAI(base_url=os.environ['TF_BASE_URL'], api_key=os.environ['TF_API_KEY']); print([m.id for m in c.models.list().data])"
```

В списке должна быть Gemma 4 31B. **Запиши её точное имя** (например `Gemma-4-31B-IT`), дальше оно идёт в `--model`. Потом пробный запрос:

```powershell
uv run --project ../backend python -c "import os; from openai import OpenAI; c=OpenAI(base_url=os.environ['TF_BASE_URL'], api_key=os.environ['TF_API_KEY']); print(c.chat.completions.create(model='Gemma-4-31B-IT', messages=[{'role':'user','content':'Say hi in 3 words'}]).choices[0].message.content)"
```

Если вернулся ответ, всё готово.

---

## 3. ⚠️ Лимиты: один ключ на всю команду

«Shared rate limits: All limits (RPM, concurrency, daily spend) are per key, not per person». Значит:
- **Не запускай параллельно** с кем-то ещё из команды, кто тоже ходит в Token Factory (например, демо-приложение).
- Держи **`--concurrency 4`** и **`--max-retries 8`**: скрипты сами подождут и повторят запрос при ошибке 429 («слишком много запросов»).
- Расход смотри на странице Token Factory → **Check Usage**. Если дневной бюджет кончится, всё встанет до завтра, а дедлайн 18.10 в 12:00.

Порядок объёма: словарь на 800 терминов — это около 1600 запросов, 3000 записей — около 3000–4000 запросов (часть отбраковывается). Поэтому сначала пробные маленькие запуски.

---

## 4. Шаг 1: бытовой словарь

**Пробный запуск (20 терминов, пара минут):**

```powershell
uv run --project ../backend python lay_expand.py --base-url $env:TF_BASE_URL --api-key-env TF_API_KEY --model Gemma-4-31B-IT --terms 20 --concurrency 4 --max-retries 8
```

Посмотри результат:

```powershell
Get-Content lay_lexicon.json.stats.json
uv run --project ../backend python -c "import json;d=json.load(open('lay_lexicon.json'));[print(k, d[k][:5]) for k in list(d)[:8]]"
```

- Фразы должны звучать как живые люди, а не как справочник.
- В статистике `verified` (прошло обратную проверку) должно быть хотя бы около трети от `code_ok`. Если меньше, пришли `lay_lexicon.json.stats.json` в чат, подкрутим.

**Полный запуск** продолжает с того же места, пробные 20 терминов не пропадут:

```powershell
uv run --project ../backend python lay_expand.py --base-url $env:TF_BASE_URL --api-key-env TF_API_KEY --model Gemma-4-31B-IT --terms 800 --concurrency 4 --max-retries 8
```

Если оборвалось (сеть, лимит), просто запусти ту же команду ещё раз: готовые термины пропускаются, файл сохраняется каждые 200 терминов.

**Результат:** `train/lay_lexicon.json` и `train/lay_lexicon.json.stats.json`.

---

## 5. Шаг 2: записи дневника

`synth.py` сам подхватит `lay_lexicon.json`, если он лежит в `train/`.

**Пробный запуск (50 записей):**

```powershell
uv run --project ../backend python synth.py --base-url $env:TF_BASE_URL --api-key-env TF_API_KEY --model Gemma-4-31B-IT --n 50 --concurrency 4 --max-retries 8 --out data/synth/pilot.jsonl
Get-Content data/synth/pilot.jsonl.stats.json
```

Открой `data/synth/pilot.jsonl` и прочитай 5–10 записей: должно звучать как дневник живого человека, без медицинских слов. В `reject_reasons` видно, почему строки отбракованы. Если отбраковано больше половины, пришли файл со статистикой.

**Полный запуск:**

```powershell
Remove-Item data/synth/pilot.jsonl*            # пилот в датасет не берём
uv run --project ../backend python synth.py --base-url $env:TF_BASE_URL --api-key-env TF_API_KEY --model Gemma-4-31B-IT --n 3000 --concurrency 4 --max-retries 8
```

Повторный запуск дописывает недостающее до 3000.

**Результат:** `train/data/synth/synth.jsonl` и `synth.jsonl.stats.json`.

---

## 6. Шаг 3: разбиение

```powershell
uv run --project ../backend python prep.py
Get-Content data/v3/SPLIT.md
```

**Результат:** папка `train/data/v3/` (`train.jsonl`, `val.jsonl`, `test.jsonl`, `*_sft.jsonl`, `SPLIT.md`). В `SPLIT.md` проверь, что болезни не пересекаются между частями.

---

## 7. Шаг 4: передать результат

1. **Словарь в git:**
   ```powershell
   git add lay_lexicon.json lay_lexicon.json.stats.json
   git commit -m "Lay lexicon from Gemma 4 31B on AMD Token Factory"
   git push
   ```
2. **Словарь в приложение** (поиск терминов начнёт понимать бытовые фразы):
   ```powershell
   Copy-Item lay_lexicon.json ..\backend\clario\data\lay_lexicon_en.json
   cd ..\backend; uv run python -m pytest -q; cd ..\train
   ```
   Если тесты зелёные, закоммить и этот файл. Если покраснели, не коммить и напиши в чат.
3. **Датасет тому, кто дообучает.** В git его **не кладём** (`train/data/` в `.gitignore`). Варианты:
   - заархивировать `train/data/v3/` и переслать;
   - для Kaggle загрузить как приватный Kaggle Dataset (Kaggle → Datasets → New Dataset → загрузить папку `v3`, видимость Private).
4. **Скинь в чат** `lay_lexicon.json.stats.json`, `synth.jsonl.stats.json` и `SPLIT.md`.

---

## 8. Если что-то не так

| Симптом | Что сделать |
|---|---|
| `401` / `403` | Неверный ключ или не тот base URL. Проверь `$env:TF_API_KEY` и User Manual |
| `404 model not found` | Имя модели не совпадает. Возьми точное из списка в шаге 2.3 |
| Много `RateLimitError` в выводе | Снизь `--concurrency` до 2; проверь, не гоняет ли кто-то ещё ключ одновременно |
| Встало и не двигается | Посмотри Check Usage: возможно, кончился дневной бюджет |
| `verified` очень мало в словаре | Пришли статистику: ослабим обратную проверку |
| В записях медицинские слова | Пришли 3 примера: подкрутим промпт |
| `ModuleNotFoundError: clario` | Запускай из папки `train` через `uv run --project ../backend python …` |

## 9. Правила

- **Только синтетика.** Никаких реальных медицинских данных.
- **Данные генерирует только Gemma** (открытая модель). Claude для обучающих данных нельзя, скрипты сами отказываются работать с API Anthropic.
- **Ключ только в переменной окружения.**
- **Любая цифра в README и на слайдах берётся из файлов результатов.**
