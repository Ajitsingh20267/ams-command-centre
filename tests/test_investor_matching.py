from app.agents.investor_matching import score_match, top_matches


def test_sector_and_geography_match_scores_high():
    client = {"sector": "Commercial real estate", "geography": "USA",
              "funding_requirement_min": None, "funding_requirement_max": None,
              "instrument": "Refinancing", "stage": ""}
    investor = {"entity_name": "Test Fund", "sectors": "Real estate credit; special situations",
                "geographies": "North America; Europe", "ticket_min": None, "ticket_max": None,
                "structures": "Direct lending", "stage_preference": "All",
                "eligibility_category": "UK FPO Art 19", "sanctions_checked": "CLEARED"}
    result = score_match(client, investor)
    assert result["sector_fit"] and result["sector_fit"] >= 50
    assert result["geography_fit"] and result["geography_fit"] >= 50
    assert result["match_score"] > 50
    assert "confidence" not in " ".join(result["concerns"]).lower() or \
        result["confidence_fit"] == 100


def test_no_overlap_scores_zero_not_fabricated():
    client = {"sector": "Mining", "geography": "Brazil", "instrument": "Equity", "stage": ""}
    investor = {"entity_name": "UK Hospitality Fund", "sectors": "Restaurants and bars",
                "geographies": "United Kingdom", "structures": "Direct equity",
                "stage_preference": "", "eligibility_category": "PROVISIONAL",
                "sanctions_checked": "UNSCREENED"}
    result = score_match(client, investor)
    assert result["sector_fit"] == 0
    assert result["geography_fit"] == 0
    assert any("PROVISIONAL" in c for c in result["concerns"])
    assert any("sanctions" in c.lower() for c in result["concerns"])


def test_ticket_undisclosed_is_excluded_not_penalised():
    client = {"sector": "Consumer", "geography": "India", "funding_requirement_min": None,
              "funding_requirement_max": None, "instrument": "", "stage": ""}
    investor = {"entity_name": "X", "sectors": "Consumer", "geographies": "India",
                "ticket_min": 10_000_000, "ticket_max": 50_000_000,
                "structures": "", "stage_preference": "", "eligibility_category": "",
                "sanctions_checked": "CLEARED"}
    result = score_match(client, investor)
    assert result["ticket_fit"] is None
    assert any("undisclosed" in c for c in result["concerns"])


def test_ticket_range_overlap_scores_full():
    client = {"sector": "", "geography": "", "funding_requirement_min": 90_000_000,
              "funding_requirement_max": 95_000_000, "instrument": "", "stage": ""}
    investor = {"entity_name": "X", "sectors": "", "geographies": "",
                "ticket_min": 20_000_000, "ticket_max": 100_000_000,
                "structures": "", "stage_preference": "", "eligibility_category": "",
                "sanctions_checked": "CLEARED"}
    result = score_match(client, investor)
    assert result["ticket_fit"] == 100


def test_top_matches_ranks_descending_and_respects_limit():
    client = {"sector": "Consumer", "geography": "India", "instrument": "", "stage": ""}
    investors = [
        {"entity_name": f"Investor {i}", "sectors": "Consumer" if i % 2 == 0 else "Mining",
         "geographies": "India", "structures": "", "stage_preference": "",
         "eligibility_category": "", "sanctions_checked": "CLEARED"}
        for i in range(15)
    ]
    top = top_matches(client, investors, top_n=10)
    assert len(top) == 10
    scores = [m["match_score"] for m in top]
    assert scores == sorted(scores, reverse=True)
