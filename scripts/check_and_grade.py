#!/usr/bin/env python3
"""check_and_grade.py — Fetch scores and grade all 3 sports.

Self-contained script (no cross-repo imports) designed to run in GitHub Actions
every 2 hours. Uses Odds API for NBA/NHL scores and ESPN for NCAAB.

Usage:
    ODDS_API_KEY=... python scripts/check_and_grade.py
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta

# ── Configuration ────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"

# Odds API full team name -> abbreviation (NBA)
NBA_TEAM_MAP = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}

# Odds API full team name -> abbreviation (NHL)
NHL_TEAM_MAP = {
    "Anaheim Ducks": "ANA", "Arizona Coyotes": "ARI", "Boston Bruins": "BOS",
    "Buffalo Sabres": "BUF", "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR",
    "Chicago Blackhawks": "CHI", "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ",
    "Dallas Stars": "DAL", "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM",
    "Florida Panthers": "FLA", "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN",
    "Montréal Canadiens": "MTL", "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD",
    "New York Islanders": "NYI", "New York Rangers": "NYR",
    "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS", "Seattle Kraken": "SEA", "St. Louis Blues": "STL",
    "St Louis Blues": "STL", "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
    "Utah Hockey Club": "UTA", "Utah Mammoth": "UTA",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}


# ── Score Fetching ───────────────────────────────────────────────


def fetch_odds_api_scores(sport_key, team_map, api_key):
    """Fetch scores from Odds API for a given sport.

    Returns dict: {"AWAY@HOME": {away_score, home_score, completed}}
    """
    if not api_key:
        print(f"  [{sport_key}] No API key — skipping")
        return {}

    url = f"{ODDS_API_BASE}/{sport_key}/scores/"
    try:
        resp = requests.get(url, params={"apiKey": api_key, "daysFrom": 2}, timeout=15)
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  [{sport_key}] API {resp.status_code} (requests remaining: {remaining})")
        if resp.status_code != 200:
            print(f"  [{sport_key}] API error: {resp.text[:200]}")
            return {}

        scores = {}
        for ev in resp.json():
            away_full = ev.get("away_team", "")
            home_full = ev.get("home_team", "")
            away_abbr = team_map.get(away_full)
            home_abbr = team_map.get(home_full)
            if not away_abbr or not home_abbr:
                continue

            score_list = ev.get("scores") or []
            score_map = {}
            for s in score_list:
                if s and s.get("score"):
                    score_map[s["name"]] = int(s["score"])

            away_score = score_map.get(away_full)
            home_score = score_map.get(home_full)
            if away_score is None or home_score is None:
                continue

            key = f"{away_abbr}@{home_abbr}"
            scores[key] = {
                "away_score": away_score,
                "home_score": home_score,
                "completed": ev.get("completed", False),
            }

        print(f"  [{sport_key}] Got scores for {len(scores)} games")
        return scores

    except Exception as e:
        print(f"  [{sport_key}] Score fetch error: {e}")
        return {}


def fetch_nba_scores(api_key):
    return fetch_odds_api_scores("basketball_nba", NBA_TEAM_MAP, api_key)


def fetch_nhl_scores(api_key):
    return fetch_odds_api_scores("icehockey_nhl", NHL_TEAM_MAP, api_key)


def fetch_ncaab_scores(date_str):
    """Fetch NCAAB scores from ESPN (free, no API key needed).

    Args:
        date_str: Date in 'YYYY-MM-DD' format

    Returns dict: {"AWAY@HOME": {away_score, home_score, completed}}
    """
    date_fmt = date_str.replace("-", "")
    url = f"{ESPN_BASE}/scoreboard"
    params = {"dates": date_fmt, "limit": 300, "groups": 50}

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        scores = {}
        for event in data.get("events", []):
            status_type = event.get("status", {}).get("type", {}).get("name", "")
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])

            if len(competitors) != 2:
                continue

            home_comp = away_comp = None
            for comp in competitors:
                if comp.get("homeAway") == "home":
                    home_comp = comp
                else:
                    away_comp = comp

            if not home_comp or not away_comp:
                continue

            home_abbr = home_comp.get("team", {}).get("abbreviation", "")
            away_abbr = away_comp.get("team", {}).get("abbreviation", "")
            home_score = int(home_comp.get("score", 0) or 0)
            away_score = int(away_comp.get("score", 0) or 0)

            key = f"{away_abbr}@{home_abbr}"
            completed = status_type == "STATUS_FINAL"

            scores[key] = {
                "away_score": away_score,
                "home_score": home_score,
                "completed": completed,
            }

        print(f"  [NCAAB] ESPN {date_str}: {len(scores)} games")
        return scores

    except Exception as e:
        print(f"  [NCAAB] ESPN fetch error for {date_str}: {e}")
        return {}


# ── Grading Functions ────────────────────────────────────────────


def grade_spread(game, away_score, home_score):
    """Grade a spread pick. Returns 'W', 'L', or 'P' (push)."""
    pick_str = game.get("spread_pick", "")
    if not pick_str or pick_str == "N/A":
        return None

    parts = pick_str.rsplit(" ", 1)
    if len(parts) < 2:
        return None

    pick_team = parts[0]
    try:
        line = float(parts[1])
    except (ValueError, IndexError):
        return None

    if pick_team == game["home_team"]:
        margin = home_score - away_score + line
    else:
        margin = away_score - home_score + line

    if margin > 0:
        return "W"
    elif margin < 0:
        return "L"
    return "P"


def grade_total(game, away_score, home_score):
    """Grade a total pick. Returns 'W', 'L', or 'P' (push)."""
    pick = game.get("total_pick")
    line = game.get("total_line")
    if not pick or line is None:
        return None

    actual_total = away_score + home_score
    if pick == "OVER":
        if actual_total > line:
            return "W"
        elif actual_total < line:
            return "L"
        return "P"
    else:  # UNDER
        if actual_total < line:
            return "W"
        elif actual_total > line:
            return "L"
        return "P"


def grade_ml(game, away_score, home_score):
    """Grade a moneyline pick. Returns 'W' or 'L'."""
    pick = game.get("ml_pick")
    if not pick:
        return None

    if pick == game["home_team"]:
        return "W" if home_score > away_score else "L"
    else:
        return "W" if away_score > home_score else "L"


# ── Results Helpers ──────────────────────────────────────────────


def _hit_from_result(r):
    """Convert grade letter to hit value: True/False/None (push)."""
    if r == "W":
        return True
    if r == "L":
        return False
    return None  # P or None


def _tally(picks_list):
    w = sum(1 for p in picks_list if p.get("hit") is True)
    l = sum(1 for p in picks_list if p.get("hit") is False)
    ps = sum(1 for p in picks_list if p.get("hit") is None)
    return w, l, ps


def _make_stat(w, l, ps=0):
    t = w + l
    pct_val = round(w / t * 100, 1) if t > 0 else 0
    record = f"{w}-{l}-{ps}" if ps else f"{w}-{l}"
    return {"wins": w, "losses": l, "pushes": ps, "record": record, "pct": pct_val}


def _sum_cat(days_list, cat):
    """Sum a category across all days and compute allTime stats with ROI."""
    w = sum(d.get(cat, {}).get("wins", 0) for d in days_list)
    l = sum(d.get(cat, {}).get("losses", 0) for d in days_list)
    p = sum(d.get(cat, {}).get("pushes", 0) for d in days_list)
    t = w + l
    pct_val = round(w / t * 100, 1) if t > 0 else 0
    profit = w * 90.91 - l * 100
    roi = round(profit / (t * 100) * 100, 1) if t > 0 else 0
    return {"wins": w, "losses": l, "pushes": p, "pct": pct_val, "roi": roi}


# ── Core Grading Pipeline ───────────────────────────────────────


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def grade_sport(sport_label, proj_filename, results_filename, scores, is_nba=False):
    """Grade a single sport's projections against scores.

    Args:
        sport_label: Display name (NBA, NHL, NCAAB)
        proj_filename: Projection JSON filename in repo root
        results_filename: Results JSON filename in repo root
        scores: Dict of {"AWAY@HOME": {away_score, home_score, completed}}
        is_nba: If True, use NBA-specific results merge (preserve props)
    """
    proj_path = os.path.join(REPO_ROOT, proj_filename)
    results_path = os.path.join(REPO_ROOT, results_filename)

    proj_data = load_json(proj_path)
    if not proj_data or not proj_data.get("games"):
        print(f"  [{sport_label}] No projection file or no games — skipping")
        return False

    games = proj_data["games"]
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    if not scores:
        print(f"  [{sport_label}] No scores available — skipping")
        return False

    changed = False
    graded_count = 0

    for g in games:
        key = f"{g['away_team']}@{g['home_team']}"
        sc = scores.get(key)
        if not sc:
            continue

        away_score = sc["away_score"]
        home_score = sc["home_score"]
        if away_score is None or home_score is None:
            continue

        if sc["completed"]:
            # Skip if already graded with same scores
            if (g.get("status") == "final"
                    and g.get("away_score") == away_score
                    and g.get("home_score") == home_score
                    and g.get("spread_result") is not None):
                continue

            g["away_score"] = away_score
            g["home_score"] = home_score
            g["status"] = "final"

            g["spread_result"] = grade_spread(g, away_score, home_score)
            g["total_result"] = grade_total(g, away_score, home_score)
            g["ml_result"] = grade_ml(g, away_score, home_score)

            print(f"  [{sport_label}] {key}: {away_score}-{home_score} | "
                  f"Spread:{g['spread_result']} Total:{g['total_result']} ML:{g['ml_result']}")
            graded_count += 1
            changed = True

        else:
            # Live game — update scores only
            if g.get("status") != "final":
                old_away = g.get("away_score")
                if old_away != away_score or g.get("home_score") != home_score:
                    g["away_score"] = away_score
                    g["home_score"] = home_score
                    g["status"] = "live"
                    changed = True

    if graded_count > 0:
        print(f"  [{sport_label}] Graded {graded_count} games")

    if changed:
        proj_data["updated"] = datetime.now().isoformat(timespec="seconds")
        save_json(proj_path, proj_data)

        if is_nba:
            update_nba_results(proj_data, results_path)
        else:
            update_results(sport_label, proj_data, results_path)

    live_count = sum(1 for g in games if g.get("status") == "live")
    final_count = sum(1 for g in games if g.get("status") == "final")
    sched_count = sum(1 for g in games if g.get("status") not in ("live", "final"))
    print(f"  [{sport_label}] Status: {sched_count} scheduled, {live_count} live, {final_count} final")

    return changed


def update_results(sport_label, proj_data, results_path):
    """Update results JSON for NHL/NCAAB (no props to preserve)."""
    games = proj_data.get("games", [])
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    picks = []
    for g in games:
        if g.get("status") != "final" or g.get("away_score") is None:
            continue

        matchup = f"{g['away_team']} @ {g['home_team']}"
        result_str = f"{g['away_score']}-{g['home_score']}"

        if g.get("spread_result") in ("W", "L", "P"):
            picks.append({
                "date": game_date, "type": "spread", "game": matchup,
                "pick": g.get("spread_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["spread_result"]),
                "confidence": g.get("spread_conf", 0),
            })
        if g.get("total_result") in ("W", "L", "P"):
            pick_label = f"{g.get('total_pick', '')} {g.get('total_line', '')}"
            picks.append({
                "date": game_date, "type": "total", "game": matchup,
                "pick": pick_label, "result": result_str,
                "hit": _hit_from_result(g["total_result"]),
                "confidence": g.get("total_conf", 0),
            })
        if g.get("ml_result") in ("W", "L"):
            picks.append({
                "date": game_date, "type": "ml", "game": matchup,
                "pick": g.get("ml_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["ml_result"]),
                "confidence": g.get("ml_conf", 0),
            })

    if not picks:
        return

    # Tag top 5 by confidence as best bets
    by_conf = sorted(picks, key=lambda p: p.get("confidence") or 0, reverse=True)
    for p in by_conf[:5]:
        p["best_bet"] = True

    # Tally per category
    spread_picks = [p for p in picks if p["type"] == "spread"]
    total_picks = [p for p in picks if p["type"] == "total"]
    ml_picks = [p for p in picks if p["type"] == "ml"]
    bb_picks = [p for p in picks if p.get("best_bet")]

    sw, sl, sp = _tally(spread_picks)
    tw, tl, tp = _tally(total_picks)
    mw, ml_l, mp = _tally(ml_picks)
    bw, bl, bp = _tally(bb_picks)

    # Load or create results
    results = load_json(results_path) or {"updated": "", "allTime": {}, "days": []}

    day_entry = {
        "date": game_date,
        "spreads": _make_stat(sw, sl, sp),
        "totals": _make_stat(tw, tl, tp),
        "moneylines": _make_stat(mw, ml_l, mp),
        "best_bets": _make_stat(bw, bl, bp),
        "picks": picks,
    }

    # Replace or append day
    days = results.get("days", [])
    replaced = False
    for i, d in enumerate(days):
        if d["date"] == game_date:
            days[i] = day_entry
            replaced = True
            break
    if not replaced:
        days.append(day_entry)
    days.sort(key=lambda d: d["date"], reverse=True)
    results["days"] = days

    # Recalculate allTime
    results["allTime"] = {
        "spreads": _sum_cat(days, "spreads"),
        "totals": _sum_cat(days, "totals"),
        "moneylines": _sum_cat(days, "moneylines"),
        "best_bets": _sum_cat(days, "best_bets"),
    }
    results["updated"] = datetime.now().isoformat(timespec="seconds")

    save_json(results_path, results)
    print(f"  [{sport_label}] Results: Spread {sw}-{sl}, Total {tw}-{tl}, ML {mw}-{ml_l}, Best Bets {bw}-{bl}")


def update_nba_results(proj_data, results_path):
    """Update NBA results.json, preserving existing props data."""
    games = proj_data.get("games", [])
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Build game picks (spread/total/ML only — no props)
    game_picks = []
    for g in games:
        if g.get("status") != "final" or g.get("away_score") is None:
            continue

        matchup = f"{g['away_team']} @ {g['home_team']}"
        result_str = f"{g['away_score']}-{g['home_score']}"

        if g.get("spread_result") in ("W", "L", "P"):
            game_picks.append({
                "date": game_date, "type": "spread", "game": matchup,
                "pick": g.get("spread_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["spread_result"]),
                "confidence": g.get("spread_conf", 0),
            })
        if g.get("total_result") in ("W", "L", "P"):
            pick_label = f"{g.get('total_pick', '')} {g.get('total_line', '')}"
            game_picks.append({
                "date": game_date, "type": "total", "game": matchup,
                "pick": pick_label, "result": result_str,
                "hit": _hit_from_result(g["total_result"]),
                "confidence": g.get("total_conf", 0),
            })
        if g.get("ml_result") in ("W", "L"):
            game_picks.append({
                "date": game_date, "type": "ml", "game": matchup,
                "pick": g.get("ml_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["ml_result"]),
                "confidence": g.get("ml_conf", 0),
            })

    if not game_picks:
        return

    # Tag top 5 game picks by confidence as best bets
    by_conf = sorted(game_picks, key=lambda p: p.get("confidence") or 0, reverse=True)
    for p in by_conf[:5]:
        p["best_bet"] = True

    # Load existing results
    results = load_json(results_path) or {"updated": "", "allTime": {}, "days": []}
    days = results.get("days", [])

    # Find existing day entry
    existing_day = None
    existing_idx = None
    for i, d in enumerate(days):
        if d["date"] == game_date:
            existing_day = d
            existing_idx = i
            break

    if existing_day:
        # Merge: keep existing prop picks, replace game picks
        existing_picks = existing_day.get("picks", [])
        prop_picks = [p for p in existing_picks if p.get("type") == "prop"]
        merged_picks = prop_picks + game_picks
        existing_day["picks"] = merged_picks

        # Recalculate game stats only (spreads, totals, moneylines, best_bets)
        spread_picks = [p for p in game_picks if p["type"] == "spread"]
        total_picks = [p for p in game_picks if p["type"] == "total"]
        ml_picks = [p for p in game_picks if p["type"] == "ml"]
        bb_picks = [p for p in game_picks if p.get("best_bet")]

        sw, sl, sp = _tally(spread_picks)
        tw, tl, tp = _tally(total_picks)
        mw, ml_l, mp = _tally(ml_picks)
        bw, bl, bp = _tally(bb_picks)

        existing_day["spreads"] = _make_stat(sw, sl, sp)
        existing_day["totals"] = _make_stat(tw, tl, tp)
        existing_day["moneylines"] = _make_stat(mw, ml_l, mp)
        existing_day["best_bets"] = _make_stat(bw, bl, bp)
        # props stats preserved (not touched)

        days[existing_idx] = existing_day
    else:
        # New day entry — game stats only (no props yet)
        spread_picks = [p for p in game_picks if p["type"] == "spread"]
        total_picks = [p for p in game_picks if p["type"] == "total"]
        ml_picks = [p for p in game_picks if p["type"] == "ml"]
        bb_picks = [p for p in game_picks if p.get("best_bet")]

        sw, sl, sp = _tally(spread_picks)
        tw, tl, tp = _tally(total_picks)
        mw, ml_l, mp = _tally(ml_picks)
        bw, bl, bp = _tally(bb_picks)

        day_entry = {
            "date": game_date,
            "spreads": _make_stat(sw, sl, sp),
            "totals": _make_stat(tw, tl, tp),
            "moneylines": _make_stat(mw, ml_l, mp),
            "best_bets": _make_stat(bw, bl, bp),
            "picks": game_picks,
        }
        days.append(day_entry)

    days.sort(key=lambda d: d["date"], reverse=True)
    results["days"] = days

    # Recalculate allTime — include props from all days
    all_time = {
        "spreads": _sum_cat(days, "spreads"),
        "totals": _sum_cat(days, "totals"),
        "moneylines": _sum_cat(days, "moneylines"),
        "best_bets": _sum_cat(days, "best_bets"),
    }
    # Preserve props allTime if it exists (calculated by daily_update.py)
    if "props" in results.get("allTime", {}):
        all_time["props"] = _sum_cat(days, "props")
    # Preserve best_prop_type/pct if they exist
    for key in ("best_prop_type", "best_prop_pct"):
        if key in results.get("allTime", {}):
            all_time[key] = results["allTime"][key]

    results["allTime"] = all_time
    results["updated"] = datetime.now().isoformat(timespec="seconds")

    save_json(results_path, results)

    sw, sl = all_time["spreads"]["wins"], all_time["spreads"]["losses"]
    tw, tl = all_time["totals"]["wins"], all_time["totals"]["losses"]
    mw, ml_l = all_time["moneylines"]["wins"], all_time["moneylines"]["losses"]
    print(f"  [NBA] Results updated (game picks merged, props preserved)")


# ── Entry Point ──────────────────────────────────────────────────


def main():
    print(f"\n{'=' * 60}")
    print(f"  Score Check & Auto-Grade — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")

    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        print("  WARNING: No ODDS_API_KEY set — NBA/NHL scores will be skipped")

    # Fetch scores (2 Odds API calls + free ESPN)
    print("Fetching scores...")
    nba_scores = fetch_nba_scores(api_key)
    nhl_scores = fetch_nhl_scores(api_key)

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    ncaab_scores = {}
    ncaab_scores.update(fetch_ncaab_scores(yesterday))
    ncaab_scores.update(fetch_ncaab_scores(today))

    # Grade each sport
    print("\nGrading...")
    any_changes = False
    any_changes |= grade_sport("NBA", "game_projections.json", "results.json",
                               nba_scores, is_nba=True)
    any_changes |= grade_sport("NHL", "nhl_game_projections.json", "nhl_results.json",
                               nhl_scores)
    any_changes |= grade_sport("NCAAB", "ncaab_projections.json", "ncaab_results.json",
                               ncaab_scores)

    if any_changes:
        print(f"\nDone — files updated.")
    else:
        print(f"\nDone — no changes.")

    return 0 if any_changes else 0


if __name__ == "__main__":
    sys.exit(main())
