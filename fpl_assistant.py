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
CURRENT_GAMEWEEK = 28  # Update this to the current gameweek

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


async def get_fixture_difficulties(fpl):
    """Fetch fixture difficulties for all teams."""
    try:
        fixtures = await fpl.get_fixtures()
        team_fixtures = {}
        for fixture in fixtures:
            if fixture.finished or fixture.event is None:
                continue
            for team_id, difficulty in [
                (fixture.team_h, fixture.team_h_difficulty),
                (fixture.team_a, fixture.team_a_difficulty)
            ]:
                if team_id not in team_fixtures:
                    team_fixtures[team_id] = []
                team_fixtures[team_id].append(difficulty)
        return team_fixtures
    except Exception as e:
        logger.error(f"❌ Error fetching fixture difficulties: {e}")
        raise


async def calculate_team_fdr(team_fixtures, team_id):
    """Calculate the total fixture difficulty rating (FDR) for a team, ensuring valid FDR values (1-5)."""
    fixtures = team_fixtures.get(team_id, [])
    
    # Ensure FDR values are within the valid range (1-5)
    valid_fixtures = [min(max(fdr, 1), 5) for fdr in fixtures[:FIXTURE_LOOKAHEAD]]
    
    return sum(valid_fixtures)

async def fetch_player_data(fpl, player, team_fixtures):
    """Fetch and format player data."""
    try:
        fdr = await calculate_team_fdr(team_fixtures, player.team)
        return {
            "full_name": f"{player.first_name} {player.second_name}",
            "team": player.team,
            "form": float(player.form),
            "total_points": player.total_points,
            "now_cost": player.now_cost / 10,
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
    """Suggest the best gameweek to use the Bench Boost chip based on future fixtures."""
    try:
        bench_players = []
        bench_scores = []

        # Identify bench players based on their position in the user's team
        for player in user_team:
            if player["position"] >= 12:  # Bench players have position 12, 13, 14, or 15
                player_data = await fpl.get_player(player["element"])
                bench_players.append(player_data)

        if not bench_players:  # No bench players found
            logger.warning("⚠️ No bench players found for Bench Boost suggestion.")
            return None

        # Log bench players for debugging
        logger.debug("Bench Players:")
        for player in bench_players:
            logger.debug(f"- {player.first_name} {player.second_name} (Team: {player.team}, Form: {player.form})")

        # Calculate bench scores for bench players across future gameweeks
        best_gw = CURRENT_GAMEWEEK
        best_bench_score = 0

        for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD):
            total_bench_score = 0

            for player in bench_players:
                fdr = await calculate_team_fdr(team_fixtures, player.team)
                bench_score = (float(player.form) * 0.5) + ((6 - fdr) * 0.5)
                total_bench_score += bench_score

                # Log player's FDR and bench score for debugging
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
    """Suggest the best gameweek to use the Triple Captain chip based on CURRENT_GAMEWEEK."""
    try:
        captain, _ = await suggest_captain(fpl, team_fixtures, user_team)
        
        # Extract the team ID from the captain DataFrame
        captain_team_id = captain.iloc[0]["team"]  # Access the first row and the "team" column
        
        # Log the captain's team ID for debugging
        logger.debug(f"Captain's team ID: {captain_team_id}")
        
        # Log all team IDs in team_fixtures for debugging
        logger.debug(f"Team IDs in team_fixtures: {list(team_fixtures.keys())}")
        
        # Get the captain's fixture difficulty for the current and upcoming gameweeks
        captain_fixtures = team_fixtures.get(captain_team_id, [])
        
        # Log the captain's fixtures for debugging
        logger.debug(f"Captain's fixtures: {captain_fixtures}")
        
        if not captain_fixtures:
            logger.warning(f"No fixture data found for team ID {captain_team_id}.")
            return "No fixture data found for the captain's team. Save Triple Captain for a future gameweek."

        # Find the gameweek with the easiest fixture for the captain
        best_gw = CURRENT_GAMEWEEK  # Start with the current gameweek
        easiest_fdr = float("inf")  # Initialize with a high value
        valid_fixtures_found = False

        for gw in range(CURRENT_GAMEWEEK, CURRENT_GAMEWEEK + FIXTURE_LOOKAHEAD):
            if gw - 1 < len(captain_fixtures):  # Ensure we don't go out of bounds
                fdr = captain_fixtures[gw - 1]  # Fixture difficulty for the gameweek
                logger.debug(f"Gameweek {gw} - FDR: {fdr}")
                if fdr < easiest_fdr:
                    easiest_fdr = fdr
                    best_gw = gw
                    valid_fixtures_found = True
            else:
                logger.debug(f"No fixture data for Gameweek {gw}.")

        if not valid_fixtures_found:  # No valid fixture difficulties found
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
    """Export dataframes to CSV and Excel files."""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        best_players.to_csv(f'best_players_{timestamp}.csv', index=False)
        transfers_out.to_csv(f'transfers_out_{timestamp}.csv', index=False)

        with pd.ExcelWriter(f'fpl_suggestions_{timestamp}.xlsx') as writer:
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


async def main():
    """Main function to run the FPL assistant."""
    try:
        cookies = load_cookies()

        async with aiohttp.ClientSession(cookies=cookies) as session:
            fpl = FPL(session)
            logger.info("✅ Logged in using full browser cookies!")

            user = await fpl.get_user(TEAM_ID)
            user_team = await user.get_team()

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

            await export_dataframes(best_players, transfers_out)

            # Convert dataframes to HTML tables
            best_players_html = best_players.to_html(index=False)
            transfers_out_html = transfers_out.to_html(index=False)

            # Create the email body with HTML formatting
            email_body = f"""
            <html>
                <body>
                    <h2>🔼 Best Players to Pick</h2>
                    {best_players_html}
                    <br>
                    <h2>🔽 Suggested Transfers Out</h2>
                    {transfers_out_html}
                    <br>
                    <h2>🎖 Captaincy Recommendations</h2>
                    <p><strong>Captain:</strong> {captain.iloc[0]['full_name']} (Team: {captain.iloc[0]['team']}, Form: {captain.iloc[0]['form']}, FDR: {captain.iloc[0]['fixture_difficulty']})</p>
                    <p><strong>Vice-Captain:</strong> {vice_captain.iloc[0]['full_name']} (Team: {vice_captain.iloc[0]['team']}, Form: {vice_captain.iloc[0]['form']}, FDR: {vice_captain.iloc[0]['fixture_difficulty']})</p>
                    <br>
                    <h2>🌟 Bench Boost Suggestion</h2>
                    <p>{bench_boost_suggestion}</p>
                    <br>
                    <h2>🌟 Triple Captain Suggestion</h2>
                    <p>{triple_captain_suggestion}</p>
                    <br>
                    <h2>🃏 Wildcard Suggestion</h2>
                    <p>{wildcard_suggestion}</p>
                    <br>
                    <h2>🎯 Free Hit Suggestion</h2>
                    <p>{free_hit_suggestion}</p>
                </body>
            </html>
            """

            # Send email with suggestions
            await send_email("Your Weekly FPL Suggestions", email_body)

    except Exception as e:
        logger.error(f"❌ Fatal error in main function: {e}")


if __name__ == "__main__":
    asyncio.run(main())