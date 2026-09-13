"""ANAF public company lookup (Romania) via PlatitorTvaRest + bilanț.

No API key. Lookup is by CUI only — if the user gives a company name,
search_web for the CUI first, then call these tools.
Docs: https://www.anaf.ro/anaf/internet/ANAF/servicii_online/servicii_web_anaf/
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import httpx

log = logging.getLogger("hassai.anaf")

_TIMEOUT = httpx.Timeout(20.0, connect=6.0)
_HEADERS = {
    "User-Agent": "HASSAI-Bridge/1.0 (+https://github.com/andreidima11/hassai-bridge)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

_TVA_URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
_BILANT_URL = "https://webservicesp.anaf.ro/bilant"

_MAX_BATCH = 8
_CUI_DIGITS = re.compile(r"^\d{2,10}$")

# Key bilanț indicators to surface (code → short label).
_BILANT_FOCUS = {
    "I1": "Active imobilizate",
    "I2": "Active circulante",
    "I7": "Datorii",
    "I10": "Capitaluri",
    "I13": "Cifră de afaceri netă",
    "I14": "Venituri totale",
    "I15": "Cheltuieli totale",
    "I16": "Profit brut",
    "I18": "Profit net",
    "I20": "Nr. mediu salariați",
}


def normalize_cui(raw: Any) -> str:
    """Strip RO/spaces; return digits only or ''."""
    s = str(raw or "").strip().upper().replace(" ", "")
    if s.startswith("RO"):
        s = s[2:]
    s = re.sub(r"\D", "", s)
    if not _CUI_DIGITS.match(s):
        return ""
    # Drop leading zeros for API, but keep at least one digit.
    s = s.lstrip("0") or "0"
    if s == "0":
        return ""
    return s


def parse_cui_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = re.split(r"[,;\s]+", str(raw).strip())
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        c = normalize_cui(p)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= _MAX_BATCH:
            break
    return out


def cui_checksum_ok(cui: str) -> bool:
    """Romanian CUI control digit (mod 11). True if unknown length edge cases skip."""
    digits = normalize_cui(cui)
    if not digits or len(digits) < 2:
        return False
    body, check = digits[:-1], int(digits[-1])
    # Pad to 9 digits for the classic algorithm used by ANAF / ONRC tools.
    body = body.zfill(9)[-9:]
    weights = (7, 5, 3, 2, 1, 7, 5, 3, 2)
    total = sum(int(d) * w for d, w in zip(body, weights))
    control = total * 10 % 11
    if control == 10:
        control = 0
    return control == check


def _yn(v: Any) -> str:
    if v is True:
        return "da"
    if v is False:
        return "nu"
    return "?"


def _fmt_money(n: Any) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "?"
    if abs(v) >= 1e9:
        return f"{v / 1e9:.2f} mld RON"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.2f} mil RON"
    return f"{v:,.0f} RON"


def _pick(d: dict | None, *keys: str) -> str:
    if not isinstance(d, dict):
        return ""
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in {"none", "null"}:
            return s
    return ""


def _format_address(block: dict | None, prefix: str) -> str:
    if not isinstance(block, dict):
        return ""
    # sediu: s*, domiciliu: d*
    p = prefix
    street = _pick(block, f"{p}denumire_Strada", f"{p}denumire_strada")
    nr = _pick(block, f"{p}numar_Strada", f"{p}numar_strada")
    loc = _pick(block, f"{p}denumire_Localitate", f"{p}denumire_localitate")
    jud = _pick(block, f"{p}denumire_Judet", f"{p}denumire_judet")
    cp = _pick(block, f"{p}cod_Postal", f"{p}cod_postal")
    det = _pick(block, f"{p}detalii_Adresa", f"{p}detalii_adresa")
    bits = []
    if street:
        bits.append(street + (f" {nr}" if nr else ""))
    elif nr:
        bits.append(f"nr. {nr}")
    if loc:
        bits.append(loc)
    if jud:
        bits.append(jud)
    if cp:
        bits.append(f"CP {cp}")
    if det:
        bits.append(det)
    return ", ".join(bits)


def format_firma_row(row: dict[str, Any]) -> str:
    g = row.get("date_generale") if isinstance(row.get("date_generale"), dict) else {}
    tva = row.get("inregistrare_scop_Tva") if isinstance(row.get("inregistrare_scop_Tva"), dict) else {}
    rtvai = row.get("inregistrare_RTVAI") if isinstance(row.get("inregistrare_RTVAI"), dict) else {}
    inactive = row.get("stare_inactiv") if isinstance(row.get("stare_inactiv"), dict) else {}
    split = row.get("inregistrare_SplitTVA") if isinstance(row.get("inregistrare_SplitTVA"), dict) else {}
    sediu = row.get("adresa_sediu_social") if isinstance(row.get("adresa_sediu_social"), dict) else {}
    domiciliu = row.get("adresa_domiciliu_fiscal") if isinstance(row.get("adresa_domiciliu_fiscal"), dict) else {}

    cui = _pick(g, "cui") or "?"
    name = _pick(g, "denumire") or "?"
    lines = [
        f"{name} (CUI {cui})",
        f"Reg. Com.: {_pick(g, 'nrRegCom') or '—'}",
        f"CAEN: {_pick(g, 'cod_CAEN') or '—'}",
        f"Stare: {_pick(g, 'stare_inregistrare') or '—'}",
        f"Înregistrată: {_pick(g, 'data_inregistrare') or '—'}",
        f"Formă: {_pick(g, 'forma_juridica') or '—'} · {_pick(g, 'forma_organizare') or ''}".rstrip(" ·"),
        f"Proprietate: {_pick(g, 'forma_de_proprietate') or '—'}",
        f"Organ fiscal: {_pick(g, 'organFiscalCompetent') or '—'}",
    ]
    sediu_s = _format_address(sediu, "s") or _pick(g, "adresa")
    dom_s = _format_address(domiciliu, "d")
    if sediu_s:
        lines.append(f"Sediu: {sediu_s}")
    if dom_s and dom_s != sediu_s:
        lines.append(f"Domiciliu fiscal: {dom_s}")
    tel = _pick(g, "telefon")
    if tel:
        lines.append(f"Telefon: {tel}")
    iban = _pick(g, "iban")
    if iban:
        lines.append(f"IBAN: {iban}")

    lines.append(
        f"TVA: {_yn(tva.get('scpTVA'))} · "
        f"TVA la încasare: {_yn(rtvai.get('statusTvaIncasare'))} · "
        f"Split TVA: {_yn(split.get('statusSplitTVA'))} · "
        f"RO e-Factura: {_yn(g.get('statusRO_e_Factura'))} · "
        f"Inactiv: {_yn(inactive.get('statusInactivi'))}"
    )
    if inactive.get("statusInactivi"):
        bits = [
            f"inactivare {_pick(inactive, 'dataInactivare')}",
            f"reactivare {_pick(inactive, 'dataReactivare')}",
            f"radiere {_pick(inactive, 'dataRadiere')}",
        ]
        lines.append("Inactiv detalii: " + " · ".join(b for b in bits if not b.endswith(" ")))
    return "\n".join(lines)


async def _post_tva(cuis: list[str], day: str) -> dict[str, Any]:
    body = [{"cui": int(c), "data": day} for c in cuis]
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        resp = await client.post(_TVA_URL, json=body)
        # ANAF returns 404 with valid JSON when nothing found.
        if resp.status_code not in (200, 404):
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("unexpected ANAF payload")
        return data


async def firma(
    cui: str | list | None,
    *,
    day: str | None = None,
) -> str:
    cuis = parse_cui_list(cui)
    if not cuis:
        return (
            "Error: need a Romanian CUI (digits, optional RO prefix). "
            "If you only have the company name, use search_web to find the CUI first."
        )
    day_s = (day or "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(day_s)
    except ValueError:
        return "Error: data must be YYYY-MM-DD."

    warns = []
    for c in cuis:
        if not cui_checksum_ok(c):
            warns.append(f"CUI {c} failed checksum (may still exist)")

    try:
        data = await _post_tva(cuis, day_s)
    except Exception as e:
        return f"Error: ANAF TVA API unavailable: {e}"

    found = data.get("found") if isinstance(data.get("found"), list) else []
    not_found = data.get("notFound") if isinstance(data.get("notFound"), list) else []
    parts: list[str] = []
    if warns:
        parts.append("Note: " + "; ".join(warns))
    parts.append(f"ANAF · data interogării {day_s}")
    if found:
        for row in found:
            if isinstance(row, dict):
                parts.append(format_firma_row(row))
                parts.append("---")
        if parts[-1] == "---":
            parts.pop()
    if not_found:
        nf = ", ".join(str(x) for x in not_found)
        parts.append(f"Negăsite: {nf}")
    if not found and not not_found:
        parts.append("No results.")
    return "\n".join(parts)


async def bilant(cui: str, *, an: int | str | None = None) -> str:
    c = normalize_cui(cui)
    if not c:
        return (
            "Error: need a Romanian CUI. "
            "If you only have the company name, use search_web to find the CUI first."
        )
    year = an
    if year is None or str(year).strip() == "":
        year = date.today().year - 1
    try:
        year_i = int(year)
    except (TypeError, ValueError):
        return "Error: an must be a year like 2023."
    if year_i < 2000 or year_i > date.today().year:
        return f"Error: year {year_i} out of range."

    params = {"cui": c, "an": str(year_i)}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(_BILANT_URL, params=params)
            if resp.status_code == 404:
                return f"Error: no bilanț for CUI {c} / {year_i}."
            if resp.status_code != 200:
                return f"Error: ANAF bilanț HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
    except Exception as e:
        return f"Error: ANAF bilanț unavailable: {e}"

    if not isinstance(data, dict):
        return "Error: unexpected bilanț payload."

    name = _pick(data, "deni", "denumire") or "?"
    caen = _pick(data, "caen", "cod_CAEN")
    den_caen = _pick(data, "den_caen")
    lines = [
        f"Bilanț ANAF · {name} (CUI {c}) · an {data.get('an') or year_i}",
    ]
    if caen:
        lines.append(f"CAEN: {caen}" + (f" — {den_caen}" if den_caen else ""))

    indicators = data.get("i") if isinstance(data.get("i"), list) else []
    by_code: dict[str, dict] = {}
    for row in indicators:
        if not isinstance(row, dict):
            continue
        code = str(row.get("indicator") or "").strip().upper()
        if code:
            by_code[code] = row

    shown = 0
    for code, label in _BILANT_FOCUS.items():
        row = by_code.get(code)
        if not row:
            continue
        val = row.get("val_indicator")
        den = (_pick(row, "val_den_indicator") or label).rstrip(": ").strip() or label
        if code == "I20":
            try:
                lines.append(f"{den}: {int(float(val))}")
            except (TypeError, ValueError):
                lines.append(f"{den}: {val}")
        else:
            lines.append(f"{den}: {_fmt_money(val)}")
        shown += 1

    if shown == 0 and indicators:
        # Fallback: first few indicators
        for row in indicators[:12]:
            if not isinstance(row, dict):
                continue
            den = _pick(row, "val_den_indicator") or str(row.get("indicator") or "?")
            lines.append(f"{den}: {_fmt_money(row.get('val_indicator'))}")
            shown += 1

    if shown == 0:
        lines.append("No indicators in response.")
    return "\n".join(lines)


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "anaf_firma",
            "description": (
                "Look up a Romanian company on the official ANAF public API by CUI "
                "(tax ID). Returns name, Reg. Com., CAEN, addresses, VAT / inactive / "
                "e-Factura flags. "
                "CUI only — if the user gives a company name (e.g. 'detalii Dedeman'), "
                "use search_web first to find the CUI, then call this tool. "
                "Accepts optional RO prefix and up to 8 CUIs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cui": {
                        "type": "string",
                        "description": "CUI or comma-separated CUIs (e.g. 'RO1590082' or '2816464').",
                    },
                    "data": {
                        "type": "string",
                        "description": "Optional inquiry date YYYY-MM-DD (default: today).",
                    },
                },
                "required": ["cui"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "anaf_bilant",
            "description": (
                "Fetch published annual financial indicators (bilanț) from ANAF for a "
                "Romanian company CUI: turnover, profit, employees, assets, debts. "
                "Requires CUI — resolve the name via search_web first if needed. "
                "Default year is last calendar year."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cui": {
                        "type": "string",
                        "description": "Company CUI (digits, optional RO).",
                    },
                    "an": {
                        "type": "integer",
                        "description": "Fiscal year (e.g. 2023). Default: previous year.",
                    },
                },
                "required": ["cui"],
            },
        },
    },
]

TOOL_NAMES = frozenset({"anaf_firma", "anaf_bilant"})
