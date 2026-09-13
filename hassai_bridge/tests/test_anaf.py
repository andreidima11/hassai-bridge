"""ANAF company lookup tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from services import anaf as anaf_ro
from services import secondary_routing as sr
from services import toolkits as tk


def test_normalize_cui():
    assert anaf_ro.normalize_cui("RO 1590082") == "1590082"
    assert anaf_ro.normalize_cui("2816464") == "2816464"
    assert anaf_ro.normalize_cui("abc") == ""
    assert anaf_ro.parse_cui_list("RO1590082, 2816464") == ["1590082", "2816464"]


def test_cui_checksum():
    assert anaf_ro.cui_checksum_ok("1590082") is True
    assert anaf_ro.cui_checksum_ok("2816464") is True
    assert anaf_ro.cui_checksum_ok("1234567") is False


def test_tools_are_core():
    assert tk.is_core_tool("anaf_firma") is True
    assert tk.is_core_tool("anaf_bilant") is True
    assert tk.pack_for_tool("anaf_firma") is None
    assert sr.tool_use_for_category("anaf_bilant") == "web_search"


def _sample_firma():
    return {
        "found": [{
            "date_generale": {
                "cui": 2816464,
                "denumire": "DEDEMAN SRL",
                "nrRegCom": "J04/262/1992",
                "cod_CAEN": "4752",
                "stare_inregistrare": "INREGISTRAT",
                "data_inregistrare": "1992-01-01",
                "forma_juridica": "SRL",
                "forma_organizare": "PERSOANA JURIDICA",
                "forma_de_proprietate": "PRIVATA",
                "organFiscalCompetent": "AJFP Bacau",
                "statusRO_e_Factura": True,
                "adresa": "Bacau",
            },
            "inregistrare_scop_Tva": {"scpTVA": True, "perioade_TVA": []},
            "inregistrare_RTVAI": {"statusTvaIncasare": False},
            "stare_inactiv": {"statusInactivi": False},
            "inregistrare_SplitTVA": {"statusSplitTVA": False},
            "adresa_sediu_social": {
                "sdenumire_Strada": "Str. Alexei Tolstoi",
                "snumar_Strada": "8",
                "sdenumire_Localitate": "Bacău",
                "sdenumire_Judet": "Bacău",
                "scod_Postal": "600017",
            },
            "adresa_domiciliu_fiscal": {},
        }],
        "notFound": [],
    }


def test_firma_and_bilant_mocked():
    async def _run():
        with patch.object(anaf_ro, "_post_tva", new=AsyncMock(return_value=_sample_firma())):
            text = await anaf_ro.firma("RO2816464")
            assert "DEDEMAN SRL (CUI 2816464)" in text
            assert "TVA: da" in text
            assert "RO e-Factura: da" in text

        sample_bilant = {
            "an": 2023,
            "cui": 2816464,
            "deni": "DEDEMAN SRL",
            "caen": 4752,
            "den_caen": "Comert",
            "i": [
                {"indicator": "I13", "val_indicator": 1e9, "val_den_indicator": "Cifra de afaceri neta"},
                {"indicator": "I18", "val_indicator": 1e8, "val_den_indicator": "Profit net"},
                {"indicator": "I20", "val_indicator": 100, "val_den_indicator": "Numar mediu de salariati"},
            ],
        }

        class FakeResp:
            status_code = 200
            text = ""

            def json(self):
                return sample_bilant

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return FakeResp()

        with patch.object(anaf_ro.httpx, "AsyncClient", FakeClient):
            bil = await anaf_ro.bilant("2816464", an=2023)
            assert "DEDEMAN SRL" in bil
            assert "Profit net" in bil
            assert "100" in bil

    asyncio.run(_run())


def test_invoke_anaf_firma(monkeypatch):
    from routers import chat as chat_mod

    async def _fake(cui, *, day=None):
        return f"ok {cui} @{day}"

    monkeypatch.setattr(chat_mod.anaf_ro, "firma", _fake)
    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "anaf_firma",
            {"cui": "1590082"},
            search_enabled=False,
        )
    )
    assert used is False
    assert "ok 1590082" in text
