
# ⚽ Fantasy Premier League (FPL) Assistant

This Python script helps you manage your Fantasy Premier League (FPL) team by:
- 🔍 Logging into your FPL account.
- 📊 Analyzing global player data.
- 📅 Evaluating upcoming fixture difficulty (FDR).
- 🧠 Suggesting the best players to pick for upcoming gameweeks.
- 🔄 Identifying weak players in your current squad to transfer out.
- 📁 Exporting the recommendations to CSV and Excel files.

---

## 🚀 Features
✅ Secure FPL login (using your email and password).  
✅ Automatically fetch your current team.  
✅ Analyze player form, points, and fixture difficulty (next 5 matches).  
✅ Suggest the best players to bring in.  
✅ Suggest underperforming or risky players to transfer out.  
✅ Export all suggestions to CSV and Excel for easy viewing.

---

## 🛠 Requirements
- Python 3.8+
- Packages:
  - `requests`
  - `pandas`
  - `getpass`

Install dependencies with:
```bash
pip install requests pandas
```

---

## 🔧 How to Use

1. **Clone or download the script.**

2. **Run the script:**
   ```bash
   python fpl_assistant.py
   ```

3. **Enter your FPL credentials** when prompted:
   ```
   Enter your FPL email:
   Enter your FPL password:
   ```

4. The script will:
   - Log in to your FPL account.
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
- Your login details are only used during the session and are not stored.
- Make sure your account uses basic authentication (no two-factor for now).
- Use responsibly and avoid excessive requests to the FPL servers.

---

## 📬 Feedback
Feel free to suggest improvements or request new features!
