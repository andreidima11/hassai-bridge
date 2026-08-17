# Changelog — HASSAI Bridge add-on

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
