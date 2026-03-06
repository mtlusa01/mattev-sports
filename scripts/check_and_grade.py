#!/usr/bin/env python3
"""check_and_grade.py — Fetch scores via ESPN (free) and grade all 3 sports.

Self-contained script (no cross-repo imports) designed to run in GitHub Actions
every 15 minutes during game windows. Uses ESPN scoreboards exclusively —
zero Odds API calls, saving the entire quota for odds fetching.

ESPN endpoints (free, unlimited, near real-time):
  NBA:   https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
  NHL:   https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard
  NCAAB: https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard

Usage:
    python scripts/check_and_grade.py
"""

import json
import os
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# ── Configuration ────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ESPN_ENDPOINTS = {
    "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "MLB": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
}

ESPN_NHL_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary"
ESPN_NBA_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

# ESPN sometimes uses non-standard abbreviations — map to our projection format
# Sport-specific because some abbreviations conflict (WSH = WAS in NBA, WSH in NHL)
ESPN_ABBR_FIX_NBA = {
    "GS": "GSW", "SA": "SAS", "NY": "NYK", "NO": "NOP",
    "UTAH": "UTA", "WSH": "WAS",
}
ESPN_ABBR_FIX_NHL = {
    "TB": "TBL", "SJ": "SJS", "LA": "LAK", "NJ": "NJD",
    "MON": "MTL", "CLB": "CBJ", "NASH": "NSH",
}
ESPN_ABBR_FIX_BY_SPORT = {
    "NBA": ESPN_ABBR_FIX_NBA,
    "NHL": ESPN_ABBR_FIX_NHL,
    "NCAAB": {},
    "MLB": {},
}
# Combined map for backwards compat with scoreboard grading (game-level)
ESPN_ABBR_FIX = {**ESPN_ABBR_FIX_NBA, **ESPN_ABBR_FIX_NHL}


# ── ESPN Score Fetching ──────────────────────────────────────────


def fetch_espn_scores(sport, date_str=None):
    """Fetch scores from ESPN scoreboard for any sport.

    Args:
        sport: "NBA", "NHL", or "NCAAB"
        date_str: Optional date in 'YYYY-MM-DD' format (defaults to today)

    Returns dict: {"AWAY@HOME": {away_score, home_score, completed}}
    """
    url = ESPN_ENDPOINTS[sport]
    params = {}
    if date_str:
        params["dates"] = date_str.replace("-", "")
    if sport == "NCAAB":
        params["limit"] = 300
        params["groups"] = 50

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

            # Normalize ESPN abbreviations using sport-specific map
            # (avoids cross-sport collisions like TB→TBL, WSH→WAS)
            abbr_fix = ESPN_ABBR_FIX_BY_SPORT.get(sport, ESPN_ABBR_FIX)
            home_abbr = abbr_fix.get(home_abbr, home_abbr)
            away_abbr = abbr_fix.get(away_abbr, away_abbr)

            home_score = int(home_comp.get("score", 0) or 0)
            away_score = int(away_comp.get("score", 0) or 0)

            completed = status_type == "STATUS_FINAL"
            in_progress = status_type == "STATUS_IN_PROGRESS"

            period = event.get("status", {}).get("period", 0)
            clock = event.get("status", {}).get("displayClock", "")

            key = f"{away_abbr}@{home_abbr}"
            scores[key] = {
                "away_score": away_score,
                "home_score": home_score,
                "completed": completed,
                "in_progress": in_progress,
                "period": period,
                "clock": clock,
            }

        label = f"{sport} {date_str}" if date_str else sport
        print(f"  [{label}] ESPN: {len(scores)} games")
        return scores

    except Exception as e:
        label = f"{sport} {date_str}" if date_str else sport
        print(f"  [{label}] ESPN fetch error: {e}")
        return {}


# ── Smart Polling ────────────────────────────────────────────────


def _parse_clock_seconds(clock_str):
    """Parse ESPN displayClock (e.g. '3:42') to total seconds."""
    try:
        parts = str(clock_str).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            return int(parts[0])
    except (ValueError, TypeError):
        pass
    return 9999  # unknown → assume not ending soon


def _games_ending_soon(score_map):
    """Check if any in-progress game across all sports is near ending.

    Thresholds:
      NBA:   period >= 4, clock < 3:00
      NHL:   period >= 3, clock < 5:00 (or OT period > 3)
      NCAAB: period >= 2, clock < 3:00
      MLB:   period (inning) >= 9

    Returns True if any game is close to finishing.
    """
    for sport, scores in score_map.items():
        for key, sc in scores.items():
            if not sc.get("in_progress"):
                continue
            period = sc.get("period", 0)
            clock_secs = _parse_clock_seconds(sc.get("clock", ""))

            if sport == "NBA" and period >= 4 and clock_secs < 180:
                return True
            elif sport == "NHL" and ((period >= 3 and clock_secs < 300) or period > 3):
                return True
            elif sport == "NCAAB" and period >= 2 and clock_secs < 180:
                return True
            elif sport == "MLB" and period >= 9:
                return True
    return False


# ── Smart Checking ───────────────────────────────────────────────


def has_ungraded_games(proj_path):
    """Check if a projection file has any ungraded (non-final) games.

    Returns (has_ungraded: bool, total_games: int, ungraded_count: int)
    """
    if not os.path.exists(proj_path):
        return False, 0, 0

    try:
        with open(proj_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games", [])
        if not games:
            return False, 0, 0

        ungraded = sum(1 for g in games if g.get("status") not in ("final", "closed"))
        return ungraded > 0, len(games), ungraded

    except Exception:
        return True, 0, 0  # err on the side of checking


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
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  Warning: invalid JSON in {path}: {e}")
        return None


def save_json(path, data):
    # Safety guard: never reduce game count in projection files
    if "games" in data and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            old_count = len(existing.get("games", []))
            new_count = len(data.get("games", []))
            if new_count < old_count:
                print(f"  WARNING: Refusing to save {os.path.basename(path)} — "
                      f"would reduce games from {old_count} to {new_count}")
                return False
        except Exception:
            pass  # can't read existing file, proceed with save
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


def grade_sport(sport_label, proj_filename, results_filename, scores, is_nba=False):
    """Grade a single sport's projections against scores.

    Args:
        sport_label: Display name (NBA, NHL, NCAAB)
        proj_filename: Projection JSON filename in repo root
        results_filename: Results JSON filename in repo root
        scores: Dict of {"AWAY@HOME": {away_score, home_score, completed}}
        is_nba: If True, use NBA-specific results merge (preserve props)

    Returns (changed: bool, summary: str)
    """
    proj_path = os.path.join(REPO_ROOT, proj_filename)
    results_path = os.path.join(REPO_ROOT, results_filename)

    proj_data = load_json(proj_path)
    if not proj_data or not proj_data.get("games"):
        return False, f"{sport_label}: no projection file"

    games = proj_data["games"]
    game_date = proj_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    if not scores:
        return False, f"{sport_label}: no ESPN scores available"

    # IMPORTANT: This loop only updates score/status/result fields.
    # It NEVER modifies prediction values (spread_pick, spread_conf,
    # total_pick, total_line, ml_pick, ml_conf, proj_* fields, etc.)
    # so locked projections stay intact through grading.
    changed = False
    graded_games = []
    live_updates = 0

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

            matchup = f"{g['away_team']} {away_score} - {g['home_team']} {home_score}"
            graded_games.append(matchup)
            changed = True

        else:
            # Non-final game — update scores only if actually in progress
            # ESPN returns score=0 for scheduled games; skip those to avoid
            # prematurely marking games as "live" (None != 0 was triggering updates)
            if g.get("status") != "final" and (sc.get("in_progress") or away_score > 0 or home_score > 0):
                old_away = g.get("away_score")
                if old_away != away_score or g.get("home_score") != home_score:
                    g["away_score"] = away_score
                    g["home_score"] = home_score
                    g["status"] = "live"
                    live_updates += 1
                    changed = True

    if changed:
        proj_data["updated"] = datetime.now().isoformat(timespec="seconds")
        save_json(proj_path, proj_data)

        if is_nba:
            update_nba_results(proj_data, results_path)
        else:
            update_results(sport_label, proj_data, results_path)

    # Build summary
    final_count = sum(1 for g in games if g.get("status") == "final")
    live_count = sum(1 for g in games if g.get("status") == "live")
    sched_count = sum(1 for g in games if g.get("status") not in ("live", "final"))

    parts = []
    if graded_games:
        parts.append(f"{len(graded_games)} graded ({', '.join(graded_games)})")
    if live_updates:
        parts.append(f"{live_updates} live score updates")
    if not parts:
        if final_count == len(games):
            parts.append("all games already graded")
        elif sched_count == len(games):
            parts.append("all games still scheduled")
        else:
            parts.append(f"{live_count} live, {sched_count} scheduled — no score changes")

    summary = f"{sport_label}: {'; '.join(parts)} [{final_count}F/{live_count}L/{sched_count}S]"
    print(f"  {summary}")

    return changed, summary


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

        proj_score = g.get("proj_score")

        if g.get("spread_result") in ("W", "L", "P"):
            pick_entry = {
                "date": game_date, "type": "spread", "game": matchup,
                "pick": g.get("spread_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["spread_result"]),
                "confidence": g.get("spread_conf", 0),
            }
            if proj_score:
                pick_entry["proj_score"] = proj_score
            picks.append(pick_entry)
        if g.get("total_result") in ("W", "L", "P"):
            pick_label = f"{g.get('total_pick', '')} {g.get('total_line', '')}"
            pick_entry = {
                "date": game_date, "type": "total", "game": matchup,
                "pick": pick_label, "result": result_str,
                "hit": _hit_from_result(g["total_result"]),
                "confidence": g.get("total_conf", 0),
            }
            if proj_score:
                pick_entry["proj_score"] = proj_score
            picks.append(pick_entry)
        if g.get("ml_result") in ("W", "L"):
            pick_entry = {
                "date": game_date, "type": "ml", "game": matchup,
                "pick": g.get("ml_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["ml_result"]),
                "confidence": g.get("ml_conf", 0),
            }
            if proj_score:
                pick_entry["proj_score"] = proj_score
            if g.get("home_win_prob") is not None:
                pick_entry["home_win_prob"] = g["home_win_prob"]
            if g.get("away_win_prob") is not None:
                pick_entry["away_win_prob"] = g["away_win_prob"]
            picks.append(pick_entry)

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

        proj_score = g.get("proj_score")

        if g.get("spread_result") in ("W", "L", "P"):
            pick_entry = {
                "date": game_date, "type": "spread", "game": matchup,
                "pick": g.get("spread_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["spread_result"]),
                "confidence": g.get("spread_conf", 0),
            }
            if proj_score:
                pick_entry["proj_score"] = proj_score
            game_picks.append(pick_entry)
        if g.get("total_result") in ("W", "L", "P"):
            pick_label = f"{g.get('total_pick', '')} {g.get('total_line', '')}"
            pick_entry = {
                "date": game_date, "type": "total", "game": matchup,
                "pick": pick_label, "result": result_str,
                "hit": _hit_from_result(g["total_result"]),
                "confidence": g.get("total_conf", 0),
            }
            if proj_score:
                pick_entry["proj_score"] = proj_score
            game_picks.append(pick_entry)
        if g.get("ml_result") in ("W", "L"):
            pick_entry = {
                "date": game_date, "type": "ml", "game": matchup,
                "pick": g.get("ml_pick", ""), "result": result_str,
                "hit": _hit_from_result(g["ml_result"]),
                "confidence": g.get("ml_conf", 0),
            }
            if proj_score:
                pick_entry["proj_score"] = proj_score
            if g.get("home_win_prob") is not None:
                pick_entry["home_win_prob"] = g["home_win_prob"]
            if g.get("away_win_prob") is not None:
                pick_entry["away_win_prob"] = g["away_win_prob"]
            game_picks.append(pick_entry)

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


def _fetch_espn_event_ids(sport, date_str):
    """Fetch ESPN event IDs mapped by team matchup for a given date.

    Returns dict: {"AWAY@HOME": espn_event_id, ...}
    """
    url = ESPN_ENDPOINTS[sport]
    params = {"dates": date_str.replace("-", "")}
    if sport == "NCAAB":
        params["limit"] = 300
        params["groups"] = 50
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = {}
        for event in data.get("events", []):
            eid = event.get("id")
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            home_comp = away_comp = None
            for comp in competitors:
                if comp.get("homeAway") == "home":
                    home_comp = comp
                else:
                    away_comp = comp
            if not home_comp or not away_comp:
                continue
            abbr_fix = ESPN_ABBR_FIX_BY_SPORT.get(sport, ESPN_ABBR_FIX)
            home_raw = home_comp.get("team", {}).get("abbreviation", "")
            away_raw = away_comp.get("team", {}).get("abbreviation", "")
            home_abbr = abbr_fix.get(home_raw, home_raw)
            away_abbr = abbr_fix.get(away_raw, away_raw)
            status = event.get("status", {}).get("type", {}).get("name", "")
            result[f"{away_abbr}@{home_abbr}"] = {
                "id": eid,
                "status": status,
                "date": date_str,
            }
        return result
    except Exception as e:
        print(f"  ESPN event ID fetch error ({sport} {date_str}): {e}")
        return {}


def _fetch_box_score(summary_url, event_id):
    """Fetch box score stats from ESPN summary API.

    Returns dict: {"Player Name": {"stat_key": value, ...}, ...} or None
    """
    try:
        resp = requests.get(f"{summary_url}?event={event_id}", timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()

        status = (data.get("header", {}).get("competitions", [{}])[0]
                  .get("status", {}).get("type", {}).get("name", ""))
        if status != "STATUS_FINAL":
            return None

        stats = {}
        for team_data in data.get("boxscore", {}).get("players", []):
            for stat_section in team_data.get("statistics", []):
                labels = stat_section.get("labels", [])
                for athlete_data in stat_section.get("athletes", []):
                    player = athlete_data.get("athlete", {})
                    name = player.get("displayName", "")
                    if not name:
                        continue
                    stat_values = athlete_data.get("stats", [])
                    player_stats = {}
                    for i, key in enumerate(labels):
                        if i < len(stat_values):
                            try:
                                val = stat_values[i]
                                if "/" in str(val):
                                    parts = str(val).split("/")
                                    player_stats[key] = float(parts[0])
                                else:
                                    player_stats[key] = float(val)
                            except (ValueError, IndexError):
                                player_stats[key] = val
                    if name not in stats:
                        stats[name] = {}
                    stats[name].update(player_stats)

        return stats if stats else None
    except Exception as e:
        print(f"    Box score {event_id} error: {e}")
        return None


def _match_player(player_name, box_score_stats):
    """Find a player in box score stats by name matching."""
    for name, s in box_score_stats.items():
        if name.lower() == player_name.lower():
            return s
        if (name.split()[-1].lower() == player_name.split()[-1].lower() and
                name.split()[0][0].lower() == player_name.split()[0][0].lower()):
            return s
    return None


def _grade_prop(direction, line, actual_value):
    """Grade OVER/UNDER prop. Returns (result, actual_float)."""
    actual_value = float(actual_value)
    if direction == "OVER":
        result = "WIN" if actual_value > line else ("PUSH" if actual_value == line else "LOSS")
    else:
        result = "WIN" if actual_value < line else ("PUSH" if actual_value == line else "LOSS")
    return result, actual_value


def grade_nhl_props():
    """Grade NHL player props against actual box score stats.

    Uses team matchup to find ESPN event IDs (NHL API game IDs differ from ESPN).
    """
    props_path = os.path.join(REPO_ROOT, "nhl_player_props.json")
    results_path = os.path.join(REPO_ROOT, "nhl_props_results.json")

    if not os.path.exists(props_path):
        print("  NHL Props: no nhl_player_props.json found")
        return False

    with open(props_path, "r", encoding="utf-8") as f:
        props_data = json.load(f)

    props = props_data.get("projections", [])
    if not props:
        print("  NHL Props: no projections to grade")
        return False

    ungraded = [p for p in props if not p.get("result")]
    if not ungraded:
        print("  NHL Props: all props already graded")
        return False

    print(f"  NHL Props: {len(ungraded)} ungraded props")

    # Build set of team matchups from ungraded props
    matchups_needed = set()
    for p in ungraded:
        team = p.get("team", "")
        opponent = p.get("opponent", "")
        if team and opponent:
            # Props may not specify home/away, so check both directions
            matchups_needed.add((team, opponent))

    if not matchups_needed:
        print("  NHL Props: no team matchups found in props")
        return False

    # Fetch ESPN event IDs for today and yesterday (parallel)
    props_date = props_data.get("date", datetime.now().strftime("%Y-%m-%d"))
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    espn_events = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futs = [executor.submit(_fetch_espn_event_ids, "NHL", d) for d in [yesterday, today]]
        for fut in as_completed(futs):
            espn_events.update(fut.result())

    # Map team abbreviations to ESPN event IDs
    # Props have team + opponent but not home/away, so try both directions
    team_to_event = {}
    for matchup_key, event_info in espn_events.items():
        away, home = matchup_key.split("@")
        team_to_event[(away, home)] = event_info
        team_to_event[(home, away)] = event_info

    # Fetch box scores for matching final games
    box_scores = {}  # keyed by (team, opponent)
    fetched_events = set()
    for team, opponent in matchups_needed:
        event_info = team_to_event.get((team, opponent))
        if not event_info:
            continue
        eid = event_info["id"]
        if event_info["status"] != "STATUS_FINAL":
            continue
        # Only grade against events from the same date as the props
        event_date = event_info.get("date", "")
        if event_date and event_date != props_date:
            continue
        if eid in fetched_events:
            # Already fetched — map this matchup pair too
            for mk, bs in box_scores.items():
                if bs.get("_eid") == eid:
                    box_scores[(team, opponent)] = bs
                    break
            continue
        fetched_events.add(eid)

        stats = _fetch_box_score(ESPN_NHL_SUMMARY, eid)
        if stats:
            stats["_eid"] = eid
            box_scores[(team, opponent)] = stats
            # Also store reverse direction
            box_scores[(opponent, team)] = stats
            print(f"    Game {eid} ({team} vs {opponent}): {len(stats) - 1} players")

    if not box_scores:
        print("  NHL Props: no finished games with box scores")
        return False

    graded = 0
    wins = 0
    losses = 0

    # ESPN NHL labels: G, A, SOG, S, BS, HT, TK, SV, SA, etc.
    # "points" in NHL = Goals + Assists (computed)
    NHL_STAT_MAP = {
        "shots": ["SOG", "S"],
        "goals": ["G"],
        "assists": ["A"],
        "saves": ["SV"],
        "blocked_shots": ["BS"],
        "hits": ["HT"],
    }

    def _get_nhl_stat(actual_stats, prop_type):
        """Get NHL stat value, handling 'points' as G + A."""
        pt = prop_type.lower()
        if pt == "points":
            g = None
            a = None
            for key in ["G"]:
                if key in actual_stats:
                    g = float(actual_stats[key])
                    break
            for key in ["A"]:
                if key in actual_stats:
                    a = float(actual_stats[key])
                    break
            if g is not None and a is not None:
                return g + a
            return None
        for key in NHL_STAT_MAP.get(pt, [prop_type]):
            if key in actual_stats:
                return float(actual_stats[key])
        return None

    for p in props:
        if p.get("result"):
            continue
        team = p.get("team", "")
        opponent = p.get("opponent", "")
        bs = box_scores.get((team, opponent))
        if not bs:
            continue
        player_name = p.get("player", "")
        prop_type = p.get("prop", "")
        line = p.get("line")
        direction = str(p.get("direction", "OVER")).upper()
        if line is None:
            continue

        actual_stats = _match_player(player_name, {k: v for k, v in bs.items() if k != "_eid"})
        if actual_stats is None:
            continue

        actual_value = _get_nhl_stat(actual_stats, prop_type)
        if actual_value is None:
            continue

        result, actual_value = _grade_prop(direction, line, actual_value)
        p["result"] = result
        p["actual"] = actual_value
        graded += 1
        if result == "WIN":
            wins += 1
        elif result == "LOSS":
            losses += 1

    if graded == 0:
        print("  NHL Props: no props could be graded")
        return False

    print(f"  NHL Props: graded {graded} props ({wins}W-{losses}L)")
    save_json(props_path, props_data)
    _update_nhl_props_results(props, props_data.get("date", datetime.now().strftime("%Y-%m-%d")), results_path)
    return True


def _update_nhl_props_results(props, game_date, results_path):
    """Update nhl_props_results.json with grading results."""
    results = load_json(results_path) or {
        "sport": "NHL", "type": "player_props",
        "days": [], "all_time": {"wins": 0, "losses": 0, "pushes": 0},
    }

    graded = [p for p in props if p.get("result")]
    if not graded:
        return

    wins = sum(1 for p in graded if p["result"] == "WIN")
    losses = sum(1 for p in graded if p["result"] == "LOSS")
    pushes = sum(1 for p in graded if p["result"] == "PUSH")

    by_type = {}
    for p in graded:
        pt = p.get("prop", "?")
        if pt not in by_type:
            by_type[pt] = {"wins": 0, "losses": 0, "pushes": 0}
        if p["result"] == "WIN": by_type[pt]["wins"] += 1
        elif p["result"] == "LOSS": by_type[pt]["losses"] += 1
        else: by_type[pt]["pushes"] += 1

    by_tier = {}
    for p in graded:
        tier = p.get("edge", "FAIR") or "FAIR"
        if tier not in by_tier:
            by_tier[tier] = {"wins": 0, "losses": 0, "pushes": 0}
        if p["result"] == "WIN": by_tier[tier]["wins"] += 1
        elif p["result"] == "LOSS": by_tier[tier]["losses"] += 1
        else: by_tier[tier]["pushes"] += 1

    day_record = {
        "date": game_date, "wins": wins, "losses": losses, "pushes": pushes,
        "total": len(graded),
        "pct": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        "by_type": by_type, "by_tier": by_tier,
        "picks": [{"player": p.get("player"), "team": p.get("team"),
                    "opponent": p.get("opponent"), "prop": p.get("prop"),
                    "direction": p.get("direction"), "line": p.get("line"),
                    "projection": p.get("projection"),
                    "actual": p.get("actual"), "result": p.get("result"),
                    "hit": True if p.get("result") == "WIN" else (False if p.get("result") == "LOSS" else None),
                    "confidence": p.get("confidence"), "ev": p.get("ev"),
                    "edge": p.get("edge")} for p in graded],
    }

    found = False
    for i, d in enumerate(results["days"]):
        if d.get("date") == game_date:
            results["days"][i] = day_record
            found = True
            break
    if not found:
        results["days"].append(day_record)

    all_w = sum(d.get("wins", 0) for d in results["days"])
    all_l = sum(d.get("losses", 0) for d in results["days"])
    all_p = sum(d.get("pushes", 0) for d in results["days"])
    results["all_time"]["wins"] = all_w
    results["all_time"]["losses"] = all_l
    results["all_time"]["pushes"] = all_p
    results["all_time"]["pct"] = round(all_w / (all_w + all_l) * 100, 1) if (all_w + all_l) > 0 else 0

    results["updated"] = datetime.now().isoformat(timespec="seconds")
    save_json(results_path, results)
    print(f"  Updated nhl_props_results.json")


def _fetch_nba_box_scores(matchups_needed, target_date):
    """Fetch ESPN box scores for NBA final games matching the given matchups.

    Args:
        matchups_needed: set of (team, opponent) tuples
        target_date: date string YYYY-MM-DD to match events against

    Returns:
        box_scores dict keyed by (team, opponent) tuples
    """
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    espn_events = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futs = [executor.submit(_fetch_espn_event_ids, "NBA", d) for d in [yesterday, today]]
        for fut in as_completed(futs):
            espn_events.update(fut.result())

    # Map team abbreviations to ESPN event IDs (both directions)
    team_to_event = {}
    for matchup_key, event_info in espn_events.items():
        away, home = matchup_key.split("@")
        team_to_event[(away, home)] = event_info
        team_to_event[(home, away)] = event_info

    box_scores = {}
    fetched_events = set()
    for team, opponent in matchups_needed:
        event_info = team_to_event.get((team, opponent))
        if not event_info:
            continue
        eid = event_info["id"]
        if event_info["status"] != "STATUS_FINAL":
            continue
        # Only filter by date if a target_date was provided
        if target_date:
            event_date = event_info.get("date", "")
            if event_date and event_date != target_date:
                continue
        if eid in fetched_events:
            for mk, bs in box_scores.items():
                if bs.get("_eid") == eid:
                    box_scores[(team, opponent)] = bs
                    break
            continue
        fetched_events.add(eid)

        stats = _fetch_box_score(ESPN_NBA_SUMMARY, eid)
        if stats:
            stats["_eid"] = eid
            box_scores[(team, opponent)] = stats
            box_scores[(opponent, team)] = stats
            print(f"    Game {eid} ({team} vs {opponent}): {len(stats) - 1} players")

    return box_scores


# ESPN NBA box score labels: MIN, PTS, FG, 3PT, FT, REB, AST, TO, STL, BLK, ...
_NBA_STAT_MAP = {
    "pts": ["PTS"],
    "reb": ["REB"],
    "ast": ["AST"],
    "stl": ["STL"],
    "blk": ["BLK"],
    "to": ["TO"],
    "3pm": ["3PT"],
}


def _get_nba_stat(actual_stats, prop_type):
    """Get NBA stat value, handling compound stats like PRA."""
    prop_lower = prop_type.lower()

    if prop_lower == "pra":
        pts = _get_nba_stat(actual_stats, "PTS")
        reb = _get_nba_stat(actual_stats, "REB")
        ast = _get_nba_stat(actual_stats, "AST")
        if pts is not None and reb is not None and ast is not None:
            return pts + reb + ast
        return None
    if prop_lower == "pr":
        pts = _get_nba_stat(actual_stats, "PTS")
        reb = _get_nba_stat(actual_stats, "REB")
        if pts is not None and reb is not None:
            return pts + reb
        return None
    if prop_lower == "pa":
        pts = _get_nba_stat(actual_stats, "PTS")
        ast = _get_nba_stat(actual_stats, "AST")
        if pts is not None and ast is not None:
            return pts + ast
        return None
    if prop_lower == "ra":
        reb = _get_nba_stat(actual_stats, "REB")
        ast = _get_nba_stat(actual_stats, "AST")
        if reb is not None and ast is not None:
            return reb + ast
        return None

    for key in _NBA_STAT_MAP.get(prop_lower, [prop_type]):
        if key in actual_stats:
            return actual_stats[key]
    return None


def _grade_props_list(props_list, box_scores, get_stat_fn):
    """Grade a list of props against box scores. Modifies props in-place.

    Returns (graded_count, wins, losses).
    """
    graded = 0
    wins = 0
    losses = 0
    for p in props_list:
        if p.get("result"):
            continue
        team = p.get("team", "")
        opponent = p.get("opponent", "")
        bs = box_scores.get((team, opponent))
        if not bs:
            continue
        player_name = p.get("player", "")
        prop_type = p.get("prop", "")
        line = p.get("line")
        direction = str(p.get("direction", "OVER")).upper()
        if line is None or direction in ("NAN", "NONE", ""):
            continue

        actual_stats = _match_player(player_name, {k: v for k, v in bs.items() if k != "_eid"})
        if actual_stats is None:
            continue

        actual_value = get_stat_fn(actual_stats, prop_type)
        if actual_value is None:
            continue

        result, actual_value = _grade_prop(direction, line, actual_value)
        p["result"] = result
        p["actual"] = actual_value
        graded += 1
        if result == "WIN":
            wins += 1
        elif result == "LOSS":
            losses += 1
    return graded, wins, losses


def grade_nba_props():
    """Grade NBA player props against actual box score stats via ESPN.

    Grades both all_props.json (comprehensive props) and projections.json
    (top picks with betting lines) using shared ESPN box score data.
    """
    any_changes = False

    # ── Load both prop files ──
    all_props_path = os.path.join(REPO_ROOT, "all_props.json")
    all_props_results_path = os.path.join(REPO_ROOT, "all_props_results.json")
    proj_props_path = os.path.join(REPO_ROOT, "projections.json")

    all_props_data = load_json(all_props_path)
    proj_props_data = load_json(proj_props_path)

    all_props = (all_props_data.get("props", []) if all_props_data else [])
    proj_props = (proj_props_data.get("projections", []) if proj_props_data else [])

    all_ungraded = [p for p in all_props if not p.get("result")]
    proj_ungraded = [p for p in proj_props if not p.get("result")]

    if not all_ungraded and not proj_ungraded:
        print("  NBA Props: all props already graded")
        return False

    print(f"  NBA Props: {len(all_ungraded)} ungraded in all_props, {len(proj_ungraded)} in projections")

    # ── Build matchups from BOTH files ──
    matchups_needed = set()
    for p in all_ungraded + proj_ungraded:
        team = p.get("team", "")
        opponent = p.get("opponent", "")
        if team and opponent:
            matchups_needed.add((team, opponent))

    if not matchups_needed:
        print("  NBA Props: no team matchups found")
        return False

    # ── Fetch box scores (shared across both files) ──
    # Use projections.json date (always today's props) as primary target.
    # all_props.json may be stale (e.g. _date from weeks ago), so we
    # fetch box scores for today regardless and let player matching filter.
    today = datetime.now().strftime("%Y-%m-%d")
    proj_date = proj_props_data.get("date", today) if proj_props_data else today
    all_props_date = all_props_data.get("_date", all_props_data.get("date", "")) if all_props_data else ""

    # Determine which dates we need box scores for
    dates_needed = {today, proj_date}
    if all_props_date and all_props_date != today:
        dates_needed.add(all_props_date)
    print(f"  NBA Props: target dates = {sorted(dates_needed)}")

    # Fetch box scores with no date filter (None) — let matchup matching handle it.
    # This avoids the bug where a stale _date caused ALL events to be skipped.
    box_scores = _fetch_nba_box_scores(matchups_needed, None)
    if not box_scores:
        print("  NBA Props: no finished games with box scores")
        return False

    # ── Grade all_props.json ──
    if all_ungraded:
        g, w, l = _grade_props_list(all_props, box_scores, _get_nba_stat)
        if g > 0:
            print(f"  NBA all_props: graded {g} props ({w}W-{l}L)")
            all_props_data["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_json(all_props_path, all_props_data)
            _update_nba_props_results(
                all_props,
                all_props_date or today,
                all_props_results_path,
            )
            any_changes = True
        else:
            print("  NBA all_props: no props could be graded (likely roster-only without lines)")

    # ── Grade projections.json ──
    proj_graded = 0
    if proj_ungraded:
        proj_graded, w, l = _grade_props_list(proj_props, box_scores, _get_nba_stat)
        if proj_graded > 0:
            print(f"  NBA projections: graded {proj_graded} props ({w}W-{l}L)")
            proj_props_data["updated"] = datetime.now().isoformat(timespec="seconds")
            save_json(proj_props_path, proj_props_data)
            any_changes = True
        else:
            print("  NBA projections: no props could be graded")

    # ── Write projections.json results to all_props_results.json too ──
    # This gives the frontend a second data path via the merge function,
    # so results show even if the CDN serves a cached projections.json.
    proj_with_results = [p for p in proj_props if p.get("result")]
    if proj_with_results:
        _merge_proj_results_into_all_props_results(
            proj_with_results, proj_date, all_props_results_path
        )

    return any_changes


def _merge_proj_results_into_all_props_results(proj_graded, game_date, results_path):
    """Merge projections.json graded props into all_props_results.json.

    Adds projections.json results alongside all_props.json results so
    the frontend merge function can find them.
    """
    results = load_json(results_path) or {"days": [], "cumulative": {}}
    days = results.get("days", [])

    # Find or create day entry
    day = None
    day_idx = None
    for i, d in enumerate(days):
        if d.get("date") == game_date:
            day = d
            day_idx = i
            break

    if not day:
        day = {
            "date": game_date,
            "graded_at": datetime.now().isoformat(timespec="seconds"),
            "total_props_graded": 0,
            "overall": {"wins": 0, "losses": 0, "pushes": 0, "total": 0,
                        "record": "0-0-0", "win_pct": 0},
            "by_stat_type": {},
            "picks": [],
        }
        days.append(day)
        day_idx = len(days) - 1

    # Build set of existing pick keys to avoid duplicates
    existing_keys = set()
    for pick in day.get("picks", []):
        key = f"{pick.get('player')}|{pick.get('prop')}|{pick.get('direction')}|{pick.get('line')}"
        existing_keys.add(key)

    # Add projections results that aren't already present
    added = 0
    for p in proj_graded:
        key = f"{p.get('player')}|{p.get('prop')}|{p.get('direction')}|{p.get('line')}"
        if key in existing_keys:
            continue
        day["picks"].append({
            "player": p.get("player"),
            "prop": p.get("prop"),
            "team": p.get("team"),
            "opponent": p.get("opponent", ""),
            "direction": p.get("direction"),
            "line": p.get("line"),
            "projection": p.get("projection"),
            "actual": p.get("actual"),
            "result": p.get("result"),
            "confidence": p.get("confidence"),
            "ev": p.get("ev"),
            "edge": p.get("edge"),
        })
        added += 1

    if added == 0:
        return

    # Recalculate day stats from all picks
    all_picks = day["picks"]
    wins = sum(1 for p in all_picks if p.get("result") == "WIN")
    losses = sum(1 for p in all_picks if p.get("result") == "LOSS")
    pushes = sum(1 for p in all_picks if p.get("result") == "PUSH")
    day["total_props_graded"] = len(all_picks)
    day["overall"] = {
        "wins": wins, "losses": losses, "pushes": pushes,
        "total": len(all_picks),
        "record": f"{wins}-{losses}-{pushes}",
        "win_pct": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
    }
    day["graded_at"] = datetime.now().isoformat(timespec="seconds")

    # Recalculate by_stat_type
    by_type = {}
    for p in all_picks:
        pt = p.get("prop", "?")
        if pt not in by_type:
            by_type[pt] = {"wins": 0, "losses": 0, "pushes": 0}
        if p.get("result") == "WIN":
            by_type[pt]["wins"] += 1
        elif p.get("result") == "LOSS":
            by_type[pt]["losses"] += 1
        else:
            by_type[pt]["pushes"] += 1
    day["by_stat_type"] = by_type

    days[day_idx] = day

    # Recalculate cumulative
    all_w = sum(d.get("overall", {}).get("wins", 0) for d in days)
    all_l = sum(d.get("overall", {}).get("losses", 0) for d in days)
    all_p = sum(d.get("overall", {}).get("pushes", 0) for d in days)
    results["cumulative"] = {
        "wins": all_w, "losses": all_l, "pushes": all_p,
        "total": all_w + all_l + all_p,
        "win_pct": round(all_w / (all_w + all_l) * 100, 1) if (all_w + all_l) > 0 else 0,
    }
    results["days"] = days
    save_json(results_path, results)
    print(f"  Merged {added} projections results into all_props_results.json")


def _update_nba_props_results(props, game_date, results_path):
    """Update all_props_results.json with NBA prop grading results."""
    results = load_json(results_path) or {"days": [], "cumulative": {}}

    graded = [p for p in props if p.get("result")]
    if not graded:
        return

    wins = sum(1 for p in graded if p["result"] == "WIN")
    losses = sum(1 for p in graded if p["result"] == "LOSS")
    pushes = sum(1 for p in graded if p["result"] == "PUSH")

    by_type = {}
    for p in graded:
        pt = p.get("prop", "?")
        if pt not in by_type:
            by_type[pt] = {"wins": 0, "losses": 0, "pushes": 0}
        if p["result"] == "WIN":
            by_type[pt]["wins"] += 1
        elif p["result"] == "LOSS":
            by_type[pt]["losses"] += 1
        else:
            by_type[pt]["pushes"] += 1

    day_record = {
        "date": game_date,
        "graded_at": datetime.now().isoformat(timespec="seconds"),
        "total_props_graded": len(graded),
        "overall": {
            "wins": wins, "losses": losses, "pushes": pushes,
            "total": len(graded),
            "record": f"{wins}-{losses}-{pushes}",
            "win_pct": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        },
        "by_stat_type": by_type,
        "picks": [{"player": p.get("player"), "prop": p.get("prop"),
                    "team": p.get("team"), "direction": p.get("direction"),
                    "line": p.get("line"), "projection": p.get("projection"),
                    "actual": p.get("actual"), "result": p.get("result"),
                    "confidence": p.get("confidence"), "ev": p.get("ev"),
                    "edge": p.get("edge")} for p in graded],
    }

    found = False
    for i, d in enumerate(results["days"]):
        if d.get("date") == game_date:
            results["days"][i] = day_record
            found = True
            break
    if not found:
        results["days"].append(day_record)

    # Update cumulative
    all_w = sum(d.get("overall", {}).get("wins", 0) for d in results["days"])
    all_l = sum(d.get("overall", {}).get("losses", 0) for d in results["days"])
    all_p = sum(d.get("overall", {}).get("pushes", 0) for d in results["days"])
    results["cumulative"] = {
        "wins": all_w, "losses": all_l, "pushes": all_p,
        "total": all_w + all_l + all_p,
        "win_pct": round(all_w / (all_w + all_l) * 100, 1) if (all_w + all_l) > 0 else 0,
    }

    save_json(results_path, results)
    print(f"  Updated all_props_results.json")


# ── Catch-Up Grading (late games from previous day) ─────────────


def catchup_grade_previous_day():
    """Add score-only entries for yesterday's games that are missing from
    results.json. This catches late West Coast games that finished after
    the daily pipeline already replaced projections with the next day's data.

    Since the model's predictions are lost (projections overwritten), we
    add entries with just the scores. The frontend uses selfGradeFromScores()
    to grade tracked bets from the score using the bet's own pick details.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    for cfg in SPORT_CONFIG:
        results_path = os.path.join(REPO_ROOT, cfg["results_file"])

        # Check which games from yesterday are already in results
        results = load_json(results_path) or {"updated": "", "allTime": {}, "days": []}
        existing_games = set()
        for d in results.get("days", []):
            if d.get("date") == yesterday:
                for p in d.get("picks", []):
                    g = p.get("game", "")
                    if g:
                        existing_games.add(g)
                break

        # Fetch yesterday's scores from ESPN
        scores = fetch_espn_scores(cfg["label"], yesterday)
        if not scores:
            continue

        # Find completed games missing from results
        added = 0
        for key, sc in scores.items():
            if not sc.get("completed"):
                continue
            away, home = key.split("@")
            matchup = f"{away} @ {home}"
            if matchup in existing_games:
                continue

            away_score = sc.get("away_score")
            home_score = sc.get("home_score")
            if away_score is None or home_score is None:
                continue

            # Add a score-only entry (no model prediction, so hit is null)
            result_str = f"{away_score}-{home_score}"
            score_pick = {
                "date": yesterday, "type": "score", "game": matchup,
                "pick": "", "result": result_str, "hit": None,
            }

            # Find or create day entry
            day = None
            for d in results.get("days", []):
                if d.get("date") == yesterday:
                    day = d
                    break
            if not day:
                day = {"date": yesterday, "picks": []}
                results.setdefault("days", []).append(day)

            day.setdefault("picks", []).append(score_pick)
            added += 1
            print(f"    Catch-up: {matchup} {result_str} (score-only)")

        if added > 0:
            results["days"].sort(key=lambda d: d.get("date", ""), reverse=True)
            results["updated"] = datetime.now().isoformat(timespec="seconds")
            save_json(results_path, results)
            print(f"  {cfg['label']}: Added {added} score-only result(s) from {yesterday}")


SPORT_CONFIG = [
    {
        "label": "NBA",
        "proj_file": "game_projections.json",
        "results_file": "results.json",
        "is_nba": True,
    },
    {
        "label": "NHL",
        "proj_file": "nhl_game_projections.json",
        "results_file": "nhl_results.json",
        "is_nba": False,
    },
    {
        "label": "NCAAB",
        "proj_file": "ncaab_projections.json",
        "results_file": "ncaab_results.json",
        "is_nba": False,
    },
    {
        "label": "MLB",
        "proj_file": "mlb_game_projections.json",
        "results_file": "mlb_results.json",
        "is_nba": False,
    },
]


def _fetch_scores_for_sport(cfg, today, yesterday):
    """Fetch ESPN scores for a single sport (designed for parallel execution)."""
    sport = cfg["label"]
    scores = {}
    if sport == "NCAAB":
        scores.update(fetch_espn_scores("NCAAB", yesterday))
        scores.update(fetch_espn_scores("NCAAB", today))
    else:
        scores.update(fetch_espn_scores(sport, today))
        scores.update(fetch_espn_scores(sport, yesterday))
    return sport, scores


def main():
    t_start = time.time()
    print(f"\n{'=' * 60}")
    print(f"  Score Check & Auto-Grade — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Source: ESPN (free, 0 Odds API calls)")
    print(f"{'=' * 60}\n")

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # ── Phase 1: Check which sports need grading ──
    t_phase1 = time.time()
    print("Checking for ungraded games...")
    sports_to_check = []
    for cfg in SPORT_CONFIG:
        proj_path = os.path.join(REPO_ROOT, cfg["proj_file"])
        has_ungraded, total, ungraded = has_ungraded_games(proj_path)
        if has_ungraded:
            sports_to_check.append(cfg)
            print(f"  {cfg['label']}: {ungraded}/{total} ungraded — will check")
        else:
            if total == 0:
                print(f"  {cfg['label']}: no games today — skipping")
            else:
                print(f"  {cfg['label']}: all {total} games graded — skipping")
    t_phase1_end = time.time()

    if not sports_to_check:
        elapsed = time.time() - t_start
        print(f"\n{'=' * 60}")
        print(f"  SUMMARY: All games graded. Nothing to do. [{elapsed:.1f}s]")
        print(f"  Signaling loop to stop (exit 2)")
        print(f"{'=' * 60}")
        return 2  # all graded — tells workflow loop to stop early

    # ── Phase 2: Fetch scores from ESPN (parallel for all sports) ──
    t_phase2 = time.time()
    print(f"\nFetching ESPN scores for {len(sports_to_check)} sport(s) (parallel)...")
    score_map = {}
    with ThreadPoolExecutor(max_workers=len(sports_to_check)) as executor:
        futures = {
            executor.submit(_fetch_scores_for_sport, cfg, today, yesterday): cfg
            for cfg in sports_to_check
        }
        for future in as_completed(futures):
            sport, scores = future.result()
            score_map[sport] = scores
    t_phase2_end = time.time()

    # ── Quick check: any newly final games? ──
    has_new_finals = False
    for cfg in sports_to_check:
        sport = cfg["label"]
        scores = score_map.get(sport, {})
        proj_path = os.path.join(REPO_ROOT, cfg["proj_file"])
        proj_data = load_json(proj_path)
        if not proj_data:
            continue
        for g in proj_data.get("games", []):
            key = f"{g['away_team']}@{g['home_team']}"
            sc = scores.get(key)
            if not sc:
                continue
            # New final: ESPN says completed but we haven't graded yet
            if sc["completed"] and g.get("status") != "final":
                has_new_finals = True
                break
            # Live score change
            if sc.get("in_progress") and g.get("status") != "final":
                old_a = g.get("away_score")
                old_h = g.get("home_score")
                if old_a != sc["away_score"] or old_h != sc["home_score"]:
                    has_new_finals = True  # treat live updates as worth processing
                    break
        if has_new_finals:
            break

    if not has_new_finals:
        elapsed = time.time() - t_start
        api_time = t_phase2_end - t_phase2
        print(f"\n  No new finals or score changes detected.")
        if _games_ending_soon(score_map):
            print(f"\n{'=' * 60}")
            print(f"  SUMMARY: No changes but games ending soon — fast poll (exit 3) [{elapsed:.1f}s total, API: {api_time:.1f}s]")
            print(f"{'=' * 60}")
            return 3
        print(f"\n{'=' * 60}")
        print(f"  SUMMARY: No changes [{elapsed:.1f}s total, API: {api_time:.1f}s]")
        print(f"{'=' * 60}")
        return 0

    # ── Phase 3: Grade (isolated per sport) ──
    t_phase3 = time.time()
    print("\nGrading...")
    any_changes = False
    summaries = []
    for cfg in sports_to_check:
        sport = cfg["label"]
        try:
            changed, summary = grade_sport(
                sport, cfg["proj_file"], cfg["results_file"],
                score_map.get(sport, {}), is_nba=cfg["is_nba"]
            )
            any_changes |= changed
            summaries.append(summary)
        except Exception as e:
            print(f"  ERROR grading {sport} (non-fatal): {e}")
            summaries.append(f"{sport}: ERROR — {e}")
    t_phase3_end = time.time()

    # ── Phase 3b: Catch-up grade late games from previous day ──
    try:
        catchup_grade_previous_day()
    except Exception as e:
        print(f"  Catch-up grading error (non-fatal): {e}")

    # ── Phase 4: Grade player props (isolated per sport) ──
    t_phase4 = time.time()
    print("\nGrading player props...")
    try:
        nhl_props_changed = grade_nhl_props()
        any_changes |= nhl_props_changed
    except Exception as e:
        print(f"  ERROR grading NHL props (non-fatal): {e}")

    try:
        nba_props_changed = grade_nba_props()
        any_changes |= nba_props_changed
    except Exception as e:
        print(f"  ERROR grading NBA props (non-fatal): {e}")
    t_phase4_end = time.time()

    # Add skipped sports to summary
    checked_labels = {cfg["label"] for cfg in sports_to_check}
    for cfg in SPORT_CONFIG:
        if cfg["label"] not in checked_labels:
            summaries.append(f"{cfg['label']}: skipped (all graded)")

    # ── Summary with timing ──
    t_end = time.time()
    total_time = t_end - t_start
    check_time = t_phase1_end - t_phase1
    api_time = t_phase2_end - t_phase2
    grade_time = t_phase3_end - t_phase3
    props_time = t_phase4_end - t_phase4

    # ── Check if all games are now graded (for loop exit signal) ──
    all_graded = True
    for cfg in SPORT_CONFIG:
        proj_path = os.path.join(REPO_ROOT, cfg["proj_file"])
        has_ungraded, total, ungraded = has_ungraded_games(proj_path)
        if has_ungraded:
            all_graded = False
            break

    print(f"\n{'=' * 60}")
    print(f"  SUMMARY {'(files updated)' if any_changes else '(no changes)'}")
    for s in summaries:
        print(f"    {s}")
    print(f"  Timing: {total_time:.1f}s total (check: {check_time:.1f}s, API: {api_time:.1f}s, grade: {grade_time:.1f}s, props: {props_time:.1f}s)")
    if all_graded:
        print(f"  All games graded — signaling loop to stop (exit 2)")
    print(f"{'=' * 60}")

    # Exit code 2 = all games graded (tells workflow loop to stop early)
    # Exit code 3 = games ending soon (tells workflow loop to fast poll 30s)
    if all_graded:
        return 2
    if _games_ending_soon(score_map):
        print(f"  Games ending soon — fast poll (exit 3)")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
