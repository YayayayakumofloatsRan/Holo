from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, resolve_issuer_identity
from kernel_v3.retrieval import QueryPlan, SearchGoal, SecEdgarSearchProvider


def test_phase100_issuer_identity_resolves_sec_ticker_and_cik_from_metadata():
    identity = resolve_issuer_identity(
        "Apple annual filing",
        {
            "ticker": "aapl",
            "sec_cik": "320193",
            "company": "Apple Inc.",
        },
    )

    assert identity.ticker == "AAPL"
    assert identity.cik == "0000320193"
    assert identity.company == "Apple Inc."
    assert identity.confidence == 0.92
    assert identity.identifiers["sec_cik"] == "0000320193"


def test_phase100_issuer_identity_uses_injected_ticker_cik_map_without_network():
    identity = resolve_issuer_identity(
        "MSFT SEC companyfacts revenue",
        {"sec_ticker_cik_map": {"MSFT": "789019"}},
    )

    assert identity.ticker == "MSFT"
    assert identity.cik == "0000789019"
    assert "metadata_ticker_cik_map" in identity.sources


def test_phase100_issuer_identity_resolves_common_us_company_name_in_finance_context():
    identity = resolve_issuer_identity(
        "NVIDIA fundamentals revenue net income",
        {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )

    assert identity.ticker == "NVDA"
    assert identity.cik == "0001045810"
    assert identity.company == "NVIDIA Corporation"
    assert "builtin_issuer_registry" in identity.sources


def test_phase100_issuer_identity_ignores_finance_acronyms_as_us_tickers():
    identity = resolve_issuer_identity("SEC EDGAR API JSON companyfacts")

    assert identity.ticker is None
    assert identity.cik is None
    assert identity.confidence == 0.0


def test_phase100_issuer_identity_extracts_exchange_codes_for_non_us_sources():
    asx = resolve_issuer_identity("ASX:BHP annual report")
    hk = resolve_issuer_identity("HKEX 700 annual report")
    sgx = resolve_issuer_identity("SGX D05 financial results")

    assert asx.asx_code == "BHP"
    assert asx.market == "ASX"
    assert hk.hkex_code == "00700"
    assert hk.market == "HKEX"
    assert sgx.sgx_code == "D05"
    assert sgx.market == "SGX"


def test_phase100_non_us_exchange_code_is_not_misread_as_sec_ticker():
    identity = resolve_issuer_identity("ASX:BHP annual report")
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "ASX:BHP annual report",
        goal=SearchGoal(
            goal_id="goal-sec-non-us",
            query="ASX:BHP annual report",
            max_sources=5,
            metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
        ),
        plan=QueryPlan(
            plan_id="plan-sec-non-us",
            goal_id="goal-sec-non-us",
            queries=["ASX:BHP annual report"],
            max_sources=5,
            max_fetches=3,
        ),
    )

    assert identity.asx_code == "BHP"
    assert identity.ticker is None
    assert sources == []
    assert provider.search_diagnostics()["reason"] == "missing_sec_identifier"


def test_phase100_sec_edgar_provider_uses_shared_identity_resolution():
    provider = SecEdgarSearchProvider()

    sources = provider.search(
        "MSFT SEC companyfacts revenue",
        goal=SearchGoal(
            goal_id="goal-sec-identity",
            query="MSFT SEC companyfacts revenue",
            max_sources=5,
            metadata={
                "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
                "sec_ticker_cik_map": {"MSFT": "789019"},
            },
        ),
        plan=QueryPlan(
            plan_id="plan-sec-identity",
            goal_id="goal-sec-identity",
            queries=["MSFT SEC companyfacts revenue"],
            max_sources=5,
            max_fetches=3,
        ),
    )

    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json" in [source.uri for source in sources]
    diagnostics = provider.search_diagnostics()
    assert diagnostics["ticker"] == "MSFT"
    assert diagnostics["cik_present"] is True
    assert "metadata_ticker_cik_map" in diagnostics["identity_sources"]
