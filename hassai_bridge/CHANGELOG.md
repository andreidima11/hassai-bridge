# Changelog — HASSAI Bridge add-on

## 0.2.57-beta

### Provider defaults & stats
- **Correct default URLs** — Grok `https://api.x.ai/v1`, DeepSeek `https://api.deepseek.com/v1`, OpenAI `https://api.openai.com/v1`
- **URL normalization** on save; legacy `/chat/completions` URLs cleaned automatically
- **Statistics → Model** — cache hit/miss per model + **Cache by Model** table

## 0.2.56-beta

### Fixes
- **Grok/provider errors** — HTML error pages (Cloudflare, bad URL) no longer appear as chat replies; show a clear message instead
- **Fetch Models** — after loading, shows a full dropdown list (input hid all but the first model)

## 0.2.55-beta

### UI fixes
- **Brain popover** — renders via portal above the entire chat UI (no longer clipped inside the composer bar)
- **Welcome message** — removed stars/glow/shimmer; subtle text-only fade-in

## 0.2.54-beta

### Chat — provider quick settings
- **🧠 brain icon** next to Send/Stop opens a popover: active provider, model picker (live fetch), thinking/reasoning mode
- **Fetch Models fix** — settings and chat now show the full model list (API shape normalization + visible `<select>`)

### Grok (x.ai) — reasoning, cache, image generation
- **Reasoning effort** mapping (Auto / Off→low / High / Max→xhigh on grok-4.6+) via `reasoning_effort`
- **Prompt cache** — `x-grok-conv-id` header from session id; cache hits from `prompt_tokens_details.cached_tokens`
- **480K context budget** metadata for Grok KV trim
- **Imagine image generation** — internal `generate_image` tool → `/v1/images/generations`; images persisted and shown inline in chat

### Tests
- 82 unit tests

## 0.2.53-beta

### DeepSeek — thinking, KV cache, stats
- **Thinking mode** (Auto / Off / High / Max) driven by provider capabilities — 🧠 in chat composer + provider settings
- **`reasoning_content`** preserved in agent tool loop for multi-round DeepSeek calls
- **KV cache optimization** — stable vs volatile system prompt split; trim drops oldest turns only (no summary injection); ~98K context budget
- **Cache metrics** — `cache_hit_tokens` / `cache_miss_tokens` stored in usage stats and shown in **Statistici → Model**

### Chat — vision & mobile
- **Vision LLM routing** when primary model lacks vision (dedicated vision provider or auxiliary fallback)
- **Welcome glow** — wider effect, no hard clip at edges
- **Mobile image attach** — HEIC support; file picker no longer drops selected photos

### Settings / UI fixes
- **Stats refresh** no longer crashes when on Server/Memory/Skills sub-tab (canvas negative radius)

### Tests
- 71 unit tests

## 0.2.52-beta

### Chat fixes & personalization
- **HA user name** in system prompt — model knows who it's assisting (display name from Ingress/profile)
- **Fix blank screen when sending images** — restored thinking imports; file picker no longer clears chat
- **Welcome glow** — soft fade instead of hard clip on the left edge

### Tests
- 58 unit tests

## 0.2.51-beta

### Chat — thinking, welcome, images
- **Gândește / Thinking** label (no more „puțin”); expand panel to read model **reasoning**
- Reasoning no longer mixed into visible assistant reply text
- **Welcome hero** — subtle space-themed animation on empty chat (stars, glow, shimmer)
- **Image upload** — attach or paste up to 4 photos; vision/multimodal to provider; persisted in session history

### Settings — memories UI
- Fix text overflow in memory list; keywords shown as wrapping chips instead of one long line

### Tests
- 55 unit tests (incl. chat images / multimodal helpers)

## 0.2.50-beta

### UI — Home Assistant theme sync
- Chat and settings colors match HA dark theme (`#111` / `#1c1c1c`)
- Ingress reads parent HA CSS variables when available
- Removed top header bars and center version stamp (chat + settings)
- Floating icons: conversations top-left, settings top-right

## 0.2.49-beta

### Automation tools & chat thinking UX
- **`ha_delete_automation`**, **`ha_delete_script`**, **`ha_delete_scene`** — remove via HA config API
- **`ha_get_automation`** — search by name + triggers/conditions/actions summary for explain questions
- Agent steered to stop tool loops on read-only explain requests
- **Thought briefly** rows between tool steps (EN/RO), like Cursor
- 52 unit tests

## 0.2.48-beta

### Chat UX — Stop & thinking
- **Stop button** replaces Send while the model is generating (EN/RO)
- **Thinking panel** collapsed by default; click the live status label to expand steps
- **Server-side cancel:** `POST /v1/chat/cancel/{trace_id}` stops the agent loop (ingress + stream)
- Activity poll exposes `cancelled`; 50 unit tests

## 0.2.47-beta

### Phase 7 — integrations, statistics, location entities
- **`ha_list_config_entries`**, **`ha_get_config_entry`**, **`ha_reload_config_entry`**
- **`ha_list_statistic_ids`**, **`ha_get_statistics`** (recorder long-term stats)
- **`ha_list_groups`**, **`ha_list_zones`**, **`ha_list_persons`**
- Thinking labels EN/RO; unit tests for formatters

## 0.2.46-beta

### Phase 5 — floors
- **`ha_list_floors`**, **`ha_create_floor`**, **`ha_update_floor`**
- **`ha_create_area` / `ha_update_area`**: resolve `floor_name` via floor registry

### Phase 6 — automations, scripts, scenes
- **`ha_list_automations`**, **`ha_get_automation`**, **`ha_trigger_automation`**
- **`ha_list_scripts`**, **`ha_run_script`**
- **`ha_list_scenes`**, **`ha_activate_scene`**
- Registry cache includes floors; thinking labels EN/RO

## 0.2.45-beta

- **Entity tools v4 (trace & Assist):** `ha_get_history`, `ha_get_logbook`, `ha_get_entity_source`, `ha_list_exposed_entities`, `ha_expose_entity`
- History/logbook via Core REST with hours lookback; entity source requires a filter
- Voice exposure: list and set Assist/Alexa/Google visibility (`confirm=true`)
- Unit tests for history/logbook/source/expose formatters

## 0.2.44-beta

- **Entity tools v3 (areas, labels, devices):** `ha_create_area`, `ha_update_area`, `ha_list_labels`, `ha_create_label`, `ha_update_label`, `ha_update_device`
- Label names resolve to `label_id` when assigning labels on entities, areas, or devices
- Registry cache includes label registry; invalidates after mutating registry tools
- Thinking UI labels (EN/RO) for new tools

## 0.2.43-beta

- **Entity tools v2 (registry):** `ha_list_entities` merges entity registry (area, device, disabled columns); filters by `area_name`, `device_id`, `include_disabled`
- New tools: `ha_list_entity_registry`, `ha_get_entity_registry`, `ha_update_entity`, `ha_list_areas`, `ha_list_devices`, `ha_get_device`, `ha_set_state` (helpers only)
- WebSocket registry bundle cached 30s; `ha_update_entity` resolves `area_name` via `ha_list_areas`
- Agent loop: primary provider for registry mutating tools; thinking labels for entity registry tools
- Unit tests for merge/filter/registry payload helpers

## 0.2.42-beta

- **Entity tools v1:** improved `ha_list_entities` (all domains, pagination, sort, state filter), `ha_get_state` (full attributes, timestamps, capabilities), `ha_call_service` (changed states + optional verify), new `ha_list_services`
- **`entity_tools.py`** + unit tests (filter, format, services index)
- **Home Assistant agent prompt** configurable in Settings → General (English default, `{tools}` placeholder); separate from personality system prompt
- Agent loop: primary provider for entity tools; do not repeat-skip verify reads (`ha_get_state`)

## 0.2.41-beta

- **Thinking panel:** Vercel-style collapsible steps — no duplicate „Gândește”, live step label (e.g. „Dashboard · home”), timeline with spinner/check, auto-collapse after reply
- Dedupe activity events from SSE + poll (fixes double step timing)

## 0.2.40-beta

- **Fix `ha_delete_dashboard` / `ha_update_dashboard`:** Home Assistant requires `dashboard_id` (from `ha_list_dashboards`), not `url_path`
- Lookup accepts `dashboard_id`, `url_path` (underscores → hyphens), or title (delete only)

## 0.2.39-beta

- New Lovelace tools: `ha_delete_view`, `ha_update_dashboard`, `ha_delete_dashboard`, `ha_list_lovelace_resources`, `ha_append_card_yaml`
- `dashboard_url` on dashboard tools resolves `/lovelace/...` and `/dashboard-.../...` into `url_path` + `view_path`
- YAML card append via PyYAML for `ui-lovelace.yaml` and `dashboards/*.yaml`
- Agent loop: notice when steps run out with pending tool calls; extended round limit uses a proper while loop
- Fix `_list_dashboards` regression that dropped additional dashboard listings

## 0.2.38-beta

- Agent loop: extra tool round after Lovelace mutations; primary provider for dashboard tools (not secondary/eco)
- Do not skip repeated `ha_get_dashboard` verify reads or mutating tool calls
- Nested stack/grid cards via `card_path` (e.g. `2.1`); YAML dashboards show `config_file` in listings
- Richer thinking-step labels for dashboard/card tools; Lovelace YAML writes hint `ha_reload lovelace`

## 0.2.37-beta

- **Lovelace tools fixed for modern HA:** card edits target `sections[].cards` on sections views (not dead `view.cards`)
- New tools: `ha_create_dashboard`, `ha_upsert_view`, `ha_upsert_section`
- `ha_get_dashboard` returns a compact summary; `view_path` distinguishes pages from dashboard `url_path`
- `ha_list_dashboards` includes Overview; YAML-mode errors and `ha_reload lovelace` are clearer
- Unit tests for Lovelace helpers (fixtures, no live HA)

## 0.2.36-beta

- Assistant messages render **markdown** (headings, lists, tables, links, code blocks with copy)
- Same chat shell: messages still scroll, composer stays put

## 0.2.35-beta

- Chat header: conversation control is a **chat-window icon** (top right), not a hamburger; settings gear stays on the left
- Composer is a compact ChatGPT-style pill when empty or one line, and grows for longer text — same sticky bar / message scroller
- Visual polish toward ChatGPT dark (flat surfaces, softer bubbles) without changing the working layout
- Settings page uses the same header, chat-window icon, and color language

## 0.2.34-beta

- **Chat is React** (Vite), using the vercel/chatbot shell: `relative flex-1 min-h-0` + `absolute inset-0 overflow-y-auto` messages, sticky composer, `useScrollToBottom`
- Built into static files at image build; Python still serves the API and Settings
- No `100dvh`, no Home Assistant iframe resize

## 0.2.33-beta

- **Chat UI from vercel/chatbot:** dark tokens, header 56px, overlay sidebar, greeting, user pills, assistant sparkles, sticky composer with arrow-up send
- Messages still scroll in an `absolute inset-0` pane (no `100dvh`, no iframe resize)

## 0.2.32-beta

- **Chat layout from vercel/chatbot:** messages scroll in an `absolute inset-0` pane; composer is `sticky` at the bottom of **our** column (not `fixed`, no iframe resize)
- Restore scroll when a conversation is open; keep the message bar in the footer
- Stamp moved into the header so it does not sit on the composer

## 0.2.31-beta

- **Stop touching the Home Assistant iframe** (0.2.30 resized the parent panel and broke the UI)
- Chat layout matches **Hyve**: header, `flex: 1` messages, composer at the bottom of **our** column — no `vh`/`dvh`, no parent `scrollTo` / iframe height hacks

## 0.2.30-beta

- **Rebuild chat layout from scratch** (keyboard kept pushing the HA header)
- App fills **only the Ingress iframe** (`inset: 0`, `height: 100%`) — no `100vh` / `100dvh`
- Toolbar is a real header in the column (not `position: fixed` / `absolute` on the viewport)
- Messages scroll; composer stays in flex flow at the bottom of **our** panel
- When the keyboard opens, shrink the **HA iframe** to the visible area (same-origin Ingress) so the HA header does not pan. Fallback: dock the composer under the toolbar

## 0.2.29-beta

- **Keyboard / HA header:** `html`, `body` and `.chat-shell` use `height: 100dvh; max-height: 100dvh` so the panel tracks the mobile visual viewport when the keyboard opens or closes. Fallback `height: 100%` for older browsers.
- Chat is a flex column: messages `flex: 1; min-height: 0; overflow-y: auto`, composer `flex: 0 0 auto` — no `position: fixed` on the shell
- Gear / menu / sidebar are `absolute` inside the iframe, not `fixed` to the visual viewport
- Removed `scrollIntoView` on focus (it can pan the parent Home Assistant page)

## 0.2.28-beta

- **Keyboard like Zigbee2MQTT:** do not overlay/pan the page. The iframe document can scroll, and the layout viewport **resizes** with the keyboard (`interactive-widget=resizes-content`) so the Home Assistant header stays put
- Removed `overlays-content`, `visualViewport` parent math, and page `translateY` / `scrollTo(0,0)` hacks that pushed HA chrome or hid the chat bar

## 0.2.27-beta

- **Fix chat layout (0.2.26 regression):** message bar stays at the bottom of the panel, not at the top / off-screen
- **Fix chat scroll:** messages scroll again when a conversation is open
- Composer is back in the page flow; keyboard only lifts the bar (clamped inset — HA iframe `visualViewport` can be a tiny number)

## 0.2.26-beta

- **HA Companion app:** tapping the chat bar no longer pushes the whole page up. Logo/settings stay put; only the message bar lifts with the keyboard (cancels WebView pan)

## 0.2.25-beta

- **HA in mobile browser:** chat bar sits above the browser toolbar (not under Safari/Chrome)
- **Keyboard in Ingress:** bar lifts using the **parent** visual viewport (iframe `visualViewport` does not shrink in HA sidebar)

## 0.2.24-beta

- **Repo is add-on only** — app lives in `hassai_bridge/app/` (no separate root copy that could ship stale UI)
- **Keyboard:** overlay only the message bar; the page/logo stay put (HA Ingress iframe included)
- **No CSS flash** when switching Chat ↔ Settings — stylesheet loads in `<head>` immediately

## 0.2.23-beta

- **Fix Ingress cache hell:** CSS/JS load only after `/api/build` check; absolute URLs with ingress prefix; static files served with strict `no-store` headers
- **Build stamp** bottom-left in chat — verify you see `v0.2.23-beta` (if not, add-on/container is still old)
- Add-on UI should match direct `:8899` (same assets, no mixed old/new CSS)

## 0.2.22-beta

- **Thinking UI (Cursor-style):** „Gândește” / pașii de tool apar într-un panou separat deasupra răspunsului, nu în același bubble
- **Add-on / Ingress:** panoul de thinking apare imediat (nu mai pare blocat/pauză); polling activitate mai rapid pe Ingress

## 0.2.21-beta

- **Fix `lang is not defined`:** language init in HTML before chat.js; chat uses `window.HASSAI_CHAT_LANG` (works even if an old cached script loads)
- **Mobile browser toolbar:** chat composer is in a flex column inside `100dvh` instead of `position: fixed` — stays above Safari/Chrome bottom bar

## 0.2.20-beta

- **Mobile browser:** chat bar stays above the browser bottom toolbar (Safari/Chrome), not only when the keyboard is open — uses `visualViewport` inset at all times
- Chat shell uses `100dvh` so the layout tracks the visible viewport when browser chrome shows or hides

## 0.2.19-beta

- **Fix:** chat crashed with `lang is not defined` when sending a message (missing variable declaration)

## 0.2.18-beta

- **Keyboard (mobile):** chat composer stays above the keyboard using `interactive-widget=resizes-content` plus `visualViewport` fallback — works better in HA sidebar / Ingress iframes
- **Settings footer:** shows app version and Home Assistant connection status (connected / unreachable / standalone)

## 0.2.17-beta

- **Ships a fresh GHCR image** — 0.2.16 had no prebuilt pull, so many installs kept the old 0.2.15 container (only HTML tweaks visible). Update to this version to get Lovelace WebSocket, fresh chat, keyboard fix, and welcome UI
- GHCR builds run on **GitHub Release only** (not every push)

## 0.2.16-beta

- **Lovelace dashboards:** edit storage dashboards via HA WebSocket (REST `/lovelace/*` returned 404 on modern HA)
- **Welcome screen:** HASSAI centered, subtle glow — no version line, no “connected to HA” banner
- **Fresh chat** every time you open the HASSAI panel (iframe no longer keeps the old thread)
- **Keyboard:** message bar sticks to the bottom of the visible screen above the keyboard
- **Add-on builds on your HA** again (no GHCR pull). Stale UI was browser cache — hard refresh once if needed

## 0.2.15-beta

- Opening HASSAI always starts a **new chat** (previous threads stay in the sidebar)
- Phone keyboard lifts **only the message bar**; the welcome/logo and Home Assistant header stay put

## 0.2.14-beta

- **Cache buster:** CSS/JS URLs use `version.hash` of the UI files; if Ingress still has old HTML, the page reloads once with `?_b=` so you are not stuck on a cached chat.js
- **Agent steps persist:** leaving a chat and opening it again still shows what HASSAI thought and which tools it ran (collapsed timeline, same as live)

## 0.2.13-beta

- **Fix:** store could say “up to date” while the sidebar still ran an old local build. Supervisor substitutes `{arch}` in `image:` (`ghcr.io/andreidima11/{arch}-hassai-bridge`); the generic name without `{arch}` does not pull on many HA OS versions
- Chat HTML/CSS/JS are served with `Cache-Control: no-store` so Ingress cannot keep a previous UI after you update

## 0.2.12-beta

- Add-on now **pulls a prebuilt image** from GHCR (`ghcr.io/andreidima11/hassai-bridge`) instead of building on the HA machine (that cache kept shipping an old UI while the store said “up to date”)
- Chat home shows the running version under the logo so you can confirm it matches GitHub

## 0.2.11-beta

- **Add-on image:** Supervisor can no longer reuse a cached Docker layer of an old `app/` (terminal had new chat, sidebar add-on did not). Version is baked into the Dockerfile so every store update rebuilds the UI
- CSS/JS in the HA sidebar use relative URLs (no missing stylesheet when Ingress prefix is empty)

## 0.2.10-beta

- Chat shows a live activity log while the agent works (thinking, HA tools, search, skills) — compact timeline, then collapses to a step count
- Works in the HA sidebar too (polls steps; does not depend on SSE)

## 0.2.9-beta

- **Fix:** Settings toast `Cannot set properties of null (setting 'textContent')` — system info no longer writes to missing DOM nodes
- **Fix:** Chat page follows Settings language (Română / English), including after a refresh
- **Fix:** Top-left chats button actually opens the conversation list (sidebar was hidden by CSS `display:flex` vs `hidden`)
- **Fix:** Welcome logo stays put when the phone keyboard opens; only the composer moves up

## 0.2.8-beta

- **Agentic loop:** the model keeps using HA/search/skill tools until the task is done (up to 16 steps, configurable), like Cursor — it no longer stops after one lookup
- Tools stay available across steps (same tool can be reused); identical repeats are skipped
- Prompt: don't ask "should I continue?"; if the user asked for a change, set `confirm=true` and do it
- Settings → Performance: **Agent tool rounds**
- Chat home: **HASSAI** + copilot subtitle (follows Settings language, including Romanian)
- Phone keyboard lifts the composer only — the logo stays put

## 0.2.7-beta

- Settings has no top header (chat icon only, same as the chat page)
- Chat sidebar: list, open, delete, and start conversations for the **logged-in Home Assistant user**
- Opening HASSAI upserts that HA user in Settings and generates an Assist API key
- Settings → Users: **Sync HA users** from `person.*`; each user has a key for the integration
- Chat no longer sends `user: "webui"` — identity comes from Ingress headers or the Assist API key

## 0.2.6-beta

- **Fix:** HA status always said “no API access” (`_request` was renamed; ping never succeeded)
- **Fix:** empty “(empty response)” on phone/Ingress — SSE is unreliable in the
  Companion WebView; chat uses JSON there, and falls back if a stream is empty
- Surface provider/network errors instead of a blank reply
- Install CA certificates in the add-on image (HTTPS to DeepSeek/OpenAI)

## 0.2.5-beta

- **Fix:** Ingress sidebar loaded HTML without CSS (gear stuck on the left).
  Asset URLs now use the Ingress prefix (or detect it from the iframe path).

## 0.2.4-beta

- **Fix:** add-on update could keep a cached Docker layer that git-cloned
  old `main` (`v0.2.0-beta`) while the store showed `0.2.3-beta`
- App sources are now copied into `hassai_bridge/app/` and baked into the
  image (no git clone at build time)

## 0.2.3-beta

- Chat gear inset from edges; redesigned composer with centered text
- Add-on chat is an HA admin copilot: entities, services, dashboards/cards,
  logs, Supervisor problems/fixes, config check/reload, and `/config` files
- User name placeholders use “George”

## 0.2.2-beta

- Chat UI: removed top bar; settings gear only (top-right)
- Single version source (`/VERSION`) synced across app, UI, add-on, and GitHub releases
- Port 8899 published for the HA integration (`http://hassai_bridge:8899`)

## 0.2.1

- Document Bridge URL for the HA integration
- Publish host port 8899 by default

## 0.2.0

- First Home Assistant add-on (Ingress sidebar panel **HASSAI**)
- Chat home + Settings page split
