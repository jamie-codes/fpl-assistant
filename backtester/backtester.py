import asyncio
import io
import os
import logging
import smtplib
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email import encoders
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
from fpl import FPL
from dotenv import load_dotenv
import aiofiles
import aiofiles.os

# Configuration
load_dotenv()
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
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/backtester.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Strategy Configuration
STRATEGIES = {
    "Form-Based": {"form_weight": 0.6, "fixture_weight": 0.2, "value_weight": 0.2},
    "Fixture-Based": {"form_weight": 0.2, "fixture_weight": 0.6, "value_weight": 0.2},
    "Value-Based": {"form_weight": 0.2, "fixture_weight": 0.2, "value_weight": 0.6},
    "Differential-Based": {"form_weight": 0.4, "fixture_weight": 0.3, "value_weight": 0.3, "max_ownership": 10},
    "Balanced": {"form_weight": 0.4, "fixture_weight": 0.3, "value_weight": 0.3}
}

# Backtester Configuration
BACKTEST_CONFIG = {
    "max_transfers_per_week": 2,
    "min_form_cutoff": 2.0,
    "budget": 100.0,
    "fixture_lookahead": 5,
    "email_notifications": True
}

async def generate_graphs(results):
    """Generate interactive graphs comparing strategy performance."""
    try:
        logger.debug("🔵 Starting to generate graphs...")

        # Create DataFrame for results
        data = []
        for strategy_name, strategy_data in results.items():
            total_points = strategy_data["total_points"]
            points_per_gameweek = strategy_data["points_per_gameweek"]
            for gameweek, points in enumerate(points_per_gameweek, start=1):
                data.append({
                    "Strategy": strategy_name,
                    "Gameweek": gameweek,
                    "Points": points
                })

        df = pd.DataFrame(data)
        logger.debug(f"✅ DataFrame created with {len(df)} rows")
        logger.debug(df.head())

        def plot_graph():
            try:
                logger.debug("📊 Creating figure...")
                fig = px.line(df, x="Gameweek", y="Points", color="Strategy", title="Strategy Performance Comparison")
                logger.debug("✅ Figure created.")

                # Try saving the image
                try:
                    logger.debug("📊 Exporting image...")
                    fig.write_image(f"{OUTPUT_DIR}/strategy_comparison.png", engine="kaleido")
                    logger.debug("✅ Image saved successfully.")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to save image: {e}")

                try:
                    logger.debug("📊 Exporting HTML...")
                    fig.write_html(f"{OUTPUT_DIR}/strategy_comparison.html")
                    logger.debug("✅ HTML file saved successfully.")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to save HTML file: {e}")



                logger.debug("✅ Finished plotting graph.")
            
            except Exception as e:
                logger.error(f"❌ Graph generation error: {e}")


        # Run plot_graph() synchronously first
        plot_graph()

        logger.debug("🔵 Finished generating graphs")

    except Exception as e:
        logger.error(f"❌ Error generating graphs: {e}")
        raise



async def fetch_historical_data(gameweek, data_dir):
    try:
        logger.debug(f"Starting to fetch historical data for gameweek {gameweek}")
        gameweek_data = []
        players_dir = os.path.join(data_dir, "players")

        # Load team data from teams.csv
        teams_path = os.path.join(data_dir, "teams.csv")
        if not await aiofiles.os.path.exists(teams_path):
            logger.error(f"❌ teams.csv file not found at {teams_path}. Please ensure it exists.")
            raise FileNotFoundError(f"teams.csv file not found at {teams_path}.")

        async with aiofiles.open(teams_path, mode='r', encoding='utf-8') as f:
            teams_content = await f.read()
            teams_df = pd.read_csv(io.StringIO(teams_content))
        logger.debug(f"Loaded team data for gameweek {gameweek}")

        # Load player data from players_raw.csv
        players_raw_path = os.path.join(data_dir, "players_raw.csv")
        if not await aiofiles.os.path.exists(players_raw_path):
            logger.error(f"❌ players_raw.csv file not found at {players_raw_path}. Please ensure it exists.")
            raise FileNotFoundError(f"players_raw.csv file not found at {players_raw_path}.")

        async with aiofiles.open(players_raw_path, mode='r', encoding='utf-8') as f:
            players_raw_content = await f.read()
            players_raw_df = pd.read_csv(io.StringIO(players_raw_content))
        logger.debug(f"Loaded player data for gameweek {gameweek}")

        # Iterate through each player's folder
        player_folders = await aiofiles.os.listdir(players_dir)
        logger.debug(f"Found {len(player_folders)} players to process for gameweek {gameweek}")

        for player_folder in player_folders:
            player_path = os.path.join(players_dir, player_folder)
            if await aiofiles.os.path.isdir(player_path):
                try:
                    player_id = int(player_folder.split("_")[-1])  # Extract player ID from folder name
                except (IndexError, ValueError) as e:
                    logger.warning(f"⚠️ Could not extract player ID from folder name: {player_folder}")
                    continue

                logger.debug(f"Processing player {player_id} for gameweek {gameweek}")

                # Load the player's gameweek data
                gw_path = os.path.join(player_path, "gw.csv")
                if await aiofiles.os.path.exists(gw_path):
                    async with aiofiles.open(gw_path, mode='r', encoding='utf-8') as f:
                        gw_content = await f.read()
                        player_history = pd.read_csv(io.StringIO(gw_content))
                    player_history = player_history[player_history["round"] == gameweek]
                    if not player_history.empty:
                        # Extract relevant data for the gameweek
                        team_id = player_history["team"].values[0] if "team" in player_history.columns else None
                        team_name = teams_df[teams_df["id"] == team_id]["name"].values[0] if team_id else "Unknown Team"

                        # Map element_type to position (1: GK, 2: DEF, 3: MID, 4: FWD)
                        player_info = players_raw_df[players_raw_df["id"] == player_id]
                        if not player_info.empty:
                            element_type = player_info["element_type"].values[0]
                            position_map = {1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Forward"}
                            position = position_map.get(element_type, "Unknown")
                            now_cost = player_info["now_cost"].values[0] / 10 if "now_cost" in player_info.columns else 0.0  # Default now_cost value if the column is missing
                        else:
                            position = "Unknown"
                            now_cost = 0.0

                        # Calculate form manually (average points over the last 3 gameweeks)
                        form = 0.0  # Default form value
                        try:
                            # Load the player's full history to calculate form
                            async with aiofiles.open(gw_path, mode='r', encoding='utf-8') as f:
                                player_full_history_content = await f.read()
                                player_full_history = pd.read_csv(io.StringIO(player_full_history_content))
                            last_3_gws = player_full_history[player_full_history["round"].isin(range(gameweek - 3, gameweek))]
                            if not last_3_gws.empty and "total_points" in last_3_gws.columns:
                                form = last_3_gws["total_points"].mean()
                            else:
                                logger.debug(f"⚠️ Insufficient data to calculate form for player {player_id}. Using default value.")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not calculate form for player {player_id}: {e}")

                        # Calculate fixture difficulty manually (based on opponent team strength)
                        fixture_difficulty = 3  # Default fixture difficulty value
                        try:
                            opponent_team_id = player_history["opponent_team"].values[0] if "opponent_team" in player_history.columns else None
                            if opponent_team_id:
                                opponent_strength = teams_df[teams_df["id"] == opponent_team_id]["strength"].values[0]
                                fixture_difficulty = max(1, min(opponent_strength, 5))  # Cap difficulty between 1 and 5
                        except Exception as e:
                            logger.warning(f"⚠️ Could not calculate fixture difficulty for player {player_id}: {e}")

                        # Handle missing 'selected_by_percent' column
                        ownership = player_history["selected_by_percent"].values[0] if "selected_by_percent" in player_history.columns else 0.0

                        # Ensure 'total_points' column exists in the DataFrame
                        total_points = player_history["total_points"].values[0] if "total_points" in player_history.columns else 0

                        # Ensure all required columns are present in the DataFrame
                        gameweek_data.append({
                            "player_id": player_id,
                            "team": team_name,
                            "position": position,
                            "total_points": total_points,  # Always include 'total_points', even if it's 0
                            "form": form,  # Always include 'form', even if it's 0.0
                            "minutes": player_history["minutes"].values[0] if "minutes" in player_history.columns else 0,
                            "fixture_difficulty": fixture_difficulty,  # Always include 'fixture_difficulty', even if it's 3.0
                            "opponent": player_history["opponent_team"].values[0] if "opponent_team" in player_history.columns else "Unknown",
                            "ownership": ownership,  # Always include 'ownership', even if it's 0.0
                            "now_cost": now_cost  # Always include 'now_cost', even if it's 0.0
                        })

        logger.debug(f"Finished fetching historical data for gameweek {gameweek}")
        return gameweek_data
    except Exception as e:
        logger.error(f"❌ Error fetching historical data for gameweek {gameweek}: {e}")
        raise


async def simulate_strategy(strategy_name, gameweeks, data_dir):
    """Simulate a strategy over a range of gameweeks."""
    logger.debug(f"Starting simulation for strategy: {strategy_name}")
    strategy = STRATEGIES[strategy_name]
    squad = []
    total_points = 0
    points_per_gameweek = []

    for gameweek in gameweeks:
        logger.debug(f"Processing gameweek {gameweek} for strategy: {strategy_name}")
        historical_data = await fetch_historical_data(gameweek, data_dir)
        df = pd.DataFrame(historical_data)

        # Ensure 'form', 'fixture_difficulty', 'total_points', 'now_cost', and 'ownership' columns exist in the DataFrame
        if "form" not in df.columns:
            df["form"] = 0.0  # Default form value if the column is missing
        if "fixture_difficulty" not in df.columns:
            df["fixture_difficulty"] = 3.0  # Default fixture difficulty value if the column is missing
        if "total_points" not in df.columns:
            df["total_points"] = 0  # Default total_points value if the column is missing
        if "now_cost" not in df.columns:
            df["now_cost"] = 0.0  # Default now_cost value if the column is missing
        if "ownership" not in df.columns:
            df["ownership"] = 0.0  # Default ownership value if the column is missing

        # Apply strategy weights
        df["score"] = (
            df["form"] * strategy["form_weight"] +
            (6 - df["fixture_difficulty"]) * strategy["fixture_weight"] +
            (df["total_points"] / df["now_cost"]) * strategy["value_weight"]
        )

        # Apply differential filter if applicable
        if "max_ownership" in strategy:
            df = df[df["ownership"] <= strategy["max_ownership"]]

        # Select squad
        squad = df.sort_values(by="score", ascending=False).head(15)
        total_points += squad["total_points"].sum()
        points_per_gameweek.append(squad["total_points"].sum())

    logger.debug(f"Finished simulation for strategy: {strategy_name}")
    return total_points, points_per_gameweek

async def compare_strategies(gameweeks, data_dir):
    """Compare the performance of all strategies."""
    results = {}
    for strategy_name in STRATEGIES:
        total_points, points_per_gameweek = await simulate_strategy(strategy_name, gameweeks, data_dir)
        results[strategy_name] = {
            "total_points": total_points,
            "points_per_gameweek": points_per_gameweek
        }
    return results

async def export_results(results):
    """Export the results of the backtest to CSV and Excel."""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        df = pd.DataFrame(results).T
        df.to_csv(f'{OUTPUT_DIR}/backtest_results_{timestamp}.csv', index=True)
        with pd.ExcelWriter(f'{OUTPUT_DIR}/backtest_results_{timestamp}.xlsx') as writer:
            df.to_excel(writer, sheet_name='Backtest Results', index=True)
        logger.info("📁 Exported backtest results to CSV and Excel.")
    except Exception as e:
        logger.error(f"❌ Error exporting results: {e}")
        raise

async def send_email(subject, body, attachments=None):
    """Send an email with the given subject and body (HTML formatted)."""
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_CONFIG["sender_email"]
        msg["To"] = EMAIL_CONFIG["receiver_email"]
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "html"))

        if attachments:
            for attachment in attachments:
                with open(attachment, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={os.path.basename(attachment)}",
                )
                msg.attach(part)

        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.send_message(msg)

        logger.info("📧 Email sent successfully.")
    except Exception as e:
        logger.error(f"❌ Error sending email: {e}")
        raise

async def main():
    """Main function to run the FPL backtester."""
    try:
        # Path to the historical data directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data", "2022-23")  # Adjust the season folder as needed

        # Define the range of gameweeks to backtest
        gameweeks = range(1, 39)  # Example: Backtest the entire season

        # Compare strategies
        results = await compare_strategies(gameweeks, data_dir)

        # Generate graphs
        await generate_graphs(results)

        # Export results
        await export_results(results)

        # Send email notification if enabled
        if BACKTEST_CONFIG["email_notifications"]:
            email_body = "<h1>FPL Backtest Results</h1>"
            for strategy_name, data in results.items():
                email_body += f"<h2>{strategy_name}</h2><p>Total Points: {data['total_points']}</p>"

                attachments = [
                    f"{OUTPUT_DIR}/strategy_comparison.png",
                    f"{OUTPUT_DIR}/backtest_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
                ]

                # Only add existing files
                valid_attachments = [f for f in attachments if os.path.exists(f)]

                if not valid_attachments:
                    logger.warning("⚠️ No attachments found. Email will be sent without files.")

            await send_email("FPL Backtest Results", email_body, attachments)

    except Exception as e:
        logger.error(f"❌ Fatal error in main function: {e}")

if __name__ == "__main__":
    asyncio.run(main())