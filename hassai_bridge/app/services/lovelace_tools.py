"""Pure Lovelace helpers (testable without a live Home Assistant instance)."""

from __future__ import annotations

import json
from typing import Any


DEFAULT_URL_PATH_ALIASES = {"", "default", "overview", "(default)"}
NESTED_CARD_TYPES = frozenset({"vertical-stack", "horizontal-stack", "grid", "stack"})
HA_LOVELACE_TOOLS = frozenset({
    "ha_list_dashboards",
    "ha_get_dashboard",
    "ha_create_dashboard",
    "ha_save_dashboard",
    "ha_upsert_view",
    "ha_upsert_section",
    "ha_upsert_card",
    "ha_delete_card",
    "ha_delete_view",
    "ha_update_dashboard",
    "ha_delete_dashboard",
    "ha_append_card_yaml",
    "ha_list_lovelace_resources",
})
HA_MUTATING_TOOLS = frozenset({
    "ha_save_dashboard",
    "ha_create_dashboard",
    "ha_upsert_view",
    "ha_upsert_section",
    "ha_upsert_card",
    "ha_delete_card",
    "ha_delete_view",
    "ha_update_dashboard",
    "ha_delete_dashboard",
    "ha_append_card_yaml",
    "ha_write_file",
    "ha_apply_fix",
    "ha_call_service",
    "ha_reload",
})


def ws_url_path(url_path: str | None) -> str | None:
    path = (url_path or "").strip().strip("/")
    if path.lower() in DEFAULT_URL_PATH_ALIASES:
        return None
    return path or None


def normalize_lovelace_config(result: Any) -> dict:
    if isinstance(result, dict):
        if "views" in result:
            return result
        if isinstance(result.get("config"), dict):
            return result["config"]
        if "strategy" in result:
            raise RuntimeError(
                "strategy dashboards (for example Map) cannot be edited with card tools; "
                "use the Home Assistant UI or recreate the dashboard."
            )
    if isinstance(result, list):
        return {"views": result}
    raise RuntimeError("unexpected Lovelace config payload from Home Assistant")


def parse_lovelace_url(url: str) -> dict[str, str | None]:
    """Parse common HA dashboard URLs into dashboard url_path and view path."""
    raw = (url or "").strip()
    if not raw:
        return {"url_path": None, "view_path": None}

    if raw.startswith("http://") or raw.startswith("https://"):
        from urllib.parse import urlparse

        raw = urlparse(raw).path or ""

    path = raw.split("?", 1)[0].strip("/")
    if not path:
        return {"url_path": None, "view_path": None}

    parts = [p for p in path.split("/") if p]
    if not parts:
        return {"url_path": None, "view_path": None}

    if parts[0] == "lovelace":
        rest = parts[1:]
        if not rest:
            return {"url_path": None, "view_path": None}
        if rest[0].isdigit() or rest[0] in {"0", "home", "hass"}:
            view_path = rest[0] if rest[0] != "0" else None
            if len(rest) > 1:
                view_path = rest[1]
            return {"url_path": None, "view_path": view_path}
        return {"url_path": None, "view_path": rest[0]}

    if parts[0].startswith("dashboard-"):
        url_path = parts[0][len("dashboard-") :]
        view_path = parts[1] if len(parts) > 1 else None
        return {"url_path": url_path or None, "view_path": view_path}

    return {"url_path": parts[0], "view_path": parts[1] if len(parts) > 1 else None}


def view_type(view: dict) -> str:
    return str((view or {}).get("type") or "masonry").lower()


def is_sections_view(view: dict) -> bool:
    return view_type(view) == "sections"


def _view_label(view: dict, index: int) -> str:
    title = (view or {}).get("title")
    path = (view or {}).get("path")
    if title:
        return str(title)
    if path:
        return str(path)
    return str(index)


def _view_path(view: dict, index: int) -> str:
    path = (view or {}).get("path")
    if path:
        return str(path)
    return str(index)


def _selector_provided(args: dict) -> bool:
    return any(
        args.get(key) not in (None, "")
        for key in ("view_index", "view_title", "view_path")
    )


def pick_view(cfg: dict, args: dict) -> tuple[int, dict]:
    views = cfg.get("views")
    if not isinstance(views, list) or not views:
        raise RuntimeError("dashboard has no views")

    if args.get("view_index") is not None:
        idx = int(args["view_index"])
        if idx < 0 or idx >= len(views):
            raise RuntimeError(f"view_index {idx} out of range 0..{len(views)-1}")
        return idx, views[idx]

    view_path = (args.get("view_path") or "").strip().strip("/").lower()
    if view_path:
        for i, view in enumerate(views):
            candidate = _view_path(view, i).lower()
            if candidate == view_path:
                return i, view
        raise RuntimeError(
            f"no view with path '{args.get('view_path')}'. "
            "Use ha_get_dashboard to list views, or ha_upsert_view to create one."
        )

    title = (args.get("view_title") or "").strip().lower()
    if title:
        matches: list[tuple[int, dict]] = []
        for i, view in enumerate(views):
            vt = str((view or {}).get("title") or (view or {}).get("path") or "").lower()
            if title in vt:
                matches.append((i, view))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(_view_label(v, i) for i, v in matches)
            raise RuntimeError(f"view_title '{args.get('view_title')}' matched multiple views: {names}")
        raise RuntimeError(
            f"no view matching title '{args.get('view_title')}'. "
            "Use ha_get_dashboard to list views, or ha_upsert_view to create one."
        )

    if _selector_provided(args):
        raise RuntimeError("view selector did not match any view")

    return 0, views[0]


def ensure_sections(view: dict) -> list[dict]:
    sections = view.get("sections")
    if not isinstance(sections, list):
        sections = []
        view["sections"] = sections
    return sections


def ensure_default_section(view: dict) -> tuple[int, dict]:
    sections = ensure_sections(view)
    if not sections:
        section = {"type": "grid", "cards": []}
        sections.append(section)
        return 0, section
    return len(sections) - 1, sections[-1]


def pick_section(view: dict, args: dict, *, create: bool = False) -> tuple[int, dict]:
    if not is_sections_view(view):
        raise RuntimeError(
            f"view type '{view_type(view)}' does not use sections; cards live on view.cards"
        )

    sections = ensure_sections(view)
    if not sections:
        if create:
            return ensure_default_section(view)
        raise RuntimeError("sections view has no sections; set create_section=true or use ha_upsert_section")

    if args.get("section_index") is not None:
        sidx = int(args["section_index"])
        if sidx < 0 or sidx >= len(sections):
            raise RuntimeError(f"section_index {sidx} out of range 0..{len(sections)-1}")
        section = sections[sidx]
        if not isinstance(section, dict):
            raise RuntimeError(f"section {sidx} is not an object")
        return sidx, section

    title = (args.get("section_title") or "").strip().lower()
    if title:
        for i, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            heading = _section_heading(section).lower()
            if title in heading:
                return i, section
        raise RuntimeError(f"no section matching title '{args.get('section_title')}'")

    if args.get("create_section") is True and create:
        section = {"type": "grid", "cards": []}
        sections.append(section)
        return len(sections) - 1, section

    return len(sections) - 1, sections[-1]


def _section_heading(section: dict) -> str:
    cards = section.get("cards") or []
    if cards and isinstance(cards[0], dict):
        first = cards[0]
        if first.get("type") == "heading":
            return str(first.get("heading") or first.get("title") or "")
    return str(section.get("title") or "")


class CardContainer:
    __slots__ = ("kind", "view", "section_index", "cards")

    def __init__(self, kind: str, view: dict, cards: list, section_index: int | None = None):
        self.kind = kind
        self.view = view
        self.section_index = section_index
        self.cards = cards

    def write_back(self, cards: list) -> None:
        if self.kind == "sections":
            sections = ensure_sections(self.view)
            section = sections[self.section_index or 0]
            section["cards"] = cards
            sections[self.section_index or 0] = section
            self.view["sections"] = sections
        else:
            self.view["cards"] = cards


def card_container(view: dict, args: dict, *, create_section: bool = False) -> CardContainer:
    if is_sections_view(view):
        sidx, section = pick_section(view, args, create=create_section)
        cards = list(section.get("cards") or [])
        return CardContainer("sections", view, cards, sidx)

    cards = list(view.get("cards") or [])
    if view_type(view) == "panel" and args.get("card_index") is None and cards:
        # Panel views only show one card; replacing is safer than silently appending.
        pass
    return CardContainer("cards", view, cards)


def card_summary(card: dict, index: int) -> str:
    ctype = (card or {}).get("type", "?")
    bits = [f"#{index}", ctype]
    for key in ("entity", "entities", "heading", "title", "name"):
        val = (card or {}).get(key)
        if isinstance(val, str) and val:
            bits.append(val)
            break
        if isinstance(val, list) and val:
            bits.append(str(val[0]))
            break
    return " ".join(bits)


def summarize_view(view: dict, index: int, *, include_cards: bool = False) -> str:
    label = _view_label(view, index)
    path = _view_path(view, index)
    vtype = view_type(view)
    lines = [f"view {index}  path={path}  type={vtype}  title={label!r}"]

    if is_sections_view(view):
        sections = view.get("sections") or []
        if not isinstance(sections, list):
            sections = []
        total_cards = 0
        lines.append(f"  sections={len(sections)}")
        for sidx, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            cards = section.get("cards") or []
            total_cards += len(cards)
            heading = _section_heading(section) or f"section {sidx}"
            lines.append(f"    section {sidx}  {heading!r}  cards={len(cards)}")
            if include_cards:
                for cidx, card in enumerate(cards):
                    if isinstance(card, dict):
                        lines.append(f"      {card_summary(card, cidx)}")
        lines.append(f"  total_cards={total_cards}")
    else:
        cards = view.get("cards") or []
        lines.append(f"  cards={len(cards)}")
        if include_cards:
            for cidx, card in enumerate(cards):
                if isinstance(card, dict):
                    lines.append(f"    {card_summary(card, cidx)}")

    return "\n".join(lines)


def summarize_dashboard(
    url_path: str | None,
    cfg: dict,
    *,
    mode: str = "storage",
    include_cards: bool = False,
) -> str:
    shown_path = url_path or "(default)"
    views = cfg.get("views") or []
    if not isinstance(views, list):
        views = []
    lines = [
        f"dashboard: {shown_path}",
        f"mode: {mode}",
        f"views: {len(views)}",
    ]
    for idx, view in enumerate(views):
        if isinstance(view, dict):
            lines.append(summarize_view(view, idx, include_cards=include_cards))
    return "\n".join(lines)


def upsert_view_in_config(cfg: dict, args: dict) -> tuple[int, dict, str]:
    views = cfg.setdefault("views", [])
    if not isinstance(views, list):
        raise RuntimeError("dashboard config views must be a list")

    view_body = args.get("view")
    if isinstance(view_body, dict):
        new_view = dict(view_body)
    else:
        title = (args.get("title") or args.get("view_title") or "New view").strip()
        path = (args.get("path") or args.get("view_path") or "").strip().strip("/")
        new_view = {
            "title": title,
            "type": (args.get("view_type") or args.get("type") or "sections").strip() or "sections",
        }
        if path:
            new_view["path"] = path
        if args.get("icon"):
            new_view["icon"] = args["icon"]
        if new_view["type"] == "sections":
            new_view["sections"] = [{"type": "grid", "cards": []}]

    if args.get("view_index") is not None:
        idx = int(args["view_index"])
        if idx < 0 or idx >= len(views):
            raise RuntimeError(f"view_index {idx} out of range 0..{len(views)-1}")
        views[idx] = new_view
        return idx, new_view, f"replaced view {idx}"

    selector = (args.get("view_path") or args.get("path") or "").strip().strip("/").lower()
    if selector:
        for i, existing in enumerate(views):
            if _view_path(existing, i).lower() == selector:
                views[i] = new_view
                return i, new_view, f"replaced view {i} ({selector})"

    views.append(new_view)
    idx = len(views) - 1
    return idx, new_view, f"created view {idx}"


def upsert_section_in_view(view: dict, args: dict) -> tuple[int, dict, str]:
    if not is_sections_view(view):
        raise RuntimeError("ha_upsert_section requires a sections view")
    sections = ensure_sections(view)
    section = args.get("section")
    if isinstance(section, dict):
        new_section = dict(section)
    else:
        new_section = {"type": "grid", "cards": []}
        if args.get("title"):
            new_section["cards"] = [{"type": "heading", "heading": args["title"]}]

    if args.get("section_index") is not None:
        sidx = int(args["section_index"])
        if sidx < 0 or sidx >= len(sections):
            raise RuntimeError(f"section_index {sidx} out of range 0..{len(sections)-1}")
        sections[sidx] = new_section
        return sidx, new_section, f"replaced section {sidx}"

    sections.append(new_section)
    sidx = len(sections) - 1
    return sidx, new_section, f"created section {sidx}"


def resolve_dashboard_args(args: dict) -> dict:
    """Merge dashboard_url (/lovelace/foo or /dashboard-bar/baz) into url_path/view_path."""
    merged = dict(args or {})
    raw_url = (merged.get("dashboard_url") or merged.get("ha_url") or "").strip()
    if not raw_url:
        return merged
    parsed = parse_lovelace_url(raw_url)
    if not merged.get("url_path") and parsed.get("url_path") is not None:
        merged["url_path"] = parsed["url_path"] or ""
    if not merged.get("view_path") and parsed.get("view_path"):
        merged["view_path"] = parsed["view_path"]
    if not merged.get("view_title") and parsed.get("view_path") and not merged.get("view_path"):
        merged["view_path"] = parsed["view_path"]
    return merged


def append_card_to_yaml(data: Any, args: dict, card: dict) -> tuple[Any, str]:
    """Append a card into a parsed YAML Lovelace config."""
    if not isinstance(data, dict):
        raise RuntimeError("YAML root must be a mapping with a views list")
    cfg = data
    views = cfg.get("views")
    if not isinstance(views, list) or not views:
        raise RuntimeError("YAML has no views")
    idx, view = pick_view(cfg, args)
    container = card_container(view, args, create_section=bool(args.get("create_section")))
    cards = list(container.cards)
    cards.append(card)
    container.write_back(cards)
    cfg["views"][idx] = view
    label = _view_label(view, idx)
    return cfg, f"appended card #{len(cards)-1} on view {idx} ({label})"


def delete_view_in_config(cfg: dict, args: dict) -> tuple[int, dict, str]:
    views = cfg.get("views")
    if not isinstance(views, list) or not views:
        raise RuntimeError("dashboard has no views")
    if len(views) <= 1:
        raise RuntimeError("cannot delete the last remaining view on a dashboard")
    idx, view = pick_view(cfg, args)
    label = _view_label(view, idx)
    views.pop(idx)
    cfg["views"] = views
    return idx, view, f"deleted view {idx} ({label})"


def dump_json(obj: Any, max_chars: int = 14_000) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n… truncated ({len(text)} chars). Use ha_get_dashboard without full=true."
    return text


def yaml_dashboard_file(url_path: str | None) -> str | None:
    ws_path = ws_url_path(url_path)
    if ws_path is None:
        ui = "ui-lovelace.yaml"
        return ui
    candidate = f"dashboards/{ws_path}.yaml"
    return candidate


def mutate_card_in_view(
    view: dict,
    args: dict,
    *,
    card: dict | None = None,
    delete: bool = False,
    create_section: bool = False,
) -> tuple[str, dict | None]:
    """Insert, replace, or delete a card. Supports optional dotted card_path (e.g. 2.1)."""
    container = card_container(view, args, create_section=create_section)
    cards = list(container.cards)
    removed: dict | None = None

    card_path = (args.get("card_path") or "").strip()
    if card_path:
        parts = [int(p) for p in card_path.split(".") if p.isdigit()]
        if not parts:
            raise RuntimeError("invalid card_path")
        if len(parts) > 2:
            raise RuntimeError("card_path supports forms like 2 or 2.1")

        if len(parts) == 1:
            parent_idx = parts[0]
            if parent_idx < 0 or parent_idx >= len(cards):
                raise RuntimeError(f"card_path {parent_idx} out of range 0..{len(cards)-1}")
            if delete or args.get("card_index") is not None:
                cidx = parent_idx if args.get("card_index") is None else int(args["card_index"])
                if delete:
                    removed = cards.pop(cidx)
                    container.write_back(cards)
                    return f"deleted card #{cidx} (type={(removed or {}).get('type', '?')})", removed
                if card is None:
                    raise RuntimeError("card is required")
                cards[cidx] = card
                container.write_back(cards)
                return f"replaced card #{cidx}", None

            parent = cards[parent_idx]
            if str(parent.get("type") or "") not in NESTED_CARD_TYPES:
                raise RuntimeError(
                    f"card {parent_idx} type={parent.get('type')} has no nested cards"
                )
            nested = list(parent.get("cards") or [])
            if card is None:
                raise RuntimeError("card is required")
            nested.append(card)
            parent["cards"] = nested
            cards[parent_idx] = parent
            container.write_back(cards)
            return f"appended nested card {parent_idx}.{len(nested)-1}", None

        parent_idx, child_idx = parts
        if parent_idx < 0 or parent_idx >= len(cards):
            raise RuntimeError(f"card_path root {parent_idx} out of range 0..{len(cards)-1}")
        parent = cards[parent_idx]
        if str(parent.get("type") or "") not in NESTED_CARD_TYPES:
            raise RuntimeError(
                f"card {parent_idx} type={parent.get('type')} has no nested cards"
            )
        nested = list(parent.get("cards") or [])
        if delete:
            if child_idx < 0 or child_idx >= len(nested):
                raise RuntimeError(
                    f"nested card {child_idx} out of range 0..{len(nested)-1}"
                )
            removed = nested.pop(child_idx)
            parent["cards"] = nested
            cards[parent_idx] = parent
            container.write_back(cards)
            return (
                f"deleted nested card {parent_idx}.{child_idx} "
                f"(type={(removed or {}).get('type', '?')})",
                removed,
            )
        if card is None:
            raise RuntimeError("card is required")
        if child_idx >= len(nested):
            nested.append(card)
            parent["cards"] = nested
            cards[parent_idx] = parent
            container.write_back(cards)
            return f"appended nested card {parent_idx}.{len(nested)-1}", None
        nested[child_idx] = card
        parent["cards"] = nested
        cards[parent_idx] = parent
        container.write_back(cards)
        return f"replaced nested card {parent_idx}.{child_idx}", None

    if delete:
        cidx = int(args.get("card_index"))
        if cidx < 0 or cidx >= len(cards):
            raise RuntimeError(f"card_index {cidx} out of range 0..{len(cards)-1}")
        removed = cards.pop(cidx)
        action = f"deleted card #{cidx} (type={(removed or {}).get('type', '?')})"
    elif args.get("card_index") is None:
        if card is None:
            raise RuntimeError("card is required")
        cards.append(card)
        action = f"appended card #{len(cards)-1}"
    else:
        cidx = int(args["card_index"])
        if cidx < 0 or cidx >= len(cards):
            raise RuntimeError(f"card_index {cidx} out of range 0..{len(cards)-1}")
        if card is None:
            raise RuntimeError("card is required")
        cards[cidx] = card
        action = f"replaced card #{cidx}"

    container.write_back(cards)
    return action, removed


def dashboard_error_hint(tool_name: str, message: str) -> str | None:
    lower = message.lower()
    if any(token in lower for token in ("storage mode", "yaml mode", "not in storage", "yaml only")):
        return (
            "This dashboard is YAML mode. Use ha_append_card_yaml, ha_read_file / ha_write_file, "
            "then ha_reload what=lovelace confirm=true."
        )
    if "strategy" in lower:
        return "Strategy dashboards cannot be edited with card tools."
    if tool_name.startswith("ha_") and any(token in lower for token in ("not_found", "404", "unknown path")):
        return (
            "Check dashboard url_path (Overview/default uses an empty url_path) versus view path/title. "
            "Use ha_list_dashboards and ha_get_dashboard before saving."
        )
    return None
