# Changelog — HASSAI Bridge add-on

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
