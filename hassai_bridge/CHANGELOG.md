# Changelog — HASSAI Bridge add-on

## 1.2.0

### Features
- **Dynamic toolkits** — Settings → Performance → Dynamic sends a small core (media, memory, bridge read, `activate_toolkits`) and loads HA/Frigate/image packs on demand; respects HA/Bridge permission toggles (including new **media** permission)
- **Tool token logging** — each turn logs estimated tool-schema tokens before/after filtering (and after pack activate)
- **Short tool descriptions** — in Dynamic mode, tool descriptions are collapsed to one short line (parameters kept) to save more input tokens

## 1.1.0

### Features
- **Session-scoped chat provider / model** — changing provider or model in the chat bar applies only to that conversation; it no longer updates the global default provider in Settings for everyone else. Auto in chat is also per-session.

## 1.0.48

### Fix
- **Inline `<thinking>` / `<think>` tags** — strip from the chat reply and show them in the Thinking panel; also pick up OpenRouter `reasoning` / `reasoning_details`
- **OpenRouter provider sort clarified** — UI hint that sort picks the upstream host for the same model (shown as `model · Host`); use Fallback models for a different model on failure

## 1.0.47

### Features
- **OpenRouter free-model filter** — checkbox before Fetch Models shows only `:free` ids
- **OpenRouter routing options** — fallback models, provider sort (price/throughput/latency), allow fallbacks, data collection / ZDR, context compression; attribution headers use `X-OpenRouter-Title` + categories

## 1.0.46

### Features
- **OpenRouter provider** — add OpenRouter in Settings (OpenAI-compatible gateway); chat/details show the exact routed model id from the API response (e.g. `anthropic/claude-…`), not just “OpenRouter”

## 1.0.45

### Features
- **Vision → chat handoff** — on a photo turn the Vision LLM also stores a dense (hidden) image description; text follow-ups on the primary model get that context so they still “know” the photo without staying on Vision

## 1.0.44

### Fix
- **Vision only for the photo turn** — after a snap, text follow-ups return to the primary / Auto fast path instead of staying on the Vision LLM (and burning API spend). Historical images are stripped for non-vision models.

## 1.0.43

### Fix
- **Vision no longer hijacks unrelated Grok** — image requests only use the Vision LLM / auxiliary linked on the active provider. A Grok secondary on another primary is never auto-picked (avoids surprise 403 credit errors on Z.AI etc.)

## 1.0.42

### Fix
- **iOS Companion conversation TTS silent** — play replies through the live mic AudioContext (HTML audio stays muted while getUserMedia is open); unlock shared audio on mic / hands-free open

## 1.0.41

### Features
- **Frigate video in chat** — `frigate_clip` + `include_clip` on events; MP4 playback in the bubble (no more snapshot substitutes for video/înregistrare)
- **AI greeting pool** — when Dynamic greetings is on: refresh every N days, seasonal/holiday-aware (Christmas, Easter, …), pick provider + model, **Generate now**; curated greetings stay as fallback

### Fix
- **Settings crash / Edit provider** — null-safe DOM updates; provider actions via `data-prov-id` (IDs with quotes/special chars)
- **Backup download toast** — dated ZIP name; clearer picker vs Downloads messaging
- **Name in every reply** — know the HA user, but don’t address them by name on most answers

## 1.0.40

### Fix
- **Voice not detecting speech until close/reopen** — resume suspended AudioContext, guard push-to-talk double-start, watch dead mic tracks, recalibrate VAD when returning to listen, resume audio on tab focus

## 1.0.39

### Fix
- **ChatGPT HTTP 400 “tools array too long”** — OpenAI allows max 128 tools; after the HA tool expansion we sent ~156. Cloud OpenAI now hard-caps at 128 (Frigate/camera turns keep `frigate_*` when you ask about video/curte/înregistrări)

## 1.0.38

### Fix
- **Delete todo lists** — `ha_create_todo_list`, `ha_delete_todo_list`, `ha_clear_todo_list` for Local To-do lists (previously only items could be removed)

## 1.0.37

Major Home Assistant tool expansion: calendar/todo, helpers, traces, and more.

### Features
- **Calendar & todo** — list/create/update/delete calendar events; todo lists + shopping list
- **Helpers CRUD** — create/update/delete `input_*`, timer, counter, schedule (UI storage helpers)
- **Automation traces** — `ha_list_traces` / `ha_get_trace` for failed runs
- **Interactive notify** — `ha_notify` with actions/images; persistent notifications
- **Integrations admin** — disable/remove entries, start/continue config & options flows
- **Media players** — browse, search, play_media, volume/queue controls
- **Matter / Thread / Bluetooth** — commission/diagnostics + OTBR/Thread datasets + BT device list
- **Scenes editor** — create/update/get scene config (plus existing activate/delete)
- **Recorder** — info, purge/repack, purge entities, validate statistics
- **HACS** — list/info/install/update/remove repositories
- New Settings toggles: **calendar**, **helpers**, **hacs** (Matter/BT under zigbee)

## 1.0.36

Automatic memory consolidation can run on a custom interval, including from chat.

### Features
- **Interval schedule** — Auto Consolidation supports daily, weekly (Monday), or every N hours (1–168); Settings UI + persisted `last_run_at` for intervals
- **Chat command** — `/consolidation` (alias `/consolidare`): status, `on`/`off`, `daily [hour]`, `weekly [hour]`, `every 6h`, `now`

## 1.0.35

Eco Mode removed — it did not reduce tokens in practice.

### Changes
- **Remove Eco Mode** — no per-provider toggle, eco prompt, `/seteco`, eco stats, or eco-driven compaction; Settings tab renamed to **Performance** (local AI tool profile / history only)
- Cloud providers stay full tools/history; local AI compaction unchanged

## 1.0.34

Intermittent HTTP 429 no longer freezes the whole add-on behind Ingress.

### Fix
- **Rate limit → everything dead** — GET polls (HA sensors info/health/stats, UI, logs) no longer count toward the limit; only chat/mutating requests are throttled (180/min), with `Retry-After`

## 1.0.33

Creating an automation no longer fails under Eco Mode / local tool compaction.

### Fix
- **„Creează o automatizare” → no tools** — create/edit automation intents were classified as `control`, which hid `ha_create_automation`; they now escalate to `deep` and keep automations (+ reload) tools when compacting

## 1.0.32

Per-category toggles for what the secondary LLM may handle on tool rounds.

### Features
- **Secondary → Use for** — on each secondary provider, enable/disable web search, Frigate, skills, media, memory, bridge tools, and every Home Assistant tool category (lights/control, cameras stay separate via Frigate, dashboards, etc.)
- Defaults match 1.0.31: extras on secondary, HA categories stay on primary until opted in

## 1.0.31

Auxiliary (secondary) LLM only runs intermediate tool rounds; primary always speaks and owns memory.

### Features
- **Secondary = tools only** — Frigate/search/skills re-calls stay on secondary; if secondary returns text without tools, primary writes the final user-facing answer (stream + non-stream)
- **Memory on primary** — extract and consolidate (auto + manual) use the active primary provider, not secondary
- **Settings copy** — secondary descriptions clarify tools-only vs primary voice/memory

## 1.0.30

Gemini tool loops (HA / Frigate) no longer die with INVALID_ARGUMENT after the first tool.

### Fix
- **Gemini HTTP 400 after tools** — capture thought signatures from stream (incl. delta-level + missing index); inject skip when missing; on 400 retry force-overwrite bad/truncated signatures; omit `reasoning_effort` once a tool loop is in progress

## 1.0.29

Backup restore no longer hits HTTP 429 on large ZIP uploads.

### Fix
- **Restore ZIP → HTTP 429** — chunked import/export paths are exempt from the 60 req/min API rate limit (a ~20MB backup needs 80+ chunk POSTs)

## 1.0.28

Eco Mode settings tab — all compact/token options in one place.

### Features
- **Settings → Eco Mode** (replaces Security) — eco prompt, tool profile, compact history limit, tool-replay turns
- **Eco Mode now caps conversation history** the same way local AI does (was tools-only before)

## 1.0.27

Gemini tool loop after Frigate/HA no longer returns INVALID_ARGUMENT.

### Fix
- **Gemini HTTP 400 after tool calls (Frigate, HA, search)** — OpenAI-compat requires `name` on `role: tool` messages; bridge now always sends it and backfills from history on retry

## 1.0.26

Fix streaming chat crash on every provider.

### Fix
- **`Provider error: name 'max_tokens' is not defined`** — `chat_completion_stream` referenced `max_tokens` without declaring it; broke all streamed chat (local, OpenAI, Gemini, etc.)

## 1.0.25

Skip memory extraction on routine commands for every provider.

### Fix
- **Routine HA commands skip auto-extract everywhere** — lights, switches, cameras, status checks no longer trigger the memory LLM on local or cloud (explicit “ține minte” and mixed life-event messages still work)

## 1.0.24

Local AI speed, smarter memory, editable extraction prompt.

### Features
- **Local AI tool profiles (auto)** — simple HA commands send ~35 tools instead of ~108; compact HA prompt, shorter history, fewer tool-replay turns; cloud API unchanged unless Eco Mode is on
- **Local performance settings in UI** — tool profile, local history limit, tool replay turns (Providers → Local + Settings → Performance)
- **Editable memory extraction prompt** — Memories tab shows the default prompt; customize via `{existing_memories}`, `{conversation}`, `{today_date}`
- **Human-like episodic memory** — life events (restaurant, outings) stored with anchored dates; prompt guides “azi am mâncat pizza” → dated fact

### Fix
- **Memory no longer hoards HA registry data** — entity IDs, “device called…”, automation parroting rejected; pure light/irrigation commands skip auto-extract
- **Skip background memory extraction on local-only GPU** for routine turns (explicit “ține minte” still works)

## 1.0.23

Gemini HA fixes, smarter device status, better prompt cache.

### Fix
- **Gemini + HA tools no longer fail with generic INVALID_ARGUMENT** — do not send `reasoning_effort: none` alongside tools; auto-retry repairs payload (thought signatures + thinking) on 400
- **“Merge irigatorul?” checks device state, not automations** — HA agent prompt and tool docs steer status questions to `ha_list_entities` + `ha_get_state` instead of `ha_get_automation`

### Features
- **KV-cache friendly prompt layout** — memories inject on the last user turn so stable prefix + history cache across turns (DeepSeek, GLM, Grok, OpenAI, Qwen)
- **GLM Preserved Thinking** — `clear_thinking: false` + `reasoning_content` pass-back in tool loops for better cache hits on Z.ai

## 1.0.22

Faster HA commands, smarter light search, thinking controls for more providers.

### Features
- **Thinking in the chat bar for Gemini, GLM (Z.ai), and OpenAI reasoning models** — Auto / Off / High / Max maps to `reasoning_effort` (GPT-5 / o-series only for OpenAI; GPT-4o unchanged). Provider picker shows controls for the selected provider

### Fix
- **DeepSeek no longer forces heavy thinking on short HA commands** — “aprinde lumina” stays fast under Auto; planning questions still enable thinking
- **Light commands find relay switches too** — `domain=light` now includes `switch.*` (most relay bulbs); prompts and tool docs tell the model to use `switch.turn_on/off` when needed

### Note
- **GPT-5.6+ with HA tools** still requires `reasoning_effort: none` on OpenAI Chat Completions — the API rejects higher effort with tools; simple chat without tools respects your setting

## 1.0.21

Gemini tool calls work again.

### Fix
- **Gemini no longer fails with “missing thought_signature” when using tools.** Gemini 2.5/3 returns an encrypted signature on function calls; the bridge now preserves it during the tool loop and backfills a safe placeholder when replaying older history

## 1.0.20

Pick the default provider for everyone in one place.

### Features
- **Default provider for all users** — Settings → Providers has a dropdown at the top to set which provider every user gets when Auto mode is off. With Auto on, a hint explains this is only the fallback

## 1.0.19

Short chat on Auto uses the weak model again.

### Fix
- **Auto no longer stays on the planning model after a deep turn.** A sticky conversation kept the strong model for every follow-up, so “ce faci” on Grok answered with 4.6 even when 4.2 was set for short chat. The session still stays on the same provider (prompt cache), but each message picks fast or deep again. A new chat was already a fresh session; this also fixes follow-ups in the same thread
- **Message details show the model that actually answered**, not the default from Settings. With Auto on, the chat no longer labels every reply with the provider’s main model

## 1.0.18

Pick the weak and strong Auto models from a list.

### Features
- **Dropdowns for Auto role models** — after Fetch Models on a provider, the cheap/fast and strong/deep fields get the same selector as the main model, with a "same as above" option when you leave them empty

## 1.0.17

You can move a zoomed photo around now.

### Fix
- **Dragging a zoomed image works.** Zooming already worked, but the picture never moved, so you only ever saw the middle of it. Drag it with a finger or the mouse to reach the edges; it stops at its own border instead of sliding off into empty space, and a drag that ends outside the picture no longer closes the viewer

### Features
- **Zoom with the mouse** — the wheel zooms and a double-click toggles between fitted and zoomed; before this a pointer had no way to zoom at all
- **Fit button** while zoomed, to jump back to the whole picture

## 1.0.16

Follow-up commands work on the smaller models.

### Fix
- **The second command in a conversation is carried out, not just described.** On lighter models the first command ("turn on the terrace") worked, but the next one ("turn it off") came back as "done" without anything actually happening. The transcript was to blame: a turn that had called a tool was replayed as its sentence alone, so the model saw itself reporting success with no tool involved and copied that. History now shows the call, its result and the answer, so the pattern the model follows is the correct one. This is not tied to any language

## 1.0.15

Camera snapshots come back clean.

### Fix
- **No more broken "Generated image" under a snapshot** — camera snaps travelled in the same list as images the AI creates, so each one also got drawn a second time as a generated picture. The chat already shows the snapshot from the attachment; only images that really came from image generation are rendered that way now
- **No more `[Photos shown in chat: …]` in the reply** — that note is meant only for the AI, to tell it the picture was already displayed. Models copied it into their own answers, sometimes half-written. It is now removed from the reply, from the live text as it arrives, and from the saved message

## 1.0.14

Auto mode is now one tap away in the chat bar.

### Features
- **Auto in the provider picker** — the brain button in the composer lists Auto at the top, so you can switch between automatic selection and a specific provider without opening Settings. While Auto is on, the model selector is replaced by a note, since Auto picks the model itself
- Choosing a provider by hand turns Auto off, so your pick is not overridden on the next message

## 1.0.13

Auto mode now picks the model as well as the provider.

### Features
- **A cheap model and a strong one on the same provider** — each provider can name a model for short chat and device commands and another for planning and long context. Auto mode switches between them by itself, so DeepSeek can answer chitchat on `deepseek-chat` and plan on `deepseek-reasoner` without leaving the provider or its prompt cache. Leave them empty to keep using the single model as before
- Once a conversation moves up to the stronger model it stays there, same as it stays on its provider

### Fix
- **Changing a provider's type no longer leaves the old API URL behind.** Editing a provider and switching it to Gemini or Qwen kept the previous address, so it quietly kept calling the old API. A custom URL is still left alone — proxies are a real use — but a mismatched address now shows a warning naming the expected one, and a **Use default** button next to the field fills in the right URL for the selected type

## 1.0.12

Gemini and Qwen join the provider list, and the bridge can now pick the provider for you.

### Features
- **Gemini (Google) and Qwen (DashScope)** as provider types, primary and secondary. Pick the type and the URL fills itself in — Gemini uses the OpenAI-compatible endpoint, Qwen defaults to the international DashScope one (switch the host for a China key)
- **Auto mode** (Settings → Providers) picks the provider per message instead of always using the active one: cheap models for short chat and device commands, a stronger one for planning, a vision-capable one for photos. Roles are worked out from whatever providers you have, so it works the moment you switch it on
- A conversation **stays on its provider**, because moving mid-thread throws away the cached prompt — on DeepSeek that costs far more than the peak-hour surcharge it would avoid
- **Transparent failover** — if the chosen provider fails, Auto answers from the next healthy one instead of showing an error. A provider that keeps failing is skipped for a couple of minutes. Manual mode never switches behind your back
- **Estimated cost per provider** in Statistics, from a price table you can edit in Settings. Peak hours are part of that table, so a provider changing its pricing no longer needs a new release. Prices older than 90 days stop influencing Auto mode and say so

### Fix
- **GLM (z.ai)** — temperature above 1.0, forced tool choices, and functions without a description or parameters were all rejected by the API; requests are now shaped to what GLM accepts. Thinking mode and prompt-cache reporting work too
- **Qwen (DashScope)** — thinking is only requested while streaming, since several Qwen builds reject it on non-streaming calls, and it is left alone entirely on the always-thinking models
- **Photos in older messages** no longer break a reply after switching to a provider without vision

## 1.0.11

Provider Personality finally sticks, and web search sits with the other tool toggles.

### Fix
- **Provider Personality** — short tone/style notes on a provider no longer replace the global system prompt or get drowned by Bridge/agentic hints. Personality is layered on top of the global prompt and placed last among stable instructions so it shapes replies
- **Web search enable** — the SearXNG on/off toggle moves to Settings → General next to the other tool permissions; Search keeps URL and limits

## 1.0.10

Voice says the brand name as a word, not letter by letter.

### Fix
- **HASSAI pronunciation** — Chirp (and most TTS engines) spelled the all-caps brand as H-A-S-S-A-I. Spoken replies and the Voice Test button now rewrite it to “Hassai” before synthesis; the UI brand stays HASSAI

## 1.0.9

Full Settings backup made explicit, and Settings stops toasting on every open.

### Features
- **Backup covers every Settings tab** — the ZIP already carried the full `config.json` (Voice with Google key and Whisper/Piper URLs, Frigate, SearXNG, Memory, tool permissions, prompts, Eco Mode). A README inside the archive and clearer Settings → Backup copy now say so, and the manifest inventories which sections and secrets were packed

### Fix
- **Memory auto-consolidation actually saves** — the schedule was being written under SearXNG by mistake, so it never stuck
- **Settings no longer toasts “Users reloaded”** every time you open the page

## 1.0.8

Local Whisper and Piper speech, freely mixable with Google.

### Features
- **Local speech engines** — Settings → Voice picks speech-to-text and text-to-speech separately, so any combination works: local Whisper for the microphone with a Google voice for the reply, Google transcription with a local Piper voice, all-local, or all-cloud
- **Home Assistant add-ons out of the box** — a plain `host:port` (prefilled with `core_whisper:10300` and `core_piper:10200`) speaks the Wyoming protocol directly to the HA Whisper and Piper add-ons; an `http(s)` address is treated as an OpenAI-compatible speech API instead (speaches, faster-whisper-server, openedai-speech)
- Each local server has a Test Connection button, Piper can list the voices it actually has installed, and the Test button previews whichever text-to-speech engine is selected
- Hands-free conversation mode hides itself when no text-to-speech engine is configured, since it has to answer out loud

### Fix
- **Brain icon** — the model and thinking control in the chat bar showed a vague blob; it is now an actual brain

## 1.0.7

Choose which voice controls appear in the chat composer.

### Features
- **Voice controls visibility** — Settings → Voice → “Show in chat” lets you show conversation mode only (hands-free waveform), the push-to-talk microphone only, or both. Default remains both

## 1.0.6

Hands-free voice conversations, and the assistant stops narrating its steps into the chat.

### Features
- **Hands-free voice conversation** — a second button next to the microphone opens a full-screen voice mode. The mic stays open, speech is detected automatically, and pausing sends the question; the reply is spoken and then it listens again, so you never touch the screen. Talking over the assistant cuts it off and starts a new question
- Voice activity detection calibrates to the room's noise floor and keeps a short pre-roll, so the first word of a sentence is not clipped

### Fix
- **Step narration no longer lands in the reply** — when the model writes "let me find the terrace light… now I'll toggle it" on its way to calling a tool, that text now appears in the step timeline next to the tool calls instead of in the chat body. The saved message keeps only the actual answer, so history stays clean and the voice reads the answer rather than the play-by-play

## 1.0.5

Voice chat in Romanian, and a fix so weaker models stop faking device commands.

### Features
- **Voice chat (Google Chirp 3: HD)** — microphone button in the composer: speak, the question is transcribed and sent through the normal chat pipeline (so HA tools, cameras and memory all still work), and the reply is spoken back. Romanian voices are native, and Google's free tier of 1M characters per month renews monthly
- **Settings → Voice** — enable, Google API key with the five Google Cloud setup steps linked directly, language, voice picker with a Test button, speaking rate, spoken-reply length cap, autoplay toggle, plus a live check that warns when the page is not on HTTPS
- Assistant replies carry a replay button so a spoken answer can be heard again

### Fix
- **Thinking Auto + short HA commands** — phrases like "aprinde lumina" / "turn on the lights" no longer leave thinking off under Auto. Weaker DeepSeek models were skipping tools and inventing that they acted; Auto now forces thinking=high for control/camera/memory intents while greetings stay cheap

## 1.0.4

Memory as real tools, HASSAI self-awareness/self-control from chat, and header icon alignment.

### Features
- **Memory as real tools** — the assistant can now call `memory_save`, `memory_search`, `memory_list`, `memory_update` and `memory_forget`. "Ține minte că…" writes a memory on the spot instead of depending on the background extractor, and the step shows up in the activity strip as **Memorat**
- **Facts, not states** — memory refuses to store live device state, sensor readings and moment-scoped facts ("becul e aprins", "temperatura e 21°", "e acasă acum"); those are read live from Home Assistant every time. The extraction prompt spells the rule out and the same filter runs on whatever the extractor produces
- **HASSAI self-awareness** — a system block tells the model it *is* the HASSAI Bridge add-on and lists what it actually runs with, so it stops guessing about itself
- **Control HASSAI from chat** — new `hassai_status`, `hassai_get_settings`, `hassai_set_setting`, `hassai_list_providers`, `hassai_switch_provider` and `hassai_usage_stats` tools; the AI can report its version/provider/model and change allowlisted add-on settings, tool permissions, provider, model or Eco Mode (secrets stay unreadable and unwritable)
- **Settings → HASSAI Bridge tool permissions** — three toggles (memory, self status, self control), all on by default

### Fix
- **"Remember this" was sometimes ignored** — an explicit request now bypasses the trivial-message and signal pre-filters that used to drop short commands before extraction ran

### Polish
- **Chat header icons** — conversations button nudged further left, settings further right by the same amount (align with HA Ingress header)
- Activity strip labels for memory, HASSAI, Frigate and image-generation steps in both English and Romanian

## 1.0.3

### Fix
- **DeepSeek + camera/tool questions (HTTP 400)** — `reasoning_content` is now sent back on every assistant turn whenever a request carries tools, not only while thinking is on; short follow-ups like "dă ultimul snap" no longer break the conversation
- **Chat replay** — CoT stored in history is restored on transcripts replayed by the Web UI / Assist, and is kept verbatim instead of truncated
- **Self-healing** — if DeepSeek still rejects the pass-back (conversations started before this fix), the request retries automatically without thinking instead of surfacing a provider error

## 1.0.2

Stable patch release: HA admin tools, DeepSeek tool-loop fix, and add-on logo.

### Features
- **HA admin tools** — backups (list/create/restore), add-on lifecycle, updates, Core/host restart, network ping/port check, binary upload, ZHA/Z-Wave mesh actions, native automation/script create/edit
- **HA tool permissions** — Settings → General toggles per capability (all on by default); disabled tools are hidden from the AI

### Fix
- **DeepSeek thinking + tools** — pass `reasoning_content` back on assistant turns (in-loop and chat history) so Frigate/tool follow-ups no longer fail with HTTP 400

### Polish
- **Add-on logo** — new HassAI Bridge mark (house–cloud bridge icon) for `icon.png` and `logo.png` in the store

## 1.0.1

### Fix
- **Frigate chat spam** — detection questions answer in text only ( by default); only one snapshot when the user explicitly asks for a photo (reverts 1.0.0 multi-snap gallery)
- Richer event lines (zones, still on camera, stationary)


## 1.0.0

First stable release (end of beta).

### Fixes
- **Frigate snaps in follow-ups** — assistant Frigate/Imagine attachments stay visible in chat but are not replayed as `image_url` to the LLM (fixes DeepSeek Vision HTTP 400: "Image in assistant message is not supported")
- **Camera photos vs Imagine** — Frigate tools preferred for detections; `generate_image` excludes camera/NVR photos
- **Frigate status stuck on Checking** — Settings service pills no longer reset via i18n; fast Frigate probe + media fallback
- **Settings footer version** — no more double `v` (`vv0.2.x` → `v1.0.0`)

### Features / Polish
- **Multiple Frigate snapshots** — `include_snapshot=true` attaches up to 6 real event snaps
- **Image lightbox** — blurred/dimmed backdrop; pinch zoom on the photo only
- **Chat header icons** — slightly more inset on mobile
- **Settings sub-tabs** — General / Providers / … wrap as chips without overlapping


## 0.2.94-beta

### Feature
- **Frigate in Settings** — new Cameras tab: enable/disable, API URL, timeout, Test button; status card on Info dashboard

## 0.2.93-beta

### Feature
- **Frigate cameras** — agent tools `frigate_list_cameras`, `frigate_events`, `frigate_snapshot`: last detections + snapshot attached in chat (Frigate API, with `/media/frigate` fallback). Ask “ce se vede pe cameră / ce e pe afară” and the model can answer with time + photo.

## 0.2.92-beta

### Fix
- **Critical** — remove broken httpx AsyncClient request hook from 0.2.91 that caused `object NoneType can't be used in 'await' expression` on every chat (all providers). Token remap still runs in `finalize_http_payload` before POST.
- **Ingress 502/504 message** — no longer blames Grok Imagine; 502 means add-on unreachable, 504 means Ingress timeout

## 0.2.91-beta

### Fix
- **OpenAI GPT-5.6 (docs-aligned)** — always send `max_completion_tokens` (never `max_tokens`); httpx wire hook rewrites any leftover `max_tokens` on POSTs to `openai.com`; GPT-5.6+ with function tools sets `reasoning_effort: none` (Chat Completions requirement); provider errors include add-on version for debugging

## 0.2.90-beta

### Fix
- **OpenAI `max_tokens` HTTP 400** — final `finalize_http_payload` gate immediately before every httpx POST/stream to `api.openai.com`; logs a warning if `max_tokens` had to be stripped; auto-fixes empty `base_url` on OpenAI providers

## 0.2.89-beta

### Fix
- **OpenAI GPT 5.6 `max_tokens` HTTP 400** — remap even when provider type is mis-set to Local/Ollama but URL is OpenAI; detect gateway model ids (`openai/gpt-5.6`); final sanitize uses request URL so `max_tokens` cannot reach `api.openai.com`

## 0.2.88-beta

### Fix
- **OpenAI / ChatGPT `max_tokens`** — broader detection (provider named ChatGPT, all `gpt-*` / `o*` models); strip `max_tokens` on every outbound request so HTTP 400 cannot slip through

### Polish
- **Model dropdown** — opens upward when there is not enough space below (long model lists near the bottom of the screen)

## 0.2.87-beta

### Fix
- **Backup restore** — fix “cross-device link” when restoring from ZIP or upload (`/tmp` staging vs `/config` database); copy fallback instead of `rename` across mounts

## 0.2.86-beta

### Polish
- **Provider / model pickers** — themed listboxes in the chat bar settings (no native OS select chrome); thinking chips match the same surface language

### Feature
- **OpenAI prompt cache** — send `prompt_cache_key` (session id) for better cache hits; KV-friendly trim (~120K budget); log/track `cached_tokens` (and stream `include_usage`)

### Fix
- **OpenAI / ChatGPT `max_tokens`** — harder remap to `max_completion_tokens` (provider named ChatGPT, Azure URL, or gpt-5/o-series model ids) so HTTP 400 no longer slips through

## 0.2.84-beta

### Fix
- **OpenAI / ChatGPT** — send `max_completion_tokens` instead of `max_tokens` (fixes HTTP 400 on current models); omit temperature on o-series / GPT-5 where the API rejects it

## 0.2.83-beta

### Fix
- **Mobile header icons** — chats and settings sit further in from the edges so they line up with the Home Assistant hamburger, with equal spacing on both sides

## 0.2.82-beta

### Fix
- **Attach menu** — Home Assistant files hint is just “Din /share și /media”, without the “doesn’t leave the add-on” line

## 0.2.81-beta

### Feature
- **HASSAI can work with your files** — ask it to look through `/media` and `/share`, read a document or a photo, or delete a file (deleting always needs a confirmation)

### Removed
- **Send from the phone browser** — the link did not open from the Home Assistant app, so the option is gone

## 0.2.80-beta

### Feature
- **One + button in the composer** — opens a modal above everything with Photo, Document and Home Assistant files, instead of three icons in the bar
- **Send from the phone browser** — in the Home Assistant app, a one-time link opens the phone browser; the file you pick there lands in the chat by itself, so the native dialog never touches the add-on

### Fix
- **Document picker in the Home Assistant app** — a wildcard accept list keeps the in-app chooser instead of launching a separate file-manager app, which is what tore down the panel
- **Nothing is lost if the panel restarts** — typed message and pending attachments are restored when you come back

## 0.2.79-beta

### Fix
- **Attach files in the Home Assistant app** — the file input now sits on top of the attach buttons (the picker that works in the Companion WebView), the accept list is wider there, and drafts survive a WebView restart
- **Files already on Home Assistant** — folder button in the composer attaches photos and documents from `/share` and `/media`, with no file dialog at all
- **Backup import from /share** — back in Settings → Backup, for when the native dialog closes the add-on
- **Night greeting** — HA `clear-night` no longer greets with „Frumos și însorit” at midnight

### Feature
- **Enlarge images** — tap a chat photo for a full-screen view with download
- **Message details** — „De la” shows your username for your messages and the model for HASSAI's

## 0.2.78-beta

### Feature
- **Dynamic chat greetings** — empty chat shows a rotating title/hint based on time of day, holidays (e.g. Paște), and HA weather when available; no LLM calls
- **Softer composer placeholder** — “Scrie ceva…” / “Ask anything…” instead of “Mesaj către HASSAI…”
- **Settings toggle** — General → Dynamic greetings (on by default); off restores the classic fixed welcome
- **Message actions** — tap a message for Copy, Reuse / Use in composer, and Details (time, length, tools)
- **Document attach** — paperclip-style document button next to photos; PDF/TXT/MD/CSV/JSON (text extracted for the model)

## 0.2.76-beta

### Feature
- **Smooth streaming** — assistant text flows continuously (ChatGPT-like) instead of jumping in chunks; soft caret while generating

## 0.2.75-beta

### Feature
- **Background chat** — replies keep generating on the server if you leave the HA panel; return to see the finished answer in the same chat (Stop still cancels)

### Fix
- **Streaming on Ingress** — live tokens via activity poll (Grok / DeepSeek no longer wait for the full JSON blob)
- **Grok Imagine** — truncated/invalid image model ids resolve to a real Imagine model; Imagine models filtered out of the chat picker
- **Imagine + Ingress 504** — skip a second LLM round after image-only tool calls; clearer gateway timeout message
- **Grok reasoning_effort** — only sent for models that support it (avoids HTTP 400 on build/older reasoning models)

## 0.2.74-beta

### Fix
- **Backup** — removed Import from /share; after Import the page no longer reloads (that kicked HA Ingress); settings refresh in-place via JS
- **Export in Companion** — blob download no longer navigates the iframe away; use browser / Open Web UI to download

## 0.2.73-beta

### Fix
- **Backup rework** — opening Backup no longer scans `/media` (that crashed the add-on). One simple card: Export, browser Import, or Import from `/share` by filename. Restore closes DB connections and copies safely.

## 0.2.72-beta

### Fix
- **Companion Import (no file dialog)** — HA Companion app often never opens a file picker for Backup Import. New **Import from /share**: copy the ZIP into Home Assistant `/share`, then pick it from the list (no dialog). Browser Import still works as before.

## 0.2.71-beta

### Fix
- **Import in HA Companion app** — Backup Import uses a full-size transparent file input over the button (and `accept=*/*`) so the native picker opens in the Companion WebView; browser/mobile web already worked

## 0.2.70-beta

### Fix
- **Import file dialog** — Backup Import uses native label + hidden file input (HA WebView no longer blocks the picker)

## 0.2.69-beta

### Fix
- **Import on HA Ingress** — full ZIP and DB restore now upload in small chunks (no kick to HA dashboard); downloads use blob URLs instead of navigating the iframe

## 0.2.68-beta

### Feature
- **Export / Import** — Settings → Backup: full ZIP with config (providers, profiles, API keys), database, chat images, and generated skills; legacy DB-only backup kept

## 0.2.67-beta

### Fix
- **Image Generation LLM** — dropdown now lists all secondary providers (same as Vision / Secondary), not only type=Grok

## 0.2.66-beta

### Feature
- **Image Generation LLM** — per primary provider, assign a secondary for `generate_image` (e.g. DeepSeek chat + Grok Imagine for image creation)

## 0.2.65-beta

### Fix
- **Grok + images** — Grok primary (grok-4 / grok-4.6) now handles uploaded photos directly instead of routing away; use low reasoning effort on multimodal requests; still skip `generate_image` when user attaches photos

## 0.2.64-beta

### Fix
- **Grok + images** — grok-4/grok-4.6 no longer treated as vision models; image requests route to Vision LLM / global Grok vision secondary (same path as DeepSeek). Skip `generate_image` tool when the user attaches photos.

## 0.2.63-beta

### Fix
- **HA Companion app** — photo attach in chat via server upload; draft attachments survive WebView reload after gallery picker (mobile browser unchanged)

## 0.2.62-beta

### Fix
- **Mobile HA app** — photo attach in chat now works (label overlay picker, HEIC/`createImageBitmap` support, longer picker guard)

## 0.2.61-beta

### Feature
- **Brain popover** — switch active AI provider from chat (alongside model and thinking mode)

## 0.2.60-beta

### Fix
- **Mobile chat** — sidebar and settings buttons no longer overlap conversation bubbles (header is in layout flow)

## 0.2.59-beta

### UI
- **Settings** — «Înapoi la chat» button in the top bar returns to the chat home
- **Chat sidebar** — «Șterge toate conversațiile» deletes all sessions for the current user (with confirmation)

## 0.2.58-beta

### Fix
- **Generated images in chat** — `/api/chat/media/...` URLs now work under HA Ingress (no more broken image placeholders)

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
