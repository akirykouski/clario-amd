# Demo video script

**[Вступление]**

How many of those stories have you scrolled past on social media this year? Probably more than you can remember. These aren't outliers. There are 300 million people living right now in the world with a rare disease. Half of them are children. And the average time for a diagnosis is over 5 years, 10 if you are a teenager. But here is what's cruel about this. An answer is usually already there. It lies in the photos, voice memos, notes. Rare diseases hide in plain sight. One symptom looks like a flu, the other like stress. The pattern is there. It just has to be seen all at once.

---

**[Главный экран, ввод пароля]**

This is Giulia. For two months she's had a rash, aching joints and mouth sores, and nobody has connected them yet. Clario is her private health diary. It opens only with her passphrase, and everything inside stays encrypted on her own device.

**[Пишет или надиктовывает заметку: симптомы и то, что хочет спросить у врача]**

She writes the way she talks. How today went, what hurts, what she wants to ask her doctor. No forms, no medical words.

Gemma 4 reads the note and turns her words into clinical terms. "My cheeks went red" becomes "malar rash", and each term keeps the exact words it came from, so nothing is invented. Before any text reaches the model, her name and phone number are replaced on her device.

**[Timeline]**

Over weeks, a picture builds. Her symptoms are grouped by body system, week by week. Skin, joints and mouth flare up together in September. That's the kind of link that gets lost between three different appointments.

**[To discuss]**

Giulia has a new appointment coming up. Here, Clario shows her what's worth bringing up: symptoms that tend to appear together, with the notes behind them. It never names a disease, and it never tells her what she has. It also suggests one question to raise with the doctor, the one that would help most.

**[Labs]**

Her paper lab reports are here too. The pages were read by MinerU running on AMD Token Factory, and every out-of-range flag is checked in code against the printed reference range. A pile of paper becomes a lab history she can follow.

**[Share, проходим всё]**

Before the visit, she decides what to share: which weeks, a note for her doctor, and how long the link lives. The package is sealed with her clinic's key, so only that clinic can open it, and it expires after a few days. Everything she didn't choose never leaves her laptop. She can also see every call to a model, in a log she can check herself.

---

**[Клиника, Patient at a glance]**

Now the doctor. One screen in plain words, no codes: who Giulia is, what keeps coming back, what's new, which labs are out of range, and the question she wrote down for this visit.

**[Что уже было сделано]**

The doctor also sees what's already been tried. Ibuprofen for two weeks, no effect. Which tests were done, and what they showed. No more starting from zero.

**[Suggestions]**

Then the hard part. Findings from skin, joints, kidneys and blood can belong to one picture, and no single specialist sees them all. Clario ranks conditions worth considering against published rare disease data, shows what matches and what's missing, and suggests the one question that would best tell them apart. The doctor answers, and the list updates. The doctor decides, not the software.

**[Generate brief]**

One click, and Gemma 4 31B, running on AMD Token Factory, drafts a one-page brief from pseudonymised data. It's marked as an AI draft. Every line points back to Giulia's own notes, and code flags any line that her notes don't support. The doctor edits it and signs. Only then is it final.

---

**[Финал: под капотом, поверх слайда]**

Under the hood, Clario runs on Gemma 4 from end to end. We used Gemma 4 31B on AMD Token Factory to generate almost three thousand synthetic patient diaries, and published them as an open dataset. On that data we fine-tuned the small Gemma 4 E4B. On diseases it never saw in training, it scores 0.69 F1, against 0.47 for Gemma 4 31B and 0.36 for the model before fine-tuning. A model six times smaller beats the big one, and it's small enough to run offline, on the patient's own laptop.

Clario organises the evidence. The doctor decides.

---

**Перед записью проверь:**
- **Модель в заметке.** Если деплой запущен с `PATIENT_LLM=modal`, заметку читает наш дообученный E4B, и можно сказать «Our fine-tuned Gemma 4 reads the note».
- **Ibuprofen.** Строка про ибупрофен нужна только если в клинике виден блок «Already tried». Он показывается у пакета второго мнения; если его не будет в кадре, этот абзац выкидываем.
- **Цифры в финале.** Они из `eval/results`: одни и те же 100 отложенных синтетических записей, F1 посчитан после проверки HPO-кодов (`extraction_ft-e4b-vllm-test100.json`, `extraction_tf-gemma-4-31b-it-test100.json`, `extraction_base-e4b-test100.json`). «В шесть раз меньше»: 31B против примерно 4–5 млрд параметров у E4B.
