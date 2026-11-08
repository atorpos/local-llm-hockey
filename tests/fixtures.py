"""Synthetic test pages (written for these tests, modelled on common site layouts)."""

REG = [  # season, team, league, GP G A PTS PIM | playoff GP G A PTS PIM
    ("2006–07", "London Knights", "OHL", 62, 25, 40, 65, 66, 16, 3, 8, 11, 12),
    ("2008–09", "London Knights", "OHL", 56, 25, 53, 78, 74, 14, 9, 12, 21, 25),
    ("2009–10", "Toronto Maple Leafs", "NHL", 1, 0, 0, 0, 0, None, None, None, None, None),
    ("2010–11", "Toronto Maple Leafs", "NHL", 29, 3, 9, 12, 8, None, None, None, None, None),
    ("2011–12", "Toronto Maple Leafs", "NHL", 21, 5, 2, 7, 8, None, None, None, None, None),
    ("2012–13", "Toronto Maple Leafs", "NHL", 48, 18, 26, 44, 23, 7, 1, 3, 4, 10),
    ("2013–14", "Toronto Maple Leafs", "NHL", 78, 20, 30, 50, 67, None, None, None, None, None),
    ("2014–15", "Toronto Maple Leafs", "NHL", 73, 18, 21, 39, 28, None, None, None, None, None),
    ("2015–16", "Toronto Maple Leafs", "NHL", 76, 17, 28, 45, 73, None, None, None, None, None),
    ("2016–17", "Toronto Maple Leafs", "NHL", 82, 32, 29, 61, 95, 6, 1, 1, 2, 8),
    ("2017–18", "Toronto Maple Leafs", "NHL", 80, 32, 23, 55, 42, 4, 0, 2, 2, 19),
    ("2018–19", "Toronto Maple Leafs", "NHL", 73, 16, 28, 44, 43, 2, 1, 1, 2, 19),
    ("2019–20", "Colorado Avalanche", "NHL", 51, 19, 17, 36, 97, 15, 9, 9, 18, 10),
    ("2020–21", "Colorado Avalanche", "NHL", 56, 11, 21, 32, 34, 2, 0, 1, 1, 10),
    ("2021–22", "Colorado Avalanche", "NHL", 71, 28, 59, 87, 71, 16, 7, 8, 15, 8),
    ("2022–23", "Calgary Flames", "NHL", 82, 24, 32, 56, 56, None, None, None, None, None),
    ("2023–24", "Calgary Flames", "NHL", 82, 29, 46, 75, 43, None, None, None, None, None),
    ("2024–25", "Calgary Flames", "NHL", 82, 35, 32, 67, 72, None, None, None, None, None),
    ("2025–26", "Calgary Flames", "NHL", 61, 12, 29, 41, 24, None, None, None, None, None),
    ("2025–26", "Colorado Avalanche", "NHL", 16, 4, 5, 9, 6, 13, 3, 6, 9, 4),
    ("2026–27", "Colorado Avalanche", "NHL", 16, 5, 9, 14, 4, None, None, None, None, None),
]
PM = {"2009–10": -1, "2010–11": -3, "2011–12": 2, "2012–13": 15, "2013–14": -11, "2014–15": -7, "2015–16": -15,
      "2016–17": -7, "2017–18": 2, "2018–19": -2, "2019–20": 7, "2020–21": -7, "2021–22": 13, "2022–23": -19,
      "2023–24": 0, "2024–25": -17}
PM_SPLIT = {("2025–26", "Calgary Flames"): -27, ("2025–26", "Colorado Avalanche"): -3,
            ("2026–27", "Colorado Avalanche"): 1}


def _c(v):
    return "—" if v is None else str(v)


def wiki_page() -> str:
    rows = "".join(
        f"<tr><td>{s}</td><td><a href='#'>{t}</a></td><td>{lg}</td>" + "".join(f"<td>{_c(v)}</td>" for v in vals) + "</tr>"
        for s, t, lg, *vals in REG)
    table = f"""<table class="wikitable">
<tbody><tr><th colspan="3"></th><th rowspan="99"></th><th colspan="5">Regular season</th>
<th rowspan="99"></th><th colspan="5">Playoffs</th></tr>
<tr><th>Season</th><th>Team</th><th>League</th><th>GP</th><th>G</th><th>A</th><th>Pts</th><th>PIM</th>
<th>GP</th><th>G</th><th>A</th><th>Pts</th><th>PIM</th></tr>
{rows}
<tr><th colspan="3">NHL totals</th><th>1,078</th><th>328</th><th>446</th><th>774</th><th>794</th>
<th>65</th><th>22</th><th>31</th><th>53</th><th>88</th></tr>
</tbody></table>"""
    return f"""<html><head><title>Nazem Kadri - Wikipedia</title></head><body><main>
<h1>Nazem Kadri</h1>
<p>Nazem Kadri (born October 6, 1990) is a Canadian professional ice hockey centre for the Colorado Avalanche
of the National Hockey League (NHL). Kadri was selected seventh overall by the Toronto Maple Leafs in the
2009 NHL entry draft. He shoots left.</p>
<h2>Toronto Maple Leafs</h2>
<p>Kadri spent parts of ten seasons with Toronto. On July 1, 2019, the Maple Leafs traded Kadri, Calle Rosen
and a 2020 third-round pick to the Colorado Avalanche in exchange for Tyson Barrie, Alexander Kerfoot and a
2020 sixth-round pick.</p>
<h2>Colorado Avalanche</h2>
<p>Kadri won the Stanley Cup with Colorado in 2022, scoring a career-high 87 points that season.</p>
<h2>Calgary Flames</h2>
<p>On August 18, 2022, Kadri signed a seven-year, $49 million contract with the Calgary Flames as a free agent.</p>
<p>At the 2026 trade deadline, on March 6, 2026, the Flames traded Kadri back to the Avalanche, retaining
20 percent of his salary.</p>
<h2>Career statistics</h2>
{table}
</main></body></html>"""


def hockeydb_page() -> str:
    """Different layout: has +/-; current season one game behind (updated later)."""
    body = []
    for s, t, lg, gp, g, a, pts, pim, pgp, pg, pa, ppts, ppim in REG:
        if lg != "NHL":
            continue
        if s == "2026–27":
            gp, g, a, pts, pim = 15, 5, 8, 13, 4
        pm = PM_SPLIT.get((s, t), PM.get(s))
        body.append(f"<tr><td>{s.replace('–', '-')}</td><td>{t}</td><td>NHL</td><td>{gp}</td><td>{g}</td><td>{a}</td>"
                    f"<td>{pts}</td><td>{pim}</td><td>{pm}</td><td>{_c(pgp)}</td><td>{_c(pg)}</td><td>{_c(pa)}</td>"
                    f"<td>{_c(ppts)}</td><td>{_c(ppim)}</td></tr>")
    return f"""<html><head><title>Nazem Kadri hockey statistics</title></head><body>
<h1>Nazem Kadri</h1><p>Nazem Kadri, centre. Shoots L. Born Oct 6 1990. Kadri career stats below.</p>
<table><tr><th></th><th></th><th></th><th colspan="6">Regular Season</th><th colspan="5">Playoffs</th></tr>
<tr><th>Season</th><th>Team</th><th>Lge</th><th>GP</th><th>G</th><th>A</th><th>Pts</th><th>PIM</th><th>+/-</th>
<th>GP</th><th>G</th><th>A</th><th>Pts</th><th>PIM</th></tr>
{''.join(body)}</table></body></html>"""


def capwages_page() -> str:
    return """<html><head><title>Nazem Kadri contract</title></head><body><article>
<h1>Nazem Kadri contract history</h1>
<p>Nazem Kadri is a centre under contract with the Colorado Avalanche. Kadri's current cap hit is $7,000,000.</p>
<p>Current contract: Kadri signed a 7 year contract with the Calgary Flames on August 18, 2022, worth a total of
$49,000,000 with an average annual value of $7,000,000. It includes a no-movement clause for the first three
seasons and a modified no-trade clause (13-team list) after that.</p>
<p>Extension: In April 2016 Kadri signed a 6 year extension with the Toronto Maple Leafs worth $27,000,000,
a cap hit of $4,500,000.</p>
<p>In July 2015 Kadri signed a 1 year contract with the Toronto Maple Leafs worth $4,100,000.</p>
<p>In September 2013 Kadri signed a 2 year contract with the Toronto Maple Leafs worth $5,800,000.</p>
<p>Entry-level contract: Kadri signed a 3 year entry-level contract with the Toronto Maple Leafs in 2009 with a
cap hit of $1,720,000 including performance bonuses.</p>
</article></body></html>"""


def espn_page() -> str:
    return """<html><head><title>Flames sign Kadri</title></head><body><article>
<h1>Flames land Kadri on seven-year deal</h1>
<p>The Calgary Flames signed center Nazem Kadri to a seven-year, $49 million contract on Thursday, Aug. 18, 2022.</p>
<p>The deal carries a $7 million average annual value. Kadri, 31, had 87 points for Colorado last season.</p>
<p>Kadri said he was excited to join Calgary after winning the Cup.</p>
</article></body></html>"""


def nhl_trade_page() -> str:
    return """<html><head><title>Kadri traded to Avalanche by Flames</title></head><body><article>
<h1>Kadri traded to Avalanche by Flames</h1>
<p>Nazem Kadri was traded to the Colorado Avalanche by the Calgary Flames on Friday, March 6, 2026.</p>
<p>Colorado received Kadri and a fourth-round pick in the 2027 NHL Draft. Calgary received forward Victor Olofsson,
forward prospect Maxmilian Curran, a conditional first-round pick in the 2028 NHL Draft and a conditional
second-round pick in the 2027 NHL Draft.</p>
<p>The Flames will retain 20 percent of Kadri's $7 million average annual value through 2028-29.</p>
<p>Kadri returns to the team he won the Stanley Cup with in 2022.</p>
</article></body></html>"""


def sportsnet_trade_page() -> str:
    return """<html><head><title>Maple Leafs trade Kadri to Avalanche</title></head><body><article>
<h1>Maple Leafs trade Kadri to Avalanche for Barrie, Kerfoot</h1>
<p>The Toronto Maple Leafs traded centre Nazem Kadri to the Colorado Avalanche on July 1, 2019.</p>
<p>Toronto also sent defenceman Calle Rosen and a third-round pick in 2020 to Colorado, and received defenceman
Tyson Barrie, forward Alexander Kerfoot and a sixth-round pick in 2020.</p>
<p>Kadri had waived his partial no-trade clause to approve the move.</p>
</article></body></html>"""


def unrelated_page() -> str:
    return """<html><body><article><h1>Makar leads Avalanche past Stars</h1>
<p>Cale Makar had two goals and an assist as the Colorado Avalanche beat the Dallas Stars 4-2 on Tuesday.
Nazem Kadri added an assist. Makar now has 21 points this season, and Colorado has won five straight.</p>
<p>The Avalanche play again Thursday.</p></article></body></html>"""


PAGES = {
    "https://en.wikipedia.org/wiki/Nazem_Kadri": wiki_page,
    "https://www.hockeydb.com/ihdb/stats/pdisplay.php?pid=97391": hockeydb_page,
    "https://capwages.com/players/nazem-kadri": capwages_page,
    "https://www.espn.com/nhl/story/kadri-flames": espn_page,
    "https://www.nhl.com/news/kadri-traded-to-avalanche": nhl_trade_page,
    "https://www.sportsnet.ca/nhl/leafs-trade-kadri": sportsnet_trade_page,
    "https://www.nhl.com/avalanche/news/makar-game-recap": unrelated_page,
}

# What a model might answer for each page. Includes deliberate mistakes the verifier must catch.
LLM_ANSWERS = {
    "https://en.wikipedia.org/wiki/Nazem_Kadri": {
        "page_is_about_player": True,
        "bio": {"position": "C", "shoots": "L", "birth_date": "October 6, 1990", "birthplace": "London, Ontario",
                "draft_year": 2009, "draft_round": 1, "draft_overall": 7, "draft_team": "Toronto Maple Leafs",
                "evidence": "Kadri was selected seventh overall by the Toronto Maple Leafs in the 2009 NHL entry draft."},
        "contracts": [
            {"team": "Calgary Flames", "contract_type": "ufa", "signing_date": "2022-08-18", "first_season": None,
             "term_years": 7, "total_value_usd": 49000000, "cap_hit_usd": None, "clauses": [],
             "evidence": "On August 18, 2022, Kadri signed a seven-year, $49 million contract with the Calgary Flames as a free agent."},
            # hallucination: this sentence is not on the page -> must be dropped
            {"team": "Colorado Avalanche", "contract_type": "extension", "signing_date": "2026-07-01",
             "first_season": "2029-30", "term_years": 3, "total_value_usd": 15000000, "cap_hit_usd": 5000000,
             "clauses": [], "evidence": "Kadri signed a three-year extension with Colorado worth $15 million."},
        ],
        "trades": [
            {"date": "2019-07-01", "from_team": "Toronto Maple Leafs", "to_team": "Colorado Avalanche",
             "new_team_received": ["Nazem Kadri", "Calle Rosen", "2020 3rd-round pick"],
             "old_team_received": ["Tyson Barrie", "Alexander Kerfoot", "2020 6th-round pick"],
             "salary_retained_pct": None,
             "evidence": "On July 1, 2019, the Maple Leafs traded Kadri, Calle Rosen and a 2020 third-round pick to the Colorado Avalanche"},
            {"date": "March 6, 2026", "from_team": "Flames", "to_team": "Avalanche",
             "new_team_received": ["Nazem Kadri"], "old_team_received": [], "salary_retained_pct": 20,
             "evidence": "At the 2026 trade deadline, on March 6, 2026, the Flames traded Kadri back to the Avalanche, retaining 20 percent of his salary."},
        ],
    },
    "https://capwages.com/players/nazem-kadri": {
        "page_is_about_player": True,
        "bio": {"position": "C", "shoots": None, "birth_date": None, "birthplace": None, "draft_year": None,
                "draft_round": None, "draft_overall": None, "draft_team": None, "evidence": None},
        "contracts": [
            {"team": "Calgary Flames", "contract_type": "ufa", "signing_date": "2022-08-18", "first_season": None,
             "term_years": 7, "total_value_usd": 49000000, "cap_hit_usd": 7000000,
             "clauses": ["no-movement clause (first three seasons)", "modified no-trade clause (13-team list)"],
             "evidence": "Current contract: Kadri signed a 7 year contract with the Calgary Flames on August 18, 2022, worth a total of $49,000,000 with an average annual value of $7,000,000."},
            {"team": "Toronto Maple Leafs", "contract_type": "extension", "signing_date": "2016-04", "first_season": None,
             "term_years": 6, "total_value_usd": 27000000, "cap_hit_usd": 4500000, "clauses": [],
             "evidence": "Extension: In April 2016 Kadri signed a 6 year extension with the Toronto Maple Leafs worth $27,000,000, a cap hit of $4,500,000."},
            {"team": "Toronto Maple Leafs", "contract_type": "rfa", "signing_date": "2015-07", "first_season": None,
             "term_years": 1, "total_value_usd": 4100000, "cap_hit_usd": 4100000, "clauses": [],
             "evidence": "In July 2015 Kadri signed a 1 year contract with the Toronto Maple Leafs worth $4,100,000."},
            # wrong cap hit (2,950,000 is not on the page) -> must be removed, then re-derived from total/term
            {"team": "Toronto Maple Leafs", "contract_type": "rfa", "signing_date": "September 2013", "first_season": None,
             "term_years": 2, "total_value_usd": 5800000, "cap_hit_usd": 2950000, "clauses": [],
             "evidence": "In September 2013 Kadri signed a 2 year contract with the Toronto Maple Leafs worth $5,800,000."},
            {"team": "Toronto Maple Leafs", "contract_type": "entry_level", "signing_date": "2009", "first_season": None,
             "term_years": 3, "total_value_usd": None, "cap_hit_usd": 1720000, "clauses": [],
             "evidence": "Entry-level contract: Kadri signed a 3 year entry-level contract with the Toronto Maple Leafs in 2009 with a cap hit of $1,720,000 including performance bonuses."},
        ],
        "trades": [],
    },
    "https://www.espn.com/nhl/story/kadri-flames": {
        "page_is_about_player": True,
        "bio": {"position": None, "shoots": None, "birth_date": None, "birthplace": None, "draft_year": None,
                "draft_round": None, "draft_overall": None, "draft_team": None, "evidence": None},
        "contracts": [
            {"team": "Calgary Flames", "contract_type": "ufa", "signing_date": "2022-08-18", "first_season": None,
             "term_years": 7, "total_value_usd": 49000000, "cap_hit_usd": 7000000, "clauses": [],
             "evidence": "The Calgary Flames signed center Nazem Kadri to a seven-year, $49 million contract on Thursday, Aug. 18, 2022."},
        ],
        "trades": [],
    },
    "https://www.nhl.com/news/kadri-traded-to-avalanche": {
        "page_is_about_player": True,
        "bio": {"position": None, "shoots": None, "birth_date": None, "birthplace": None, "draft_year": None,
                "draft_round": None, "draft_overall": None, "draft_team": None, "evidence": None},
        "contracts": [],
        "trades": [
            {"date": "2026-03-06", "from_team": "Calgary Flames", "to_team": "Colorado Avalanche",
             "new_team_received": ["Nazem Kadri", "2027 4th-round pick"],
             "old_team_received": ["Victor Olofsson", "Maxmilian Curran", "Conditional 2028 1st-round pick",
                                   "Conditional 2027 2nd-round pick"],
             "salary_retained_pct": 20,
             "evidence": "Nazem Kadri was traded to the Colorado Avalanche by the Calgary Flames on Friday, March 6, 2026."},
        ],
    },
    "https://www.sportsnet.ca/nhl/leafs-trade-kadri": {
        "page_is_about_player": True,
        "bio": {"position": "C", "shoots": None, "birth_date": None, "birthplace": None, "draft_year": None,
                "draft_round": None, "draft_overall": None, "draft_team": None, "evidence": None},
        "contracts": [],
        "trades": [
            {"date": "2019-07-01", "from_team": "Toronto Maple Leafs", "to_team": "Colorado Avalanche",
             "new_team_received": ["Nazem Kadri", "Calle Rosen", "2020 3rd-round pick"],
             "old_team_received": ["Tyson Barrie", "Alexander Kerfoot", "2020 6th-round pick"],
             # wrong: 50 % is not on the page -> must be removed
             "salary_retained_pct": 50,
             "evidence": "The Toronto Maple Leafs traded centre Nazem Kadri to the Colorado Avalanche on July 1, 2019."},
        ],
    },
}
