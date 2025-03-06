import asyncio
import json
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pandas as pd
from fpl import FPL
import aiohttp
from dotenv import load_dotenv

# Configuration
TEAM_ID = 6378398
FIXTURE_LOOKAHEAD = 5  # Number of fixtures to consider
LOG_FILE = "fpl_assistant.log"

# Load environment variables from .env file
load_dotenv()

# Access the email password
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Use EMAIL_PASSWORD in your email configuration
EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",

    "smtp_port": 587,
    "sender_email": "user.invalid@gmail.com",
    "sender_password": EMAIL_PASSWORD,  # Use the environment variable
    "receiver_email": "user.invalid@gmail.com"
}

# Logging
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = f"{LOG_DIR}/fpl_assistant.log"
# Ensure directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Set up logging with UTF-8 encoding
logging.basicConfig(
    level=logging.DEBUG,  # Enable DEBUG level logging
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_cookies():
    """Load cookies from cookies.json."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(base_dir, "cookies.json")
    try:
        with open(cookies_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("❌ cookies.json file not found. Please ensure it exists.")
        raise
    except json.JSONDecodeError:
        logger.error("❌ cookies.json is not a valid JSON file.")
        raise

CURRENT_GAMEWEEK = None
async def get_current_gameweek(fpl):
    """Fetch the current active gameweek from the FPL API."""
    try:
        gameweeks = await fpl.get_gameweeks()
        for gw in gameweeks:
            if gw.is_current:
                logger.info(f"✅ Current Gameweek detected: {gw.id}")
                gw.id += 1
                logger.info(f"📅 Using Gameweek: {gw.id} for suggestions going forward.")
                return gw.id
        logger.warning("⚠️ No active gameweek found. Defaulting to 1.")
        return 1  # Fallback if no current gameweek is active
    except Exception as e:
        logger.error(f"❌ Error fetching current gameweek: {e}")
        raise

async def get_fixture_difficulties(fpl):
    try:
        fixtures = await fpl.get_fixtures()
        team_fixtures = {}
        for fixture in fixtures:
            if fixture.finished or fixture.event is None:
                continue
            gw = fixture.event
            for team_id, difficulty in [
                (fixture.team_h, fixture.team_h_difficulty),
                (fixture.team_a, fixture.team_a_difficulty)
            ]:
                if team_id not in team_fixtures:
                    team_fixtures[team_id] = {}
                team_fixtures[team_id][gw] = difficulty
        return team_fixtures
    except Exception as e:
        logger.error(f"❌ Error fetching fixture difficulties: {e}")
        raise

async def calculate_team_fdr(team_fixtures, team_id):
    """Calculate the total fixture difficulty rating (FDR) for a team over the next few gameweeks."""
    fixtures = team_fixtures.get(team_id, {})

    # Get the FDRs for the next FIXTURE_LOOKAHEAD gameweeks
    upcoming_fdrs = []
    for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD):
        fdr = fixtures.get(gw, 5)  # Default to 5 if no fixture data
        capped_fdr = max(1, min(float(fdr), 5))
        upcoming_fdrs.append(capped_fdr)

    return sum(upcoming_fdrs)

async def fetch_player_data(fpl, player, team_fixtures):
    """Fetch and format player data."""
    try:
        fdr = await calculate_team_fdr(team_fixtures, player.team)

        # Map element_type to position
        position_map = {
            1: "Goalkeeper",
            2: "Defender",
            3: "Midfielder",
            4: "Forward"
        }
        position = position_map.get(player.element_type, "Unknown")

        form = float(player.form) if player.form not in [None, ""] else 0.0
        now_cost = player.now_cost / 10 if player.now_cost else 0.0

        return {
            "full_name": f"{player.first_name} {player.second_name}",
            "team": player.team,
            "position": position,
            "form": form,
            "total_points": player.total_points,
            "now_cost": now_cost,
            "fixture_difficulty": fdr
        }
    except Exception as e:
        logger.error(f"❌ Error fetching data for player {player.first_name} {player.second_name}: {e}")
        return None

async def suggest_best_players(fpl, team_fixtures, top_n=10):
    """Suggest the best players to pick based on form, points, and FDR."""
    try:
        players = await fpl.get_players()
        player_data = []
        for player in players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:  # Only append valid player data
                player_data.append(data)

        df = pd.DataFrame(player_data)
        top_players = df.sort_values(
            by=["form", "total_points", "fixture_difficulty"],
            ascending=[False, False, True]
        ).head(top_n)

        return top_players
    except Exception as e:
        logger.error(f"❌ Error suggesting best players: {e}")
        raise

async def suggest_captain(fpl, team_fixtures, user_team):
    """Suggest captain and vice-captain based on form, points, and FDR."""
    try:
        my_players = [await fpl.get_player(p["element"]) for p in user_team]
        captain_data = []
        for player in my_players:
            fdr = await calculate_team_fdr(team_fixtures, player.team)
            captain_score = (float(player.form) * 0.4) + (player.total_points * 0.3) + ((6 - fdr) * 0.3)
            captain_data.append({
                "full_name": f"{player.first_name} {player.second_name}",
                "team": player.team,  # Ensure the "team" column is included
                "form": float(player.form),
                "total_points": player.total_points,
                "fixture_difficulty": fdr,
                "captain_score": captain_score
            })

        df = pd.DataFrame(captain_data)
        captain = df.sort_values(by="captain_score", ascending=False).head(1)
        vice_captain = df.sort_values(by="captain_score", ascending=False).iloc[1:2]

        return captain, vice_captain
    except Exception as e:
        logger.error(f"❌ Error suggesting captain: {e}")
        raise

async def suggest_transfers_out(fpl, team_fixtures, user_team):
    """Suggest players to transfer out based on form, status, and FDR."""
    try:
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
    except Exception as e:
        logger.error(f"❌ Error suggesting transfers out: {e}")
        raise

async def suggest_bench_boost(fpl, team_fixtures, user_team):
    try:
        bench_players = []

        for player in user_team:
            if player["position"] >= 12:
                player_data = await fpl.get_player(player["element"])
                bench_players.append(player_data)

        if not bench_players:
            logger.warning("⚠️ No bench players found for Bench Boost suggestion.")
            return None

        logger.debug("Bench Players:")
        for player in bench_players:
            logger.debug(f"- {player.first_name} {player.second_name} (Team: {player.team}, Form: {player.form})")

        best_gw = CURRENT_GAMEWEEK
        best_bench_score = 0

        for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD):
            total_bench_score = 0
            for player in bench_players:
                fdr = team_fixtures.get(player.team, {}).get(gw, default_fixture_value)
                capped_fdr = max(1, min(fdr, 5))
                bench_score = max(0, (float(player.form) * 0.6) + ((5 - capped_fdr) * 0.4))
                total_bench_score += bench_score
                logger.debug(f"Gameweek {gw} - {player.first_name} {player.second_name}: Form = {player.form}, FDR = {fdr}, Bench Score = {bench_score}")

            logger.debug(f"Gameweek {gw} - Total Bench Score: {total_bench_score}")

            if total_bench_score > best_bench_score:
                best_bench_score = total_bench_score
                best_gw = gw

        return f"Use Bench Boost in Gameweek {best_gw} (Total Bench Score: {best_bench_score:.2f})"
    except Exception as e:
        logger.error(f"❌ Error suggesting Bench Boost: {e}")
        raise

default_fixture_value = 5
async def suggest_triple_captain(fpl, team_fixtures, user_team):
    try:
        captain, _ = await suggest_captain(fpl, team_fixtures, user_team)
        captain_team_id = captain.iloc[0]["team"]
        logger.debug(f"Captain's team ID: {captain_team_id}")
        fixtures = team_fixtures.get(captain_team_id, {})

        if not fixtures:
            logger.warning(f"No fixture data found for team ID {captain_team_id}.")
            return "No fixture data found for the captain's team. Save Triple Captain for a future gameweek."

        best_gw = CURRENT_GAMEWEEK
        easiest_fdr = float("inf")
        valid_fixtures_found = False

        for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD):
            fdr = fixtures.get(gw, default_fixture_value)
            logger.debug(f"Gameweek {gw} - FDR: {fdr}")
            if fdr < easiest_fdr:
                easiest_fdr = fdr
                best_gw = gw
                valid_fixtures_found = True

        if not valid_fixtures_found:
            logger.warning("No valid fixture difficulties found for the captain. Save Triple Captain for a future gameweek.")
            return "No valid fixture difficulties found for the captain. Save Triple Captain for a future gameweek."

        return f"Use Triple Captain in Gameweek {best_gw} (Fixture Difficulty: {easiest_fdr})"
    except Exception as e:
        logger.error(f"❌ Error suggesting Triple Captain: {e}")
        raise

# Simple logic here, could be improved by comparing current team selection (injuries etc.)
async def suggest_wildcard():
    """Suggest when to play the Wildcard chip."""
    if CURRENT_GAMEWEEK <= 20:
        return "Play Wildcard in the first half of the season (before Gameweek 20)."
    else:
        return "Play Wildcard in the second half of the season (after Gameweek 20)."
    
async def analyze_current_team(fpl, team_fixtures, user_team):
    """Analyze the current team and bench selection, suggesting improvements for upcoming games."""
    try:
        my_players = [await fpl.get_player(p["element"]) for p in user_team]
        team_data = []

        for player in my_players:
            fdr = await calculate_team_fdr(team_fixtures, player.team)
            
            # Map element_type to position
            position_map = {
                1: "Goalkeeper",
                2: "Defender",
                3: "Midfielder",
                4: "Forward"
            }
            position = position_map.get(player.element_type, "Unknown")

            team_data.append({
                "full_name": f"{player.first_name} {player.second_name}",
                "position": position,  # Add position mapping
                "form": float(player.form),
                "total_points": player.total_points,
                "now_cost": player.now_cost / 10,
                "fixture_difficulty": fdr,
                "status": player.status
            })

        df = pd.DataFrame(team_data)

        # Identify underperforming players
        underperforming_players = df[
            (df["form"] < 2.0) |
            (df["status"] != "a") |
            (df["fixture_difficulty"] > (FIXTURE_LOOKAHEAD * 3))
        ]

        # Suggest replacements for underperforming players
        replacements = []
        for _, player in underperforming_players.iterrows():
            replacement = await suggest_replacement(fpl, team_fixtures, player)
            if replacement:
                replacements.append(replacement)

        return underperforming_players, replacements
    except Exception as e:
        logger.error(f"❌ Error analyzing current team: {e}")
        raise

async def suggest_replacement(fpl, team_fixtures, player):
    """Suggest a replacement for an underperforming player."""
    try:
        players = await fpl.get_players()
        player_data = []

        for p in players:
            # Map element_type to position
            position_map = {
                1: "Goalkeeper",
                2: "Defender",
                3: "Midfielder",
                4: "Forward"
            }
            position = position_map.get(p.element_type, "Unknown")

            if position == player["position"] and p.now_cost / 10 <= player["now_cost"] + 1.0:  # Allow slight budget increase
                data = await fetch_player_data(fpl, p, team_fixtures)
                if data:
                    player_data.append(data)

        df = pd.DataFrame(player_data)

        # Sort by form, points, and FDR
        replacement = df.sort_values(
            by=["form", "total_points", "fixture_difficulty"],
            ascending=[False, False, True]
        ).head(1)

        if not replacement.empty:
            return {
                "transfer_out": player["full_name"],
                "transfer_in": replacement.iloc[0]["full_name"],
                "cost": replacement.iloc[0]["now_cost"] - player["now_cost"]
            }
        return None
    except Exception as e:
        logger.error(f"❌ Error suggesting replacement: {e}")
        raise

async def suggest_free_hit(fpl):
    """Suggest when to play the Free Hit chip based on blank or double gameweeks."""
    try:
        fixtures = await fpl.get_fixtures()
        gameweek_fixtures = {}

        # Count fixtures per gameweek
        for fixture in fixtures:
            if fixture.event is None or fixture.finished:
                continue
            if fixture.event not in gameweek_fixtures:
                gameweek_fixtures[fixture.event] = 0
            gameweek_fixtures[fixture.event] += 1

        # Identify blank and double gameweeks
        blank_gameweeks = [gw for gw, count in gameweek_fixtures.items() if count < 5]
        double_gameweeks = [gw for gw, count in gameweek_fixtures.items() if count > 10]

        if blank_gameweeks:
            return f"Play Free Hit in a Blank Gameweek (BGW): {blank_gameweeks}"
        elif double_gameweeks:
            return f"Play Free Hit in a Double Gameweek (DGW): {double_gameweeks}"
        else:
            return "No clear Free Hit opportunity found. Save it for a future blank or double gameweek."
    except Exception as e:
        logger.error(f"❌ Error suggesting Free Hit: {e}")
        raise

async def export_dataframes(best_players, transfers_out):
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        best_players.to_csv(f'{OUTPUT_DIR}/best_players_{timestamp}.csv', index=False)
        transfers_out.to_csv(f'{OUTPUT_DIR}/transfers_out_{timestamp}.csv', index=False)

        with pd.ExcelWriter(f'{OUTPUT_DIR}/fpl_suggestions_{timestamp}.xlsx') as writer:
            best_players.to_excel(writer, sheet_name='Best Players', index=False)
            transfers_out.to_excel(writer, sheet_name='Transfers Out', index=False)

        logger.info("📁 Exported suggestions to CSV and Excel.")
    except Exception as e:
        logger.error(f"❌ Error exporting dataframes: {e}")
        raise

async def send_email(subject, body):
    """Send an email with the given subject and body (HTML formatted)."""
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_CONFIG["sender_email"]
        msg["To"] = EMAIL_CONFIG["receiver_email"]
        msg["Subject"] = subject

        # Attach the HTML body
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.send_message(msg)

        logger.info("📧 Email sent successfully.")
    except Exception as e:
        logger.error(f"❌ Error sending email: {e}")
        raise

async def suggest_free_hit_team(fpl, team_fixtures, budget=100.0):
    """Suggest the best Free Hit team within budget, following FPL rules."""
    try:
        players = await fpl.get_players()
        player_data = []

        # Gather data on all players
        for player in players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:
                player_data.append(data)

        df = pd.DataFrame(player_data)

        if df.empty:
            logger.warning("⚠️ No valid players found for Free Hit team.")
            return df

        # Ensure numeric types
        df["now_cost"] = pd.to_numeric(df["now_cost"], errors="coerce")
        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["total_points"] = pd.to_numeric(df["total_points"], errors="coerce")
        df["fixture_difficulty"] = pd.to_numeric(df["fixture_difficulty"], errors="coerce")
        df = df.dropna(subset=["now_cost", "form", "total_points", "fixture_difficulty"])

        # Sort players: prioritize high form, high points, and easier fixtures
        df = df.sort_values(by=["form", "total_points", "fixture_difficulty"], ascending=[False, False, True])

        # Build balanced squad
        squad = []
        positions = {
            "Goalkeeper": 2,
            "Defender": 5,
            "Midfielder": 5,
            "Forward": 3
        }
        team_count = {}

        for position, count_needed in positions.items():
            position_players = df[df["position"] == position]

            for _, player in position_players.iterrows():
                if count_needed == 0:
                    break
                if player["now_cost"] + sum(p["now_cost"] for p in squad) > budget:
                    continue
                if team_count.get(player["team"], 0) >= 3:
                    continue
                squad.append(player)
                team_count[player["team"]] = team_count.get(player["team"], 0) + 1
                count_needed -= 1

        squad_df = pd.DataFrame(squad)

        if squad_df.empty:
            logger.warning("⚠️ No valid Free Hit squad could be formed within budget.")
        else:
            logger.info(f"✅ Free Hit squad selected with total cost £{squad_df['now_cost'].sum()}m")

        return squad_df

    except Exception as e:
        logger.error(f"❌ Error suggesting Free Hit team: {e}")
        raise


async def suggest_dgw_team(fpl, team_fixtures, budget=100.0):
    """Suggest a balanced Double Gameweek team within budget, considering FPL rules."""
    try:
        players = await fpl.get_players()
        player_data = []

        # Identify teams with double fixtures
        dgw_teams = []
        for team_id, fixtures in team_fixtures.items():
            upcoming_gws = [gw for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD)]
            gw_count = sum(1 for gw in upcoming_gws if gw in fixtures)
            if gw_count >= 2:
                dgw_teams.append(team_id)

        if not dgw_teams:
            logger.warning("⚠️ No Double Gameweek teams found.")
            return pd.DataFrame()

        # Collect player data from DGW teams
        for player in players:
            if player.team in dgw_teams:
                data = await fetch_player_data(fpl, player, team_fixtures)
                if data:
                    player_data.append(data)

        df = pd.DataFrame(player_data)

        if df.empty:
            logger.warning("⚠️ No valid DGW players found.")
            return df

        # Ensure numeric types for safety
        df["now_cost"] = pd.to_numeric(df["now_cost"], errors="coerce")
        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["total_points"] = pd.to_numeric(df["total_points"], errors="coerce")
        df = df.dropna(subset=["now_cost", "form", "total_points"])

        # Sort by form and total points
        df = df.sort_values(by=["form", "total_points"], ascending=[False, False])

        # Build the squad
        squad = []
        positions = {
            "Goalkeeper": 2,
            "Defender": 5,
            "Midfielder": 5,
            "Forward": 3
        }
        team_count = {}

        for position, count_needed in positions.items():
            position_players = df[df["position"] == position]

            for _, player in position_players.iterrows():
                if count_needed == 0:
                    break
                if player["now_cost"] + sum(p["now_cost"] for p in squad) > budget:
                    continue
                if team_count.get(player["team"], 0) >= 3:
                    continue
                squad.append(player)
                team_count[player["team"]] = team_count.get(player["team"], 0) + 1
                count_needed -= 1

        squad_df = pd.DataFrame(squad)

        if squad_df.empty:
            logger.warning("⚠️ No valid DGW squad could be formed within budget.")
        else:
            logger.info(f"✅ DGW squad selected with total cost £{squad_df['now_cost'].sum()}m")

        return squad_df

    except Exception as e:
        logger.error(f"❌ Error suggesting DGW team: {e}")
        raise


async def suggest_transfers(fpl, team_fixtures, user_team, budget=100.0, free_transfers=1):
    """Suggest the best transfers for the upcoming gameweeks, considering budget and free transfers."""
    try:
        my_players = [await fpl.get_player(p["element"]) for p in user_team]
        my_team_cost = sum(player.now_cost / 10 for player in my_players)

        # Get all players
        players = await fpl.get_players()
        player_data = []

        for player in players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:
                player_data.append(data)

        df = pd.DataFrame(player_data)

        # Ensure correct data types
        df["now_cost"] = pd.to_numeric(df["now_cost"], errors="coerce")
        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["fixture_difficulty"] = pd.to_numeric(df["fixture_difficulty"], errors="coerce")

        # Drop rows with NaN values in critical columns
        df = df.dropna(subset=["now_cost", "form", "fixture_difficulty"])

        # Sort players by form, points, and FDR
        best_players = df.sort_values(by=["form", "total_points", "fixture_difficulty"], ascending=[False, False, True])

        # Suggest transfers
        transfers = []
        for player in my_players:
            # Find a better replacement within budget
            replacement = best_players[
                (best_players["now_cost"] <= (my_team_cost + budget)) &
                (best_players["form"] > float(player.form)) &
                (best_players["total_points"] > player.total_points) &  # Ensure replacement has more points
                (best_players["fixture_difficulty"] < await calculate_team_fdr(team_fixtures, player.team))
            ].head(1)

            if not replacement.empty:
                transfers.append({
                    "transfer_out": f"{player.first_name} {player.second_name}",
                    "transfer_in": replacement.iloc[0]["full_name"],
                    "cost": float(replacement.iloc[0]["now_cost"] - (player.now_cost / 10))  # Convert to float
                })

        return transfers[:free_transfers]  # Limit to the number of free transfers
    except Exception as e:
        logger.error(f"❌ Error suggesting transfers: {e}")
        raise

async def track_injuries(fpl, user_team):
    """Track injuries and suspensions in your team and suggest replacements."""
    try:
        injured_players = []
        for player in user_team:
            player_data = await fpl.get_player(player["element"])
            if player_data.status != "a":  # Player is not available
                injured_players.append({
                    "name": f"{player_data.first_name} {player_data.second_name}",
                    "status": player_data.status
                })

        logger.debug(f"Injured players: {injured_players}")
        return injured_players
    except Exception as e:
        logger.error(f"❌ Error tracking injuries: {e}")
        raise

async def predict_points(fpl, player, team_fixtures):
    """Predict points for a player based on form, fixture difficulty, and historical performance."""
    try:
        fdr = await calculate_team_fdr(team_fixtures, player.team)
        predicted_points = (float(player.form) * 2) + ((6 - fdr) * 1.5)  # Example formula
        return predicted_points
    except Exception as e:
        logger.error(f"❌ Error predicting points: {e}")
        raise

async def track_team_value(fpl, user_team):
    """Track your team's value and suggest ways to increase it through transfers."""
    try:
        team_value = 0.0
        for player in user_team:
            player_id = player["element"]
            player_data = await fpl.get_player(player_id)  # Fetch player data from FPL API
            team_value += player_data.now_cost / 10  # Add player's cost to team value

        return f"Your team's current value is {team_value:.1f} million."
    except Exception as e:
        logger.error(f"❌ Error tracking team value: {e}")
        raise

async def analyze_historical_performance(fpl, player_id):
    """Analyze historical performance data for a player."""
    try:
        player = await fpl.get_player(player_id)
        history = player.history
        return history
    except Exception as e:
        logger.error(f"❌ Error analyzing historical performance: {e}")
        raise

async def main():
    """Main function to run the FPL assistant."""
    try:
        cookies = load_cookies()

        async with aiohttp.ClientSession(cookies=cookies) as session:
            fpl = FPL(session)
            global CURRENT_GAMEWEEK
            CURRENT_GAMEWEEK = await get_current_gameweek(fpl)
            logger.info("✅ Logged in using full browser cookies!")

            user = await fpl.get_user(TEAM_ID)
            user_team = await user.get_team()
            logger.debug(f"User team structure: {user_team}")

            team_fixtures = await get_fixture_difficulties(fpl)

            logger.info("\n🔼 Best Players to Pick:")
            best_players = await suggest_best_players(fpl, team_fixtures)
            logger.info(best_players)

            logger.info("\n🔽 Suggested Transfers Out:")
            transfers_out = await suggest_transfers_out(fpl, team_fixtures, user_team)
            logger.info(transfers_out)

            logger.info("\n🎖 Captaincy Recommendations:")
            captain, vice_captain = await suggest_captain(fpl, team_fixtures, user_team)
            logger.info("Captain: %s", captain)
            logger.info("Vice-Captain: %s", vice_captain)

            logger.info("\n🌟 Bench Boost Suggestion:")
            bench_boost_suggestion = await suggest_bench_boost(fpl, team_fixtures, user_team)
            if bench_boost_suggestion:
                logger.info(bench_boost_suggestion)
            else:
                logger.info("No bench players found for Bench Boost suggestion.")

            logger.info("\n🌟 Triple Captain Suggestion:")
            triple_captain_suggestion = await suggest_triple_captain(fpl, team_fixtures, user_team)
            logger.info(triple_captain_suggestion)

            logger.info("\n🃏 Wildcard Suggestion:")
            wildcard_suggestion = await suggest_wildcard()
            logger.info(wildcard_suggestion)

            logger.info("\n🎯 Free Hit Suggestion:")
            free_hit_suggestion = await suggest_free_hit(fpl)
            logger.info(free_hit_suggestion)

            logger.info("\n🌟 Free Hit Team Suggestion:")
            free_hit_team = await suggest_free_hit_team(fpl, team_fixtures)
            logger.info(free_hit_team)

            logger.info("\n🌟 Double Gameweek Team Suggestion:")
            dgw_team = await suggest_dgw_team(fpl, team_fixtures)
            logger.info(dgw_team)

            logger.info("\n🌟 Transfer Suggestions:")
            transfer_suggestions = await suggest_transfers(fpl, team_fixtures, user_team)
            logger.info(transfer_suggestions)

            logger.info("\n🌟 Injury and Suspension Tracker:")
            injured_players = await track_injuries(fpl, user_team)
            logger.info(injured_players)

            logger.info("\n🌟 Team Value Tracker:")
            team_value = await track_team_value(fpl, user_team)
            logger.info(team_value)

            logger.info("\n🌟 Current Team Analysis:")
            underperforming_players, replacements = await analyze_current_team(fpl, team_fixtures, user_team)
            logger.info("Underperforming Players:\n%s", underperforming_players)
            logger.info("Suggested Replacements:\n%s", replacements)

            await export_dataframes(best_players, transfers_out)

            # Convert dataframes to HTML tables
            best_players_html = best_players.to_html(index=False)
            transfers_out_html = transfers_out.to_html(index=False)
            free_hit_team_html = free_hit_team.to_html(index=False)
            dgw_team_html = dgw_team.to_html(index=False)
            underperforming_players_html = underperforming_players.to_html(index=False)
            replacements_html = pd.DataFrame(replacements).to_html(index=False)

            # Create the email body with HTML formatting
            email_body = f"""
            <html>
            <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #f9f9f9;
                    padding: 20px;
                    color: #333333;
                }}
                h2 {{
                    background-color: #0044cc;
                    color: #ffffff;
                    padding: 10px;
                    border-radius: 5px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }}
                th {{
                    background-color: #007bff;
                    color: #ffffff;
                    padding: 10px;
                }}
                td {{
                    padding: 8px;
                    text-align: center;
                    border: 1px solid #dddddd;
                }}
                tr:nth-child(even) {{
                    background-color: #f2f2f2;
                }}
                tr:hover {{
                    background-color: #e6f7ff;
                }}
                p {{
                    padding: 10px;
                    background-color: #eef2f7;
                    border-left: 4px solid #0044cc;
                    border-radius: 3px;
                }}
            </style>
            </head>
            <body>
                <h2>🔼 Best Players to Pick</h2>
                {best_players_html}
                <h2>🔽 Suggested Transfers Out</h2>
                {transfers_out_html}
                <h2>🎖 Captaincy Recommendations</h2>
                <p><strong>Captain:</strong> {captain.iloc[0]['full_name']} (Team: {captain.iloc[0]['team']}, Form: {captain.iloc[0]['form']}, FDR: {captain.iloc[0]['fixture_difficulty']})</p>
                <p><strong>Vice-Captain:</strong> {vice_captain.iloc[0]['full_name']} (Team: {vice_captain.iloc[0]['team']}, Form: {vice_captain.iloc[0]['form']}, FDR: {vice_captain.iloc[0]['fixture_difficulty']})</p>
                <h2>🌟 Bench Boost Suggestion</h2>
                <p>{bench_boost_suggestion}</p>
                <h2>🌟 Triple Captain Suggestion</h2>
                <p>{triple_captain_suggestion}</p>
                <h2>🃏 Wildcard Suggestion</h2>
                <p>{wildcard_suggestion}</p>
                <h2>🎯 Free Hit Suggestion</h2>
                <p>{free_hit_suggestion}</p>
                <h2>🌟 Free Hit Team Suggestion</h2>
                {free_hit_team_html}
                <h2>🌟 Double Gameweek Team Suggestion</h2>
                {dgw_team_html}
                <h2>🌟 Transfer Suggestions</h2>
                {replacements_html}
                <h2>🌟 Injury and Suspension Tracker</h2>
                <p>{injured_players}</p>
                <h2>🌟 Team Value Tracker</h2>
                <p>{team_value}</p>
                <h2>🌟 Current Team Analysis</h2>
                <p>Underperforming Players:</p>
                {underperforming_players_html}
                <p>Suggested Replacements:</p>
                {replacements_html}
            </body>
            </html>
            """

            # Send email with suggestions
            await send_email("Your Weekly FPL Suggestions", email_body)

    except Exception as e:
        logger.error(f"❌ Fatal error in main function: {e}")

if __name__ == "__main__":
    asyncio.run(main())