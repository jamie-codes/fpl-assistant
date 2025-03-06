
Author: Jamie McKee

# ⚽ Fantasy Premier League (FPL) Assistant

![FPL Assistant](https://github.com/user-attachments/assets/c260cb9d-b2fa-4526-a74b-2a38132a1127)


This Python script helps you manage your Fantasy Premier League (FPL) team by:
- 🔍 Authenticating with your full FPL browser session cookies.
- 📊 Analyzing global player data.
- 📅 Evaluating upcoming fixture difficulty (FDR).
- 🧠 Suggesting the best players to pick for upcoming gameweeks.
- 🔄 Identifying weak players in your current squad to transfer out.
- 🌟 Suggesting optimal gameweeks for chips (Bench Boost, Triple Captain, Free Hit, Wildcard).
- 📧 Sending personalized email reports with styled HTML tables.
- 📁 Exporting recommendations to CSV and Excel files.

---

## 🚀 Features
✅ Secure FPL login via the `fpl` library using full browser cookies.  
✅ Automatically fetch your current team.  
✅ Analyze player form, points, and fixture difficulty (next 5 matches).  
✅ Suggest the best players to bring in.  
✅ Suggest underperforming or risky players to transfer out.  
✅ Chip usage recommendations (Bench Boost, Triple Captain, Free Hit, Wildcard).  
✅ Styled HTML email notifications with detailed weekly reports.  
✅ Automatic export of suggestions to CSV and Excel files.  
✅ Organized logs and outputs into `/logs` and `/output` folders.

---

## 🛠 Requirements
- Python 3.8+
- Packages:
  - `fpl`
  - `aiohttp`
  - `pandas`
  - `python-dotenv`

Install dependencies with:
```bash
pip install fpl aiohttp pandas python-dotenv
```

---

## 🔐 Setup Authentication

### How to export your FPL cookies:
1. Log into [https://fantasy.premierleague.com/](https://fantasy.premierleague.com/) in your browser.
2. Open **Developer Tools** (F12 or right-click → Inspect).
3. Go to **Application → Cookies → https://fantasy.premierleague.com/**.
4. Copy all cookie names and values.
5. Save them into a file named `cookies.json` in this format:
   ```json
   {
     "pl_profile": "your_value_here",
     "sessionid": "your_value_here",
     "csrftoken": "your_value_here",
     "other_cookie_name": "other_cookie_value_here"
   }
   ```

---

## ✉️ Setup Email Notifications

1. Create a `.env` file in the same directory as the script:
   ```bash
   EMAIL_PASSWORD=your_gmail_app_password
   ```

2. Update the `EMAIL_CONFIG` dictionary in the script with your sender and receiver email addresses.

> ⚠️ You must use an [App Password](https://support.google.com/mail/answer/185833?hl=en-GB) if using Gmail with 2FA enabled. This is different to your email password.

---

## 🔧 How to Use

1. **Clone or download the script.**
2. **Ensure your `cookies.json` and `.env` files are set up.**
3. **Run the script:**
   ```bash
   python fpl_assistant.py
   ```

4. The script will:
   - Authenticate using your FPL session cookies.
   - Retrieve your current team.
   - Analyze players and fixtures.
   - Suggest transfers, chip usage, and captaincy.
   - Export CSV and Excel files to `/output`.
   - Save logs to `/logs`.
   - Email you a full weekly report.

---

## 🏷 Files Generated
All files are stored in the `output/` directory:
- `best_players_<timestamp>.csv`  
  Top player recommendations based on form, points, and fixture difficulty.

- `transfers_out_<timestamp>.csv`  
  Players from your current squad flagged for transfer out.

- `fpl_suggestions_<timestamp>.xlsx`  
  Combined Excel file with both datasets.

Logs are stored in the `logs/` directory:
- `fpl_assistant.log`

---

## ⚙️ Configuration
Inside the script, you can edit:
```python
TEAM_ID = 6378398           # Your FPL Team ID
FIXTURE_LOOKAHEAD = 5       # Number of upcoming fixtures to consider
```

---

## 🌟 Future Ideas
- Advanced squad optimization based on budget and formation.
- Value for Money ranking (VFM) to help identify high-scoring low-cost gems that maximize budget efficiency.
- Perfect Free Hit Squad Selector (within budget)
- Double Gameweek (DGW) & Blank Gameweek (BGW) Planner
- Injury & Rotation Risk Filter
- Visual charts of fixture difficulty and player trends.
- More detailed email reports with graphs and player insights.
- Automated backtesting of transfer strategies.

---

## ⚠️ Important Notes
- Ensure your cookies are current and not expired.
- Avoid excessive requests to the FPL servers.
- Email credentials are securely loaded from environment variables.

---

## 📬 Feedback
Feel free to suggest improvements or request new features!
