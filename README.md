Author: Jamie McKee


# ⚽ Fantasy Premier League (FPL) Assistant

This Python script helps you manage your Fantasy Premier League (FPL) team by:
- 🔍 Authenticating with your full FPL browser session cookies.
- 📊 Analyzing global player data.
- 📅 Evaluating upcoming fixture difficulty (FDR).
- 🧠 Suggesting the best players to pick for upcoming gameweeks.
- 🔄 Identifying weak players in your current squad to transfer out.
- 📁 Exporting the recommendations to CSV and Excel files.

---

## 🚀 Features
✅ Secure FPL login via the `fpl` library using full browser cookies.  
✅ Automatically fetch your current team.  
✅ Analyze player form, points, and fixture difficulty (next 5 matches).  
✅ Suggest the best players to bring in.  
✅ Suggest underperforming or risky players to transfer out.  
✅ Export all suggestions to CSV and Excel for easy viewing.

---

## 🛠 Requirements
- Python 3.8+
- Packages:
  - `fpl`
  - `aiohttp`
  - `pandas`

Install dependencies with:
```bash
pip install fpl aiohttp pandas
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

The script will automatically load this `cookies.json` file for authentication.

---

## 🔧 How to Use

1. **Clone or download the script.**
2. **Ensure your `cookies.json` file is set with your cookies.**
3. **Run the script:**
   ```bash
   python fpl_assistant.py
   ```

4. The script will:
   - Authenticate using your full FPL session cookies.
   - Retrieve your current team (using your FPL Team ID).
   - Analyze players and fixtures.
   - Print suggestions directly in the terminal.
   - Export CSV and Excel files with full suggestions.

---

## 🏷 Files Generated
- `best_players_<timestamp>.csv`  
  Top player recommendations based on form, points, and fixture difficulty.

- `transfers_out_<timestamp>.csv`  
  Players from your current squad flagged for transfer out.

- `fpl_suggestions_<timestamp>.xlsx`  
  Combined Excel file with both datasets.

---

## ⚙️ Configuration
Inside the script, edit these if needed:
```python
TEAM_ID = 6378398           # Your FPL Team ID
FIXTURE_LOOKAHEAD = 5       # Number of upcoming fixtures to consider
```

---

## 🌟 Future Ideas
- Captaincy recommendations.
- Price change alerts.
- Squad optimization based on available budget.
- Visual charts of fixture difficulty.
- Weekly email notifications with personalized suggestions.

---

## ⚠️ Important Notes
- Your cookies are only used during the session and are not stored elsewhere.
- Make sure your cookies are current and not expired.
- Use responsibly and avoid excessive requests to the FPL servers.

---

## 📬 Feedback
Feel free to suggest improvements or request new features!
