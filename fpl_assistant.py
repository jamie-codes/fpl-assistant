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

# Load environment variables from .env file
load_dotenv()

# Access the email password
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Email configuration
EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "user.invalid@gmail.com",
    "sender_password": EMAIL_PASSWORD,
    "receiver_email": "user.invalid@gmail.com"
}

# Logging
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
# Generate a unique log file name with a timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # Format: YYYYMMDD_HHMMSS
LOG_FILE = f"{LOG_DIR}/fpl_assistant_{timestamp}.log"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
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
        return 1
    except Exception as e:
        logger.error(f"❌ Error fetching current gameweek: {e}")
        raise

async def get_fixture_difficulties(fpl):
    """Fetch fixture difficulties for all teams."""
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
    if not team_id or team_id not in team_fixtures:
        logger.warning(f"⚠️ Invalid team ID or no fixture data found for team ID: {team_id}")
        return 5 * FIXTURE_LOOKAHEAD  # Default to maximum difficulty if no data is found

    fixtures = team_fixtures.get(team_id, {})
    upcoming_fdrs = []
    for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD):
        fdr = fixtures.get(gw, 5)  # Default to 5 if no fixture data
        capped_fdr = max(1, min(float(fdr), 5))
        upcoming_fdrs.append(capped_fdr)
    return sum(upcoming_fdrs)

async def fetch_player_data(fpl, player, team_fixtures):
    try:
        # Check if player object is valid and has required attributes
        if not player or not hasattr(player, 'team') or not hasattr(player, 'element_type'):
            logger.warning(f"⚠️ Invalid player object or missing attributes for player: {player}")
            return None

        if not player.team or not player.element_type:
            logger.warning(f"⚠️ Missing team or position data for player {player.first_name} {player.second_name}")
            return None

        fdr = await calculate_team_fdr(team_fixtures, player.team)
        position_map = {
            1: "Goalkeeper",
            2: "Defender",
            3: "Midfielder",
            4: "Forward"
        }
        position = position_map.get(player.element_type, "Unknown")

        form = float(player.form) if player.form not in [None, ""] else 0.0
        now_cost = player.now_cost / 10 if player.now_cost else 0.0
        total_points = player.total_points if player.total_points else 0.0

        # Calculate Value for Money (VFM)
        vfm = total_points / now_cost if now_cost > 0 else 0.0

        # Fetch team logo and player photo URLs (handle missing fields)
        team_logo_url = f"https://resources.premierleague.com/premierleague/badges/t{player.team}.png" if player.team else "https://via.placeholder.com/30"
        player_photo_url = f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{player.code}.png" if hasattr(player, 'code') and player.code else "https://via.placeholder.com/50"

        return {
            "full_name": f"{player.first_name} {player.second_name}",
            "team": player.team,
            "team_logo": team_logo_url,  # Add team logo URL
            "player_photo": player_photo_url,  # Add player photo URL
            "position": position,
            "form": form,
            "total_points": total_points,
            "now_cost": now_cost,
            "fixture_difficulty": fdr,
            "vfm": vfm
        }
    except Exception as e:
        logger.error(f"❌ Error fetching data for player {player.first_name} {player.second_name}: {e}")
        return None
    
def generate_player_row(player):
    player_photo = player.get('player_photo') or 'https://via.placeholder.com/40x50?text=Player'
    team_logo = player.get('team_logo') or 'https://via.placeholder.com/30x30?text=Logo'

    return f"""
    <tr>
        <td>
            <img src="{player_photo}" 
                 alt="{player.get('full_name', 'Unknown')}" 
                 style="width:30px; height:40px; border-radius:5px; margin-right:5px;">
            {player.get('full_name', 'Unknown')}
        </td>
        <td>
            <img src="{team_logo}" 
                 alt="Team Logo" 
                 title="{get_team_name(player.get('team', 0))}" 
                 style="width:20px; height:20px; border-radius:50%; margin-right:5px;">
            {get_team_name(player.get('team', 0))}
        </td>
        <td>{player.get('position', 'Unknown')}</td>
        <td>{player.get('form', 'N/A')}</td>
        <td>{player.get('total_points', 'N/A')}</td>
        <td>{player.get('now_cost', 'N/A')}</td>
        <td>{player.get('fixture_difficulty', 'N/A')}</td>
        <td>{player.get('vfm', 'N/A')}</td>
    </tr>
    """

def get_team_name(team_id):
    """Map team IDs to team names."""
    team_names = {
        1: "Arsenal",
        2: "Aston Villa",
        3: "Brentford",
        4: "Brighton",
        5: "Burnley",
        6: "Chelsea",
        7: "Crystal Palace",
        8: "Everton",
        9: "Leicester",
        10: "Leeds",
        11: "Liverpool",
        12: "Man City",
        13: "Man Utd",
        14: "Newcastle",
        15: "Norwich",
        16: "Southampton",
        17: "Spurs",
        18: "Watford",
        19: "West Ham",
        20: "Wolves"
    }
    return team_names.get(team_id, "Unknown Team")

def build_html_table(players):
    """Build an HTML table with team logos, player photos, and hover-over tooltips."""
    if not players:
        return "<p>No player data available.</p>"

    rows = ''.join([generate_player_row(player) for player in players])
    table = f"""
    <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
        <thead>
            <tr>
                <th>Player</th>
                <th>Team</th>
                <th>Position</th>
                <th>Form</th>
                <th>Total Points</th>
                <th>Cost</th>
                <th>FDR</th>
                <th>VFM</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """
    return table

async def suggest_best_players(fpl, team_fixtures, top_n=10):
    """Suggest the best players to pick based on form, points, and FDR."""
    try:
        players = await fpl.get_players()
        player_data = []
        for player in players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:
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
            # Check if player object is valid and has required attributes
            if not player or not hasattr(player, 'team'):
                logger.warning(f"⚠️ Invalid player object or missing team attribute for player: {player}")
                continue

            fdr = await calculate_team_fdr(team_fixtures, player.team)
            captain_score = (float(player.form) * 0.4) + (player.total_points * 0.3) + ((6 - fdr) * 0.3)
            captain_data.append({
                "full_name": f"{player.first_name} {player.second_name}",
                "team": player.team,
                "form": float(player.form),
                "total_points": player.total_points,
                "fixture_difficulty": fdr,
                "captain_score": captain_score
            })

        if not captain_data:
            logger.warning("⚠️ No valid captain data found.")
            return pd.DataFrame(), pd.DataFrame()  # Return empty DataFrames

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
    """Suggest when to use the Bench Boost chip."""
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
                fdr = team_fixtures.get(player.team, {}).get(gw, 5)
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

async def suggest_triple_captain(fpl, team_fixtures, user_team):
    """Suggest when to use the Triple Captain chip."""
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
            fdr = fixtures.get(gw, 5)
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
            position_map = {
                1: "Goalkeeper",
                2: "Defender",
                3: "Midfielder",
                4: "Forward"
            }
            position = position_map.get(player.element_type, "Unknown")

            team_data.append({
                "full_name": f"{player.first_name} {player.second_name}",
                "position": position,
                "form": float(player.form),
                "total_points": player.total_points,
                "now_cost": player.now_cost / 10,
                "fixture_difficulty": fdr,
                "status": player.status
            })

        df = pd.DataFrame(team_data)
        underperforming_players = df[
            (df["form"] < 2.0) |
            (df["status"] != "a") |
            (df["fixture_difficulty"] > (FIXTURE_LOOKAHEAD * 3))
        ]

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
            position_map = {
                1: "Goalkeeper",
                2: "Defender",
                3: "Midfielder",
                4: "Forward"
            }
            position = position_map.get(p.element_type, "Unknown")

            if position == player["position"] and p.now_cost / 10 <= player["now_cost"] + 1.0:
                data = await fetch_player_data(fpl, p, team_fixtures)
                if data:
                    player_data.append(data)

        df = pd.DataFrame(player_data)
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
        for fixture in fixtures:
            if fixture.event is None or fixture.finished:
                continue
            if fixture.event not in gameweek_fixtures:
                gameweek_fixtures[fixture.event] = 0
            gameweek_fixtures[fixture.event] += 1

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
    """Export dataframes to CSV and Excel files."""
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

        # Attach the HTML body with improved styling and gameweek title
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
                .email-container {{
                    max-width: 800px;
                    margin: 0 auto;
                    background-color: #ffffff;
                    padding: 20px;
                    border-radius: 10px;
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                }}
                h1 {{
                    text-align: center;
                    color: #0044cc;
                    margin-bottom: 20px;
                }}
                h2 {{
                    background-color: #0044cc;
                    color: #ffffff;
                    padding: 10px;
                    border-radius: 5px;
                    text-align: center;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                }}
                th, td {{
                    padding: 10px;
                    text-align: center;
                    border: 1px solid #dddddd;
                }}
                th {{
                    background-color: #007bff;
                    color: #ffffff;
                }}
                tr:nth-child(even) {{
                    background-color: #f2f2f2;
                }}
                tr:hover {{
                    background-color: #e6f7ff;
                }}
                img {{
                    vertical-align: middle;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 20px;
                    font-size: 12px;
                    color: #777777;
                }}
            </style>
        </head>
        <body>
            <div class="email-container">
                <h1>FPL Assistant - Gameweek {CURRENT_GAMEWEEK}</h1>
                {body}
                <div class="footer">
                    <p>This email was generated by the FPL Assistant. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(email_body, "html"))

        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.send_message(msg)

        logger.info("📧 Email sent successfully.")
    except Exception as e:
        logger.error(f"❌ Error sending email: {e}")
        raise

async def suggest_free_hit_team(fpl, team_fixtures, budget=100.0):
    """Suggest the best Free Hit team within budget, prioritizing teams with the easiest fixtures."""
    try:
        players = await fpl.get_players()
        player_data = []

        team_fdr = {}
        for team_id, fixtures in team_fixtures.items():
            fdr_sum = sum(
                fixtures.get(gw, 5) for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD)
            )
            team_fdr[team_id] = fdr_sum

        easiest_teams = sorted(team_fdr, key=team_fdr.get)

        for player in players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:
                data["team_fdr"] = team_fdr.get(player.team, 25)
                player_data.append(data)

        df = pd.DataFrame(player_data)

        if df.empty:
            logger.warning("⚠️ No valid players found for Free Hit team.")
            return df

        df["now_cost"] = pd.to_numeric(df["now_cost"], errors="coerce")
        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["total_points"] = pd.to_numeric(df["total_points"], errors="coerce")
        df["fixture_difficulty"] = pd.to_numeric(df["fixture_difficulty"], errors="coerce")
        df["team_fdr"] = pd.to_numeric(df["team_fdr"], errors="coerce")
        df = df.dropna(subset=["now_cost", "form", "total_points", "fixture_difficulty", "team_fdr"])

        df = df.sort_values(
            by=["team_fdr", "form", "total_points", "fixture_difficulty"],
            ascending=[True, False, False, True]
        )

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

        dgw_teams = []
        for team_id, fixtures in team_fixtures.items():
            upcoming_gws = [gw for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD)]
            gw_count = sum(1 for gw in upcoming_gws if gw in fixtures)
            if gw_count >= 2:
                dgw_teams.append(team_id)

        if not dgw_teams:
            logger.warning("⚠️ No Double Gameweek teams found.")
            return pd.DataFrame()

        for player in players:
            if player.team in dgw_teams:
                data = await fetch_player_data(fpl, player, team_fixtures)
                if data:
                    player_data.append(data)

        df = pd.DataFrame(player_data)

        if df.empty:
            logger.warning("⚠️ No valid DGW players found.")
            return df

        df["now_cost"] = pd.to_numeric(df["now_cost"], errors="coerce")
        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["total_points"] = pd.to_numeric(df["total_points"], errors="coerce")
        df = df.dropna(subset=["now_cost", "form", "total_points"])

        df = df.sort_values(by=["form", "total_points"], ascending=[False, False])

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

        players = await fpl.get_players()
        player_data = []

        for player in players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:
                player_data.append(data)

        df = pd.DataFrame(player_data)

        df["now_cost"] = pd.to_numeric(df["now_cost"], errors="coerce")
        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["fixture_difficulty"] = pd.to_numeric(df["fixture_difficulty"], errors="coerce")
        df = df.dropna(subset=["now_cost", "form", "fixture_difficulty"])

        best_players = df.sort_values(by=["form", "total_points", "fixture_difficulty"], ascending=[False, False, True])

        transfers = []
        for player in my_players:
            replacement = best_players[
                (best_players["now_cost"] <= (my_team_cost + budget)) &
                (best_players["form"] > float(player.form)) &
                (best_players["total_points"] > player.total_points) &
                (best_players["fixture_difficulty"] < await calculate_team_fdr(team_fixtures, player.team))
            ].head(1)

            if not replacement.empty:
                transfers.append({
                    "transfer_out": f"{player.first_name} {player.second_name}",
                    "transfer_in": replacement.iloc[0]["full_name"],
                    "cost": float(replacement.iloc[0]["now_cost"] - (player.now_cost / 10))
                })

        return transfers[:free_transfers]
    except Exception as e:
        logger.error(f"❌ Error suggesting transfers: {e}")
        raise

async def suggest_starting_xi(fpl, my_players, team_fixtures):
    """Suggest the optimal starting XI from your current squad with dynamic formation."""
    try:
        player_data = []
        for player in my_players:
            data = await fetch_player_data(fpl, player, team_fixtures)
            if data:
                player_data.append(data)

        df = pd.DataFrame(player_data)

        if df.empty:
            logger.warning("⚠️ No valid player data found for your team.")
            return None, None, None, None

        df["form"] = pd.to_numeric(df["form"], errors="coerce")
        df["fixture_difficulty"] = pd.to_numeric(df["fixture_difficulty"], errors="coerce")
        df = df.dropna(subset=["form", "fixture_difficulty"])

        goalkeepers = df[df["position"] == "Goalkeeper"].sort_values(by=["form", "fixture_difficulty"], ascending=[False, True])
        defenders = df[df["position"] == "Defender"].sort_values(by=["form", "fixture_difficulty"], ascending=[False, True])
        midfielders = df[df["position"] == "Midfielder"].sort_values(by=["form", "fixture_difficulty"], ascending=[False, True])
        forwards = df[df["position"] == "Forward"].sort_values(by=["form", "fixture_difficulty"], ascending=[False, True])

        formations = [
            (3, 4, 3),
            (3, 5, 2),
            (4, 4, 2),
            (4, 3, 3),
            (5, 3, 2)
        ]

        best_xi, best_score, best_formation = None, 0, None

        for def_count, mid_count, fwd_count in formations:
            if len(defenders) >= def_count and len(midfielders) >= mid_count and len(forwards) >= fwd_count:
                xi = pd.concat([
                    goalkeepers.head(1),
                    defenders.head(def_count),
                    midfielders.head(mid_count),
                    forwards.head(fwd_count)
                ])
                score = xi["form"].sum()
                if score > best_score:
                    best_xi, best_score, best_formation = xi, score, (def_count, mid_count, fwd_count)

        if best_xi is None:
            logger.warning("⚠️ No valid starting XI could be formed. Check player data and formations.")
            return None, None, None, None

        bench = df[~df.index.isin(best_xi.index)].sort_values(by=["form", "fixture_difficulty"], ascending=[False, True])

        captain = best_xi.sort_values(by="form", ascending=False).iloc[0]
        vice_captain = best_xi.sort_values(by="form", ascending=False).iloc[1]

        logger.info(f"✅ Best formation: {best_formation[0]}-{best_formation[1]}-{best_formation[2]}")
        logger.info(f"✅ Captain: {captain['full_name']}")
        logger.info(f"✅ Vice-Captain: {vice_captain['full_name']}")

        return best_xi, bench, captain, vice_captain

    except Exception as e:
        logger.error(f"❌ Error suggesting starting XI: {e}")
        raise


async def track_injuries(fpl, user_team):
    """Track injuries and suspensions in your team and suggest replacements."""
    try:
        injured_players = []
        for player in user_team:
            player_data = await fpl.get_player(player["element"])
            if player_data.status != "a":
                injured_players.append({
                    "name": f"{player_data.first_name} {player_data.second_name}",
                    "status": player_data.status
                })

        logger.debug(f"Injured players: {injured_players}")
        return injured_players
    except Exception as e:
        logger.error(f"❌ Error tracking injuries: {e}")
        raise

async def track_team_value(fpl, user_team):
    """Track your team's value and suggest ways to increase it through transfers."""
    try:
        team_value = 0.0
        for player in user_team:
            player_id = player["element"]
            player_data = await fpl.get_player(player_id)
            team_value += player_data.now_cost / 10

        return f"Your team's current value is {team_value:.1f} million."
    except Exception as e:
        logger.error(f"❌ Error tracking team value: {e}")
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

            players = await fpl.get_players()
            team_fixtures = await get_fixture_difficulties(fpl)

            # Fetch the user's current players
            my_players = [await fpl.get_player(p["element"]) for p in user_team]

            # Suggest the optimal starting XI and bench
            logger.info("\n🌟 Suggesting Optimal Starting XI and Bench:")
            starting_xi, bench, captain, vice_captain = await suggest_starting_xi(fpl, my_players, team_fixtures)
            if starting_xi is not None:
                logger.info("Starting XI:\n%s", starting_xi)
                logger.info("Bench:\n%s", bench)
            else:
                logger.warning("⚠️ No valid starting XI or bench data found.")

            logger.info("\n🔼 Best Players to Pick:")
            best_players = await suggest_best_players(fpl, team_fixtures)
            logger.info(best_players)

            logger.info("\n🔽 Suggested Transfers Out:")
            transfers_out = await suggest_transfers_out(fpl, team_fixtures, user_team)
            logger.info(transfers_out)

            logger.info("\n🎖 Captaincy Recommendations:")
            captain, vice_captain = await suggest_captain(fpl, team_fixtures, user_team)

            # Log the captain and vice-captain data for debugging
            logger.info("Captain data: %s", captain)
            logger.info("Vice-Captain data: %s", vice_captain)

            if not captain.empty:
                logger.info("Captain: %s", captain.iloc[0]['full_name'])
            else:
                logger.warning("⚠️ No valid captain data found.")

            if not vice_captain.empty:
                logger.info("Vice-Captain: %s", vice_captain.iloc[0]['full_name'])
            else:
                logger.warning("⚠️ No valid vice-captain data found.")

            if not vice_captain.empty:
                logger.info("Vice-Captain: %s", vice_captain.iloc[0]['full_name'])
            else:
                logger.warning("⚠️ No valid vice-captain data found.")
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
            best_players_html = build_html_table(best_players.to_dict('records')) if not best_players.empty else "<p>No data available for best players.</p>"
            transfers_out_html = build_html_table(transfers_out.to_dict('records')) if not transfers_out.empty else "<p>No data available for transfers out.</p>"
            free_hit_team_html = build_html_table(free_hit_team.to_dict('records')) if not free_hit_team.empty else "<p>No valid Free Hit squad could be formed within budget.</p>"
            dgw_team_html = build_html_table(dgw_team.to_dict('records')) if not dgw_team.empty else "<p>No valid DGW squad could be formed within budget.</p>"
            underperforming_players_html = build_html_table(underperforming_players.to_dict('records')) if not underperforming_players.empty else "<p>No underperforming players found.</p>"
            replacements_html = build_html_table(pd.DataFrame(replacements).to_dict('records')) if replacements else "<p>No suggested replacements found.</p>"

            # Build HTML tables for starting XI and bench
            starting_xi_html = build_html_table(starting_xi.to_dict('records')) if starting_xi is not None else "<p>No starting XI data available.</p>"
            bench_html = build_html_table(bench.to_dict('records')) if bench is not None else "<p>No bench data available.</p>"

            # Create the email body with HTML formatting
            # Create the email body with HTML formatting
            email_body = f"""
                <h2>🌟 Starting XI</h2>
                {starting_xi_html}
                <h2>🌟 Bench</h2>
                {bench_html}
                <h2>🔼 Best Players to Pick</h2>
                {best_players_html}
                <h2>🔽 Suggested Transfers Out</h2>
                {transfers_out_html}
                <h2>🎖 Captaincy Recommendations</h2>
            """

            # Safely extract captain data
            if not captain.empty and 'team' in captain.columns:
                captain_name = captain.iloc[0].get('full_name', 'Unknown')
                captain_team = get_team_name(captain.iloc[0].get('team', 0))
                captain_form = captain.iloc[0].get('form', 'N/A')
                captain_fdr = captain.iloc[0].get('fixture_difficulty', 'N/A')
            else:
                captain_name = 'No valid captain'
                captain_team = 'N/A'
                captain_form = 'N/A'
                captain_fdr = 'N/A'

            # Safely extract vice-captain data
            if not vice_captain.empty and 'team' in vice_captain.columns:
                vice_captain_name = vice_captain.iloc[0].get('full_name', 'Unknown')
                vice_captain_team = get_team_name(vice_captain.iloc[0].get('team', 0))
                vice_captain_form = vice_captain.iloc[0].get('form', 'N/A')
                vice_captain_fdr = vice_captain.iloc[0].get('fixture_difficulty', 'N/A')
            else:
                vice_captain_name = 'No valid vice-captain'
                vice_captain_team = 'N/A'
                vice_captain_form = 'N/A'
                vice_captain_fdr = 'N/A'

            email_body += f"""
                <p><strong>Captain:</strong> {captain_name} 
                (Team: {captain_team}, 
                Form: {captain_form}, 
                FDR: {captain_fdr})</p>

                <p><strong>Vice-Captain:</strong> {vice_captain_name} 
                (Team: {vice_captain_team}, 
                Form: {vice_captain_form}, 
                FDR: {vice_captain_fdr})</p>
            """

            # Add the rest of the email body
            email_body += f"""
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
            """

            # Send email with suggestions
            await send_email("Your Weekly FPL Suggestions", email_body)

    except Exception as e:
        logger.error(f"❌ Fatal error in main function: {e}")

if __name__ == "__main__":
    asyncio.run(main())