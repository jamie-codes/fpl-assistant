
import asyncio
import json
import os
from datetime import datetime
import pandas as pd
from fpl import FPL
import aiohttp

TEAM_ID = 6378398
FIXTURE_LOOKAHEAD = 5  # Number of fixtures to consider


def load_cookies():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(base_dir, "cookies.json")
    with open(cookies_path, "r") as f:
        return json.load(f)


async def get_fixture_difficulties(fpl):
    fixtures = await fpl.get_fixtures()
    team_fixtures = {}
    for fixture in fixtures:
        if fixture.finished or fixture.event is None:
            continue
        for team_side in ['team_h', 'team_a']:
            team_id = fixture[team_side]
            difficulty = fixture[f"{team_side}_difficulty"]
            if team_id not in team_fixtures:
                team_fixtures[team_id] = []
            team_fixtures[team_id].append(difficulty)
    return team_fixtures


async def calculate_team_fdr(team_fixtures, team_id):
    fixtures = team_fixtures.get(team_id, [])
    return sum(fixtures[:FIXTURE_LOOKAHEAD])


async def suggest_best_players(fpl, team_fixtures, top_n=10):
    players = await fpl.get_players()
    player_data = []
    for player in players:
        fdr = await calculate_team_fdr(team_fixtures, player.team)
        player_data.append({
            "full_name": f"{player.first_name} {player.second_name}",
            "team": player.team,
            "form": float(player.form),
            "total_points": player.total_points,
            "now_cost": player.now_cost / 10,
            "fixture_difficulty": fdr
        })

    df = pd.DataFrame(player_data)
    top_players = df.sort_values(
        by=["form", "total_points", "fixture_difficulty"],
        ascending=[False, False, True]
    ).head(top_n)

    return top_players


async def suggest_transfers_out(fpl, team_fixtures, user_team):
    my_players = [await fpl.get_player(p["element"]) for p in user_team]
    player_data = []
    for player in my_players:
        fdr = await calculate_team_fdr(team_fixtures, player.team)
        player_data.append({
            "full_name": f"{player.first_name} {player.second_name}",
            "form": float(player.form),
            "status": player.status,
            "total_points": player.total_points,
            "fixture_difficulty": fdr
        })

    df = pd.DataFrame(player_data)
    transfers_out = df[
        (df["form"] < 2.0) |
        (df["status"] != "a") |
        (df["fixture_difficulty"] > (FIXTURE_LOOKAHEAD * 3))
    ]

    return transfers_out


async def export_dataframes(best_players, transfers_out):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    best_players.to_csv(f'best_players_{timestamp}.csv', index=False)
    transfers_out.to_csv(f'transfers_out_{timestamp}.csv', index=False)

    with pd.ExcelWriter(f'fpl_suggestions_{timestamp}.xlsx') as writer:
        best_players.to_excel(writer, sheet_name='Best Players', index=False)
        transfers_out.to_excel(writer, sheet_name='Transfers Out', index=False)

    print(f"📁 Exported suggestions to CSV and Excel.")


async def main():
    cookies = load_cookies()
    
    async with aiohttp.ClientSession(cookies=cookies) as session:
        fpl = FPL(session)
        print("✅ Logged in using full browser cookies!")

        user = await fpl.get_user(TEAM_ID)
        user_team = await user.get_team()

        team_fixtures = await get_fixture_difficulties(fpl)

        print("\n🔼 Best Players to Pick:")
        best_players = await suggest_best_players(fpl, team_fixtures)
        print(best_players)

        print("\n🔽 Suggested Transfers Out:")
        transfers_out = await suggest_transfers_out(fpl, team_fixtures, user_team)
        print(transfers_out)

        await export_dataframes(best_players, transfers_out)


if __name__ == "__main__":
    asyncio.run(main())
