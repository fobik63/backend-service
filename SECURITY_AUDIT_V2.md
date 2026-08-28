# SECURITY_AUDIT_V2.md — AI-Card-Master (ретест)

> Дата ретеста: 2026-08-28  
> Объект: `AI-Card-Master` (FastAPI + Next.js)  
> Режим: **статический ретест, без изменений исходного кода приложения**  
> База: `SECURITY_AUDIT.md` (score 68/100, вердикт: частично заблокировано)  
> Методология: skill `007` (6 фаз), `llm-security` / `api-security-patterns` из `.cursor/rules/agentic-skills`. Каталог `.cursor/rules/security-rules` по-прежнему **отсутствует** в репозитории.  
> Codebase Memory: проект `C-Users-ADMIN-Desktop-my-AI-Card-Master` переиндексирован 2026-08-28 (`fast`/`full`, ~12.5k узлов). Граф использовался для навигации; **ground truth — исходники на диске** (coverage части файлов всё ещё `metadata_changed`).

**Вердикт: одобрено с оговорками (score 80/100).**  
Платёжный контур ЮKassa (коины + тариф) можно выводить в прод. Остаточный риск C-01 (бесплатный LLM после fail/replay без кэша) желательно закрыть до широкой AI-монетизации. H-01/H-04/H-05 не блочат приём денег, но оставляют XSS→угон access-токена, публичную раздачу загрузок и jailbreak.

---

## 1. Новый Security Score

| Метрика | V1 (08:00) | V2 (ретест) |
|---|---|---|
| **Security Score** | **68 / 100%** | **80 / 100%** |
| Вердикт 007 | Bloqueado parcial | **Aprovado com ressalvas** |
| Критический (открыт) | 1 | **0** (C-01 → ⚠️ Partial) |
| Высокий (открыт / partial) | 6 | **0 открытых / 4 partial** |
| Средний | 9 | **1 partial** (остальные Fixed) |
| Низкий | 6 | **2 Not Fixed + 2 Partial** |
| Резолюции | — | ✅ 14 · ⚠️ 7 · ❌ 2 |
| Тип аудита | Static + graph | Static retest + graph refresh |

```
Критический  ░░░░░░░░░░  0 open (1 partial)
Высокий      ████░░░░░░  2 Fixed + 4 Partial
Средний      █████████░  9 Fixed + 1 Partial
Низкий       ██░░░░░░░░  2 Fixed + 2 Partial + 2 Open
OK           ██████████████  14 (сохранены) + новые контроли патча
```

### Баллы по доменам (007)

| Домен | Вес | V1 | V2 | Комментарий |
|---|---|---|---|---|
| Секреты и учётные данные | 20% | 80 | 82 | Прод-валидаторы: IP ЮKassa, Telegram secret при webhook URL |
| Input validation | 15% | 58 | 76 | Fence маркетплейса, magic bytes, multipart-sanitizer; regex-WAF всё ещё обходится |
| Аутентификация и авторизация | 15% | 70 | 86 | Auth на upload, Telegram fail-closed в prod, HttpOnly refresh |
| Защита данных | 15% | 60 | 78 | Refresh не в LS/`document.cookie`; access всё ещё в `localStorage`; CSP на Next.js |
| Устойчивость | 10% | 66 | 84 | FOR UPDATE + `Payment.find` на обоих webhook; Redis idempotency fail-closed |
| Мониторинг | 10% | 76 | 78 | Нейтральный ack вебхуков, лог reject IP |
| Supply chain | 10% | 70 | 70 | Полный SCA/CVE-прогон по-прежнему не делался |
| Compliance (OWASP / платежи) | 5% | 55 | 86 | Единый `YooKassaWebhookIngress`; IP allowlist на обоих путях |

**Итог:** `0.20·82 + 0.15·76 + 0.15·86 + 0.15·78 + 0.10·84 + 0.10·78 + 0.10·70 + 0.05·86 = 80`.

---

## 2. Таблица резолюций

Все ID — из первичного `SECURITY_AUDIT.md`. Новых Critical/High в этом проходе не заводилось (остаточные дыры описаны как хвосты исходных ID).

| ID | Кратко | V1 | V2 | Статус |
|---|---|---|---|---|
| C-01 | Replay `X-Idempotency-Key` → бесплатный LLM | Critical | Ledger кэширует результат; `/api/ai` в HTTP-idempotency; ключ = user+route+sha256(body). Replay **без** `llm_result` всё ещё вызывает провайдер | ⚠️ Partially Fixed |
| H-01 | Upload картинок без auth, публичный GET, `location` | High | `Depends(get_current_user)` + magic bytes; `location` убран. GET `/files/{filename}` публичный, квот нет | ⚠️ Partially Fixed |
| H-02 | Тарифный webhook без IP / cancel без lock | High | IP allowlist + `Payment.find` + `FOR UPDATE`; cancel не затирает `SUCCEEDED`; CF-bypass на обоих путях | ✅ Fixed |
| H-03 | Indirect injection через отзывы WB/Ozon | High | `fence_untrusted_text` на title/description/specs/reviews (+ delta path) | ✅ Fixed |
| H-04 | Direct jailbreak обходит WAF/fence | High | Canary, XML-fence, output-filter. Regex-детектор и `reject_injection=False` у canvas parser остались | ⚠️ Partially Fixed |
| H-05 | JWT в `localStorage` и cookie без HttpOnly | High | Refresh — HttpOnly cookie с backend. Access по-прежнему в `localStorage`; фронт не вызывает `/auth/refresh` | ⚠️ Partially Fixed |
| H-06 | Telegram webhook fail-open при пустом секрете | High | Prod 403 без секрета; `hmac.compare_digest`; webhook не регистрируется без secret | ✅ Fixed |
| M-01 | Нет верхней границы `amount_coins` | Medium | `le=MAX_PURCHASE_COINS` (5000) в schema и `coin_pricing` | ✅ Fixed |
| M-02 | IP-enforcement отключаемый; доверие CF-заголовкам | Medium | В production enforcement форсируется; заголовки читаются только если peer ∈ CF/trusted proxy | ✅ Fixed |
| M-03 | CF-bypass только для coin-webhook | Medium | Оба пути в `YOOKASSA_WEBHOOK_PATHS` | ✅ Fixed |
| M-04 | Redis idempotency fail-open | Medium | Redis down → HTTP 503, fail-closed | ✅ Fixed |
| M-05 | Утечка system prompt (нет canary/фильтра) | Medium | `PROMPT_CANARY_TOKEN` + `LlmOutputFilterMiddleware` | ✅ Fixed |
| M-06 | 404 / leak тела ошибок на webhook | Medium | Оба webhook всегда 200 + нейтральный ack; ошибки в лог | ✅ Fixed |
| M-07 | Multipart `/bulk-generations` обходит sanitizer | Medium | `_sanitize_multipart` сканирует текстовые form-поля | ✅ Fixed |
| M-08 | Upload доверяет `Content-Type` | Medium | `validate_image`: magic bytes JPEG/PNG/WebP + PIL | ✅ Fixed |
| M-09 | Два стека биллинга разной жёсткости | Medium | Общий `YooKassaWebhookIngress`. Клиенты SDK vs httpx и in-memory credit тарифа ещё разные | ⚠️ Partially Fixed |
| M-10 | Нет CSP на Next.js | Medium | CSP headers в `web/next.config.ts` | ✅ Fixed |
| L-01 | Абсолютный путь ФС в ответе upload | Low | Поле `location` удалено | ✅ Fixed |
| L-02 | Сравнение Telegram-секрета через `!=` | Low | `hmac.compare_digest` | ✅ Fixed |
| L-03 | Cookie JWT + CORS credentials | Low | JS больше не пишет JWT в cookie; refresh HttpOnly; access в LS + `withCredentials` | ⚠️ Partially Fixed |
| L-04 | Regex SQL/XSS WAF | Low | Паттерны те же по сути; ORM bind — основная защита | ❌ Not Fixed |
| L-05 | Плейсхолдеры юр. данных / `example.com` | Low | Defaults `support@example.com`, `[УКАЖИТЕ ЮРИДИЧЕСКОЕ НАИМЕНОВАНИЕ…]` на месте | ❌ Not Fixed |
| L-06 | Неполный набор русских jailbreak-паттернов | Low | Добавлены шаблоны («игнорируй все предыдущие…»). Обходы (role-play, encoding) живы | ⚠️ Partially Fixed |

**OK-01 — OK-14** из V1 подтверждены, не регрессировали.

Новые контроли патча (не были в V1 OK-таблице): единый `YooKassaWebhookIngress`; `bind_idempotency_key`; HttpOnly refresh cookie; `LlmOutputFilterMiddleware`; prod-валидаторы `YOOKASSA_WEBHOOK_IP_ENFORCEMENT` / Telegram secret.

---

## 3. Анализ остаточных рисков

Ниже — только ID со статусом ⚠️ / ❌. Как добить — конкретный патч, без эксплойт-пейлоадов.

### C-01 — ⚠️ Partially Fixed

**Что закрыто.** Исходный сценарий V1 (тот же клиентский ключ + **другое** тело → дебет не списывается, LLM всё равно идёт) больше не работает:

- Ledger-ключ считается как `user_id + route + sha256(body)` (`bind_idempotency_key`, `backend/app/domain/llm_coin_guard.py:14-26`). `SeoTextService.generate` подставляет этот ключ, а не сырой заголовок (`seo_text_service.py:108-124`).
- При replay с кэшем `predebit_then_call` возвращает `llm_result` и **не** вызывает `llm_call` (`llm_coin_guard.py:263-266`). Регрессия: `test_ledger_replay_returns_cached_result_without_llm`.
- HTTP-слой покрывает `/api/ai` и `/api/v1/billing` (`idempotency_middleware.py:39-41`); scope тоже включает hash тела (`:229-242`). Redis недоступен → 503, не fail-open (`:116-128`).

**Что осталось.** Если ledger уже `already_processed`, но `llm_result` нет, код **проваливается в `llm_call()`**:

```263:278:AI-Card-Master/backend/app/application/llm_coin_guard.py
        if already_processed:
            cached = ledger_body.get(_LLM_RESULT_KEY)
            if cached is not None:
                return cached, user, 0
        try:
            result = await llm_call()
        except Exception:
            if not already_processed:
                await self.refund(user_id=user_id, amount=amount)
            raise
        await self._store_llm_result(...)
        return result, user, 0 if already_processed else amount
```

Цепочка:

1. Первый запрос дебетит и пишет `IdempotencyRecord` (`billing_service.py:688-696`) **до** LLM.
2. LLM падает / клиент обрывает соединение → `refund` возвращает коины (`llm_coin_guard.py:269-272`), **строка ledger не удаляется**.
3. Повтор с тем же телом: `already_processed=True`, кэша нет → провайдер вызывается **без списания**. При повторном fail refund пропускается (`if not already_processed`). Это снова безлимитный LLM на один и тот же prompt.

Параллельный double-call того же body без заголовка `X-Idempotency-Key`: HTTP-middleware не включается (`:88-90`), оба хендлера доходят до LLM, дебет один.

**Как добить.**

1. Если `already_processed` и нет `llm_result` — **не** вызывать провайдер: вернуть 409 `IDEMPOTENCY_IN_PROGRESS` или сохранённую ошибку.
2. При fail LLM / refund — удалить или пометить ledger как `failed`, чтобы retry снова дебетил.
3. Тест: первый `llm_call` бросает; второй с тем же ключом не инкрементирует счётчик провайдера (или требует новый дебет).
4. Обязать `X-Idempotency-Key` на `/api/ai/*` либо всегда строить HTTP-scope даже без заголовка (по hash тела).

---

### H-01 — ⚠️ Partially Fixed

**Что закрыто.** Upload требует JWT (`images.py:143-146`); magic bytes + PIL (`generation_image_validation.py:51-78`); `location` нет в схеме (`images.py:56-68`, тест `test_upload_response_omits_filesystem_location`).

**Что осталось.**

- `GET /api/v1/images/files/{filename}` **без** `get_current_user` (`images.py:109-130`). Знание UUID из ответа upload (или утечка URL) = публичная раздача с origin API.
- Нет per-user квоты и `owner_id` (комментарий в `images.py:149`: «ownership column not on uploads yet»). Authenticated DoS диска остаётся.

**Как добить.** Колонка `owner_user_id`; GET только владельцу или signed URL с TTL; дневной/суммарный cap байт на пользователя; не отдавать `public_path` как долгоживущий CDN без подписи.

---

### H-04 — ⚠️ Partially Fixed

**Что закрыто.** XML-fence вместо известных `<<<UNTRUSTED_USER_DATA>>>` (`prompt_safety.py:18-21, 67-104`); canary `AICM-CANARY-9b4e2f71c8d03a56`; `LlmOutputFilterMiddleware` подключён в `main.py:444`; больше русских regex (`input_sanitization.py:82-85`).

**Что осталось.** Детектор — тот же узкий regex (`input_sanitization.py:64-86`). Canvas parser намеренно `reject_injection=False` (`prompt_parser.py:303-307`). Нет отдельного message-role / dual-LLM / классификатора. Fence-теги `<untrusted_input>` известны модели. Output-filter ловит только canary и фиксированные hardening-фразы, не произвольный пересказ system prompt.

**Как добить.** Структурное разделение (system vs tool/user data); structured output + фильтр на фрагменты policy; не считать regex защитой; регрессии jailbreak уровней 1–4 из `llm-security` в CI без боевых ключей. `reject_injection=True` на пользовательском canvas-промпте — только как доп. слой, не как гарантия.

---

### H-05 — ⚠️ Partially Fixed

**Что закрыто.** `persistSession` больше не пишет refresh в LS и затирает legacy cookie (`web/lib/auth/session.ts:27-37`). Backend ставит `refresh_token` как HttpOnly / Secure (не-dev) / SameSite=Lax / path=`/api/v1/auth` (`auth.py:151-160`) и отдаёт `refresh_token=""` в JSON (`:173-181`).

**Что осталось.**

- Access JWT по-прежнему в `localStorage` (`session.ts:30`, `client.ts:52-56`) — XSS читает его напрямую.
- Фронт **нигде не вызывает** `POST /api/v1/auth/refresh`. Cookie ставится, но не используется клиентом (сессия живёт TTL access ~15 мин или пока LS не почистят).
- `/refresh` всё ещё принимает refresh из JSON-body (`auth.py:517-519`) — запасной канал, если токен снова окажется у JS.
- Same-origin XSS может `fetch` refresh с `credentials: 'include'` и украсть **новый** `access_token` из JSON. HttpOnly защищает от кражи refresh для офлайн-использования, не от XSS-сессии.
- CSP Next.js содержит `'unsafe-inline'` и `'unsafe-eval'` (`web/next.config.ts:35-36`) — ослабляет защиту от XSS, которая и есть пререквизит H-05.

**Как добить.** Access только in-memory; фронт: interceptor 401 → `POST /auth/refresh` с `withCredentials`; убрать refresh из body-схемы в production; ужесточить CSP (nonce вместо `unsafe-inline`/`unsafe-eval`).

---

### M-09 — ⚠️ Partially Fixed

**Что закрыто.** Оба webhook проходят `YooKassaWebhookIngress.verify` → `find_payment` (`payment_service.py:138-142`, `coin_billing_service.py:116-120`). IP-зависимость общая (`require_yookassa_webhook_source`).

**Что осталось.** Два клиента: `yookassa_sdk_client.py` (коины) и `yookassa_service.py` (тариф, httpx). Зачисление тарифа — `user.ai_coins = int(...) + int(plan.ai_coins)` в ORM (`billing_service.py:513`), а не `credit_coins_in_transaction` / `_apply_balance_delta_locked` (`:733-776`). Под `FOR UPDATE` гонка закрыта, но пути снова разъедутся при следующем фиче-запросе.

**Как добить.** Один адаптер ЮKassa. Все кредиты кошелька — один `WalletPort` / `credit_coins_in_transaction`.

---

### L-03 — ⚠️ Partially Fixed

Следствие H-05: CORS `allow_credentials=true` нужен для HttpOnly cookie — это уже правильный паттерн. Остаточный удар — XSS → access в `localStorage`. Добивается тем же, что H-05.

---

### L-04 — ❌ Not Fixed

`input_sanitization.py:15-61` — regex SQL/XSS. Основная защита по-прежнему ORM bind params (как в V1). WAF остаётся обходимым defense-in-depth. **Добить:** не расширять regex как «безопасность»; держать parameterized queries; WAF — только шум/телеметрия. При желании — allowlist полей вместо blocklist.

---

### L-05 — ❌ Not Fixed

Плейсхолдеры в `config.py:132-159`: `https://ai-card-master.example`, `[УКАЖИТЕ ЮРИДИЧЕСКОЕ НАИМЕНОВАНИЕ ОПЕРАТОРА]`, `support@example.com`, `privacy@example.com`. Не RCE, но 54-ФЗ/оферта/доверие. **Добить:** прод-валидатор, запрещающий `example.com` и квадратные скобки-заглушки при `APP_ENV=production`.

---

### L-06 — ⚠️ Partially Fixed

Добавлены русские шаблоны (`input_sanitization.py:82-85`). Обходы из V1 (role-play без стоп-слов, encoding, crescendo) не закрыты. Добивается вместе с H-04, не отдельным Critical.

---

## 4. Сводка по шагам V1 (дорожная карта)

| Шаг V1 | Результат ретеста |
|---|---|
| 0. C-01 replay LLM | ⚠️ Кэш есть; fail-without-cache ещё вызывает провайдер |
| 0. H-02 единый webhook-guard | ✅ |
| 0. H-01 auth + убрать `location` | ⚠️ Auth и `location` ок; GET публичный, квот нет |
| 1. H-05 HttpOnly refresh | ⚠️ Cookie есть; access в LS; refresh на фронте не подключён |
| 1. H-06 Telegram secret | ✅ |
| 1. M-01 `le` на coins | ✅ |
| 1. M-02/M-03 IP + CF bypass | ✅ |
| 1. M-06 webhook 200 | ✅ |
| 2. H-03/H-04/M-05 fence+canary | H-03 ✅ · M-05 ✅ · H-04 ⚠️ |
| 2. M-07 multipart | ✅ |
| 2. M-10 CSP | ✅ (ослаблен `unsafe-inline`/`unsafe-eval`) |
| 3. M-04 fail-closed | ✅ |
| 3. M-08 magic bytes | ✅ |
| 3. M-09 один wallet/ingress | ⚠️ Ingress общий, wallet/клиент ещё два |
| 3. L-01–L-06 | L-01/L-02 ✅ · L-03/L-06 ⚠️ · L-04/L-05 ❌ |
| SCA в CI | Не делался (как в V1) |

---

## 5. Evidence (ретест)

| ID | source_ref | Вывод |
|---|---|---|
| E2-01 | `llm_coin_guard.py:263-268` + `seo_text_service.py:108-124` | Replay с кэшем без LLM; replay без кэша → LLM |
| E2-02 | `idempotency_middleware.py:39-41, 116-128, 229-242` | `/api/ai` в scope; fail-closed; body hash |
| E2-03 | `images.py:143-146` vs `:109-130` | Upload с auth; GET публичный |
| E2-04 | `payments.py:321-326` + `yookassa_webhook_ips.py:32-36, 66-76` | Оба webhook: IP + prod force |
| E2-05 | `yookassa_webhook_ingress.py:36-46` + `billing_service.py:411-427` | `Payment.find` на cancel; FOR UPDATE; SUCCEEDED не затирается |
| E2-06 | `competitor_audit.py:537-749` | Fence на отзывы/описание/specs |
| E2-07 | `session.ts:27-37` + `auth.py:151-181` | Refresh HttpOnly; access в LS |
| E2-08 | `telegram_bot.py:74-88` + `config.py:2346-2357` | Prod fail-closed + compare_digest |
| E2-09 | Codebase Memory reindex 2026-08-28 | Индекс обновлён; цитаты сверены с диском |

Live `repro_command` не выполнялся (read-only, без атаки на рантайм и без PoC).

---

## 6. Threat model (дельта к V1)

| Угроза | V1 | V2 |
|---|---|---|
| Spoofing ЮKassa тариф | H-02 | Закрыто (IP + find + lock) |
| Spoofing Telegram | H-06 | Закрыто в production |
| Tampering idempotency + LLM | C-01 безлимит | Безлимит на **тот же** prompt после fail; разное тело больше не бесплатно |
| DoS upload | H-01 анонимный | Только с JWT, без квоты |
| XSS → полный захват | H-05 access+refresh из JS | Refresh не читается JS; access из LS + refresh-via-cookie с XSS origin |
| Отравленный аудит карточек | H-03 сырой текст | Fence есть; jailbreak модели (H-04) остаётся |

**PASTA:** удар по марже с поддельным webhook тарифа снят. Основной финансовый остаток — LLM-cost после «оплатил → упал → replay». Репутация: XSS-угон кабинета (access JWT) и residual prompt injection.

---

## 7. Что сознательно не эксплуатировалось

По политике `llm-security` и правилам Cursor не выпускались jailbreak-пейлоады, эксплойт-скрипты и атаки на живые API/ЮKassa. Исходный код приложения в этом проходе не изменялся (создан только этот отчёт).

---

*Конец ретеста V2.*
