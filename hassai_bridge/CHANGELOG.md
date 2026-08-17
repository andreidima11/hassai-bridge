# Changelog — HASSAI Bridge add-on

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
