# locqa — контроль качества локализации Flutter ARB (қазақша · O‘zbekcha)

Решение кейса **Grand Mobile × Decentrathon 6.0 — «Qazaq Loc QA»**.
`locqa` находит ошибки в ARB-файлах локализации, собирает отчёт (JSON + HTML), глоссарий и готовит исправленный файл
с **отметкой «проверил ли человек»** у каждой изменённой строки. Работает с **любым ARB**, без интернета, без API-ключей,
только на стандартной библиотеке Python 3.9+ (зависимостей нет).

**Два языка с отдельными правилами:** казахский (`--lang kk`, кириллица) и узбекский (`--lang uz`, латиница).
Язык выбирается явно (или из `@@locale` / имени файла); правила, глоссарий и определение «чужого языка» берутся строго для
выбранного языка — узбекский никогда не обрабатывается казахскими правилами (это проверяется тестами).

## Быстрый старт

```bash
git clone <repo> && cd locqa
python3 -m unittest discover -s tests -t .        # 20 тестов

# Казахский (обязательное ядро)
python3 -m locqa check --source intl_ru.arb --target intl_kk.arb --glossary glossary/glossary.csv --out report.json
# -> report.json, report.html, report.summary.json

# Узбекский (те же детекторы, узбекские правила)
python3 -m locqa check --source intl_ru.arb --target intl_uz.arb --lang uz --glossary glossary/glossary.csv --out report_uz.json

# Исправленный файл + материалы для проверки человеком
python3 -m locqa fix --source intl_ru.arb --target intl_kk.arb --glossary glossary/glossary.csv \
        --curated fixes/kk_curated_fixes.csv --out-dir out/
# -> out/intl_kk_fixed.arb, out/review_kk.csv, out/review_kk.html

# Офлайн-проверка совместимости с gen-l10n (плейсхолдеры, ICU, метаданные)
python3 -m locqa validate --source intl_ru.arb --fixed out/intl_kk_fixed.arb
```

Установка как команды: `pip install .` → `locqa check ...` (то же самое, что `python3 -m locqa`).
Воспроизвести все артефакты сдачи одной командой: `scripts/run_case.sh /путь/к/handout submission`.

Дополнительные источники доказательств: `--ref uz=intl_uz.arb --ref en=intl_en.arb` (другие языки используются **только как
улики**: например, «казахская» строка равна узбекской версии того же ключа → `wrong_language`).

## Что находит (типы кейса)

| код | как ищем |
|---|---|
| `untranslated` | ключа нет / значение пустое (пустое и в других языках — считаем намеренным) |
| `same_as_source` | совпадение с русским; исключения: бренды, латиница, числа; заимствования получают низкую уверенность и пометку |
| `placeholder_mismatch` | `{name}`, `%s`, теги `<g>`: потерянные скобки, искажённые имена (`{platformColo}`), лишние/пропавшие, ломаный ICU |
| `plural_mismatch` | разбор ICU `plural/select`: нет `other`, нет `one`, лишние `few/many`, плюрал пропал |
| `glossary_violation` | по `glossary.csv` (основы слов, запрещённые синонимы, предложение замены) |
| `length_overflow` | короткий исходник → длинный перевод; ищет **повторяющуюся «воду»** в хвосте и предлагает укороченный вариант |
| `machine_translation_suspect` | русские слова/окончания в казахском тексте, потерянные/изменённые числа |
| `inconsistent_term` | один исходник → разные переводы; статистическое выравнивание терминов (корень перевода «доступ → қолжетімді» нарушен в паре ключей) |
| `suffix_harmony` | жёсткий аффикс после плейсхолдера (`{name}-ға`, `{x}ga`); предлагает переформулировку |
| `orthography` | смесь кириллицы/латиницы в слове; казахские буквы, набранные русскими аналогами (`кұру`→`құру`, `Кайта`→`Қайта`) через частоты слов файла; для uz — единый апостроф `oʻ/gʻ` |
| `wrong_language` | узбекский/английский/португальский/русский текст в казахском файле; казахский/русский в узбекском |

Схема находки в `report.json` — ровно как в кейсе:
`key, issue_type, severity (high|medium|low), source, target, evidence, suggestion, confidence, reviewed_by_human`.

## Человеческая проверка (честно)

* `reviewed_by_human` в отчёте и `x-locqa.reviewed_by_human` в `intl_*_fixed.arb` — **`false` у всех строк**, пока их не подтвердил человек.
  Инструмент никогда не ставит `true` сам.
* `out/review_kk.html` — страница для носителя: оригинал / сейчас / предложение, кнопки **ok / правка / отклонить**,
  экспорт `review.csv`. Затем:
  ```bash
  python3 -m locqa apply-review --source intl_ru.arb --target intl_kk.arb --curated fixes/kk_curated_fixes.csv \
          --review review.csv --out intl_kk_fixed.arb
  ```
  `ok` → предложение принято, флаг `true`; `правка` → берётся `final_text`, флаг `true`; `отклонить` → строка остаётся как была.
* Метаданные хранятся в `"@key": { "x-locqa": {...} }` — пользовательский ключ, который `flutter gen-l10n` игнорирует.

## CI (GitHub Action)

`.github/workflows/locqa.yml` запускает `locqa check --fail-on high` на каждом pull request, меняющем `*.arb`.

## Данные

Данные организаторов в репозиторий **не входят** (`data/` в `.gitignore`); тесты используют синтетические файлы.
Файлы в `submission/` (отчёты, исправленный ARB) — производные от данных и сдаются организаторам по условиям кейса;
держите репозиторий приватным или не публикуйте `submission/` в открытом доступе.

## Структура

```
locqa/            пакет (arb, langs, icu, core, detectors, glossary, engine, report, fix, validate, cli)
glossary/         glossary.csv (ru · kk · en · uz + комментарии по употреблению)
fixes/            kk_curated_fixes.csv — ручные исправления (не проверены носителем!)
tests/            20 unit-тестов (синтетические ARB, kk и uz)
scripts/          run_case.sh — воспроизведение сдачи
submission/       готовые файлы для сдачи
docs/             METHODOLOGY.md
```

Ограничения и методика — в [docs/METHODOLOGY.md](docs/METHODOLOGY.md).
