import asyncio
import json
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
from fpl import FPL
import aiohttp
from dotenv import load_dotenv

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

async def load_cookies():
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

async def fetch_historical_data(fpl, gameweek):
    try:
        players = await fpl.get_players()
        historical_data = []
        for player in players:
            history = await player.get_history_data()  # Updated method name
            for entry in history:
                if entry["round"] == gameweek:
                    historical_data.append({
                        "player_id": player.id,
                        "name": f"{player.first_name} {player.second_name}",
                        "team": player.team,
                        "position": player.element_type,
                        "total_points": entry["total_points"],
                        "form": entry["form"],
                        "minutes": entry["minutes"],
                        "fixture_difficulty": entry["fixture_difficulty"],
                        "opponent": entry["opponent"],
                        "ownership": entry["selected_by_percent"]
                    })
        return historical_data
    except Exception as e:
        logger.error(f"❌ Error fetching historical data for gameweek {gameweek}: {e}")
        raise

async def simulate_strategy(fpl, strategy_name, gameweeks):
    """Simulate a strategy over a range of gameweeks."""
    strategy = STRATEGIES[strategy_name]
    squad = []
    total_points = 0
    points_per_gameweek = []

    for gameweek in gameweeks:
        historical_data = await fetch_historical_data(fpl, gameweek)
        df = pd.DataFrame(historical_data)

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

    return total_points, points_per_gameweek

async def compare_strategies(fpl, gameweeks):
    """Compare the performance of all strategies."""
    results = {}
    for strategy_name in STRATEGIES:
        total_points, points_per_gameweek = await simulate_strategy(fpl, strategy_name, gameweeks)
        results[strategy_name] = {
            "total_points": total_points,
            "points_per_gameweek": points_per_gameweek
        }
    return results

async def generate_graphs(results):
    """Generate graphs comparing strategy performance."""
    plt.figure(figsize=(10, 6))
    for strategy_name, data in results.items():
        plt.plot(data["points_per_gameweek"], label=strategy_name)
    plt.xlabel("Gameweek")
    plt.ylabel("Points")
    plt.title("Strategy Performance Comparison")
    plt.legend()
    plt.savefig(f"{OUTPUT_DIR}/strategy_comparison.png")
    plt.close()

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
        cookies = await load_cookies()

        async with aiohttp.ClientSession(cookies=cookies) as session:
            fpl = FPL(session)
            logger.info("✅ Logged in using full browser cookies!")

            # Define the range of gameweeks to backtest
            gameweeks = range(1, 39)  # Example: Backtest the entire season

            # Compare strategies
            results = await compare_strategies(fpl, gameweeks)

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
                await send_email("FPL Backtest Results", email_body, attachments)

    except Exception as e:
        logger.error(f"❌ Fatal error in main function: {e}")

if __name__ == "__main__":
    asyncio.run(main())