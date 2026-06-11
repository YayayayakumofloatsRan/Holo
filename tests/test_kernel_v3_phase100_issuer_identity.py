from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, resolve_issuer_identity
from kernel_v3.research.issuer_registry import builtin_issuers_for_text
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


def test_phase100_issuer_identity_resolves_common_financial_issuers_in_finance_context():
    goldman = resolve_issuer_identity(
        "Goldman Sachs net revenues 2024 10-K",
        {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )
    blackrock = resolve_issuer_identity(
        "BlackRock total revenues annual report",
        {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )

    assert goldman.ticker == "GS"
    assert goldman.cik == "0000886982"
    assert goldman.company == "The Goldman Sachs Group, Inc."
    assert "builtin_issuer_registry" in goldman.sources
    assert blackrock.ticker == "BLK"
    assert blackrock.cik == "0002012383"
    assert blackrock.company == "BlackRock, Inc."
    assert "builtin_issuer_registry" in blackrock.sources


def test_issuer_identity_enriches_known_ticker_with_registry_urls():
    identity = resolve_issuer_identity(
        "BLK total revenues 2024 SEC companyfacts",
        {
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "ticker": "BLK",
            "sec_cik": "2012383",
        },
    )

    assert identity.ticker == "BLK"
    assert identity.cik == "0002012383"
    assert identity.company == "BlackRock, Inc."
    assert identity.identifiers["annual_reports_url"] == (
        "https://ir.blackrock.com/financials/annual-reports-and-proxy/default.aspx"
    )
    assert "builtin_issuer_registry" in identity.sources


def test_phase100_issuer_identity_ignores_finance_acronyms_as_us_tickers():
    identity = resolve_issuer_identity("SEC EDGAR API JSON companyfacts")

    assert identity.ticker is None
    assert identity.cik is None
    assert identity.confidence == 0.0


def test_issuer_identity_ignores_source_url_label_as_us_ticker():
    identity = resolve_issuer_identity(
        "Source URL: https://example.com/annual-report.pdf in USD millions",
        {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )

    assert identity.ticker is None
    assert identity.cik is None


def test_builtin_issuer_registry_does_not_match_benchmark_target_label_as_target_corp():
    matches = builtin_issuers_for_text("Benchmark target source follows. Source URL: https://example.com/report.pdf")

    assert all(match["ticker"] != "TGT" for match in matches)


def test_issuer_identity_resolves_3m_company_name_in_finance_context():
    identity = resolve_issuer_identity(
        "3M 2018 10-K capital expenditure",
        {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID, "company": "3M"},
    )

    assert identity.ticker == "MMM"
    assert identity.cik == "0000066740"
    assert identity.company == "3M"


def test_issuer_identity_ignores_finance_formula_acronyms_as_us_tickers():
    identity = resolve_issuer_identity(
        "Compare Home Depot and Lowe's fiscal 2024 DIO using SEC 10-K companyfacts.",
        {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )

    assert identity.ticker == "HD"
    assert identity.cik == "0000354950"
    assert identity.company == "The Home Depot, Inc."


def test_builtin_issuer_registry_does_not_match_lowercase_finance_words_as_tickers():
    matches = builtin_issuers_for_text("HD 2024 inventory cost of revenue and cost of goods sold")

    assert [match["ticker"] for match in matches] == ["HD"]


def test_sec_edgar_provider_returns_structured_sources_for_all_requested_issuers():
    provider = SecEdgarSearchProvider()
    query = "For NYSE: HD and NYSE: LOW, calculate FY2024 DIO using inventory and cost of goods sold."
    goal = SearchGoal(
        goal_id="goal-hd-low-sec",
        query=query,
        max_sources=8,
        metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )

    sources = provider.search(
        query,
        goal=goal,
        plan=QueryPlan(
            plan_id="plan-hd-low-sec",
            goal_id=goal.goal_id,
            queries=[query],
            max_sources=8,
            max_fetches=8,
        ),
    )
    uris = [source.uri for source in sources]

    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000354950.json" in uris
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000060667.json" in uris
    assert "https://data.sec.gov/api/xbrl/companyfacts/CIK0000909832.json" not in uris
    assert provider.search_diagnostics()["issuer_candidate_count"] == 2


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


def test_phase100_target_revenue_does_not_resolve_to_target_corporation():
    issuers = builtin_issuers_for_text(
        "Pfizer Seagen acquisition transaction value enterprise value target revenue"
    )

    tickers = {str(item.get("ticker")) for item in issuers}
    assert "PFE" in tickers
    assert "SGEN" in tickers
    assert "TGT" not in tickers
