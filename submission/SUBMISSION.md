# Текст для сдачи (edu.astanahub.com → трек → кейс → «Сдать решение»)

**Команда / кейс:** Grand Mobile · Кейс 02 · Qazaq Loc QA

## Краткое описание
`locqa` — CLI-инструмент контроля качества ARB-локализации Flutter. Находит 11 типов проблем из таксономии кейса
(untranslated, same_as_source, placeholder_mismatch, plural_mismatch, glossary_violation, length_overflow,
machine_translation_suspect, inconsistent_term, suffix_harmony, orthography, wrong_language) в казахском **и узбекском**
файлах, выдаёт `report.json` + HTML-отчёт с evidence/severity/confidence у каждой находки, готовит исправленный
`intl_kk_fixed.arb` и файлы для проверки носителем. Работает на любом ARB, офлайн, без API-ключей, зависимостей нет, 20 тестов.

## Что сдаём
| требование кейса | файл |
|---|---|
| CLI: `locqa check --source … --target … --glossary … --out report.json` | пакет `locqa/` (`python -m locqa` или `pip install .`) |
| `report.json` + HTML-отчёт | `submission/report.json`, `submission/report.html` |
| `glossary.csv` (ru, kk, en + комментарий; бонусом uz) | `submission/glossary.csv` |
| `intl_kk_fixed.arb` с отметкой проверки человеком | `submission/intl_kk_fixed.arb` (`@key → x-locqa.reviewed_by_human`) |
| описание методологии | `docs/METHODOLOGY.md` (копия в `submission/`) |
| README: что сделано и как запустить | `README.md` |
| бонус: узбекский | `submission/report_uz.json`, `report_uz.html`, `intl_uz_fixed.arb` |
| бонус: GitHub Action на PR с ARB | `.github/workflows/locqa.yml` |
| бонус: предложение переформулировки для аффиксов | `suffix_harmony` → поле `suggestion`, `fixes/kk_curated_fixes.csv` |
| материалы для проверки носителем | `submission/review_kk.html`, `review_kk.csv` (+ `review_uz.*`) |

## Результаты запуска на данных организаторов
* Казахский: 219 находок в 216 ключах (high 60 / medium 77 / low 82). Узбекский: 226 находок (high 23 / medium 18 / low 185).
* Исправлено 124 строки kk из 5 480 (12 — недостающие ключи): 48 механических, 76 ручных. **Через носителя прошло 0 строк** —
  у всех `reviewed_by_human = false`; для проверки подготовлены `review_kk.html` и команда `locqa apply-review`.
* Внешние LLM не использовались: стоимость обработки 0 $.

## Честные оговорки
Recall по подложенным ошибкам не измерялся (ответов у нас нет). Ручные переводы подготовлены ИИ-ассистентом и не проверены
носителем. `flutter gen-l10n` не запускался; вместо него — офлайн-проверка `locqa validate`.
