# Anonymous Easy-Bench report — 2026-11-05

**Evidence: one user-supplied screenshot. Verification: arithmetic only. Not included in regraded statistics.** The repository owner authorized anonymous publication. Contributor identity, model access route, environment, exact dataset revision and grader digest are unknown.

[Source image](report.png) · [Transcribed JSON](report.json) · [CSV](summary.csv) · [Provenance](PROVENANCE.json)

| Reported model | low | medium | high | xhigh | max | Passed / 150 | Transport errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-6-astra | 29 | 30 | 30 | 30 | 29 | 148 | 1 |
| gpt-6.1-sol | 28 | 29 | 30 | 30 | 29 | 146 | 1 |
| gpt-6.1-terra | 27 | 28 | 28 | 30 | 28 | 141 | 2 |
| gpt-5.6-terra | 27 | 28 | 26 | 29 | 27 | 137 | 2 |
| gpt-5.6-sol | 26 | 27 | 27 | 28 | 27 | 135 | 0 |
| gpt-5.6-luna | 25 | 26 | 27 | 28 | 28 | 134 | 2 |
| gpt-6-luna | 23 | 25 | 27 | 29 | 27 | 131 | 0 |

Each effort cell reports passes out of 30. Transport errors are provided only per model, not per effort or task.

| Reported phase | Trials | Passed | Wrong answers | Transport errors |
|---|---:|---:|---:|---:|
| Primary | 1050 | 972 | 70 | 8 |
| Pilot | 35 | 30 | 4 | 1 |
| Control | 42 | 37 | 5 | 0 |

Reported total coverage: **1127/1127**, primary matrix **35/35**. Primary pass rate is **972/1050 = 92.57%**; pilot and control do not enter this percentage.

The screenshot also claims a Docker check passed, initial observations were retained without retries/replacements, and parallelism up to 12 was an agreed deviation. These are source claims, not independently verified facts. They must not be interpreted as approval of a new default protocol.

No raw answers, task-level results or execution logs were supplied. Model identity is not independently attested. No model calls or regrading were performed to create this archive. It cannot establish account-level degradation or an A/B experiment. Published PNG metadata was removed while retaining the encoded image data and color profile; the visible contents were not changed. The original image's “nothing published” caption describes its earlier state.

## Русский

Анонимный отчёт перенесён из присланного скриншота: **972 верных ответа из 1050 (92,57%)**, 70 неверных и 8 транспортных сбоев в основной серии. Заявлено полное покрытие 1127 наблюдений с пилотом и контролем.

Проверена арифметика таблицы и итогов. Исходных ответов и журналов нет, поэтому правильность оценок, происхождение вызовов и соблюдение протокола не перепроверены. Отчёт хранится отдельно от `studies` и не увеличивает число исследований в перепроверенной статистике. Личность участника не раскрывается; служебные метаданные изображения удалены.
