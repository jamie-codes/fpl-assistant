import requests
import pandas as pd
import getpass
from datetime import datetime
from collections import defaultdict


TEAM_ID = 6378398
FIXTURE_LOOKAHEAD = 5  # Number of upcoming fixtures to analyze


def login_fpl():
    session = requests.Session()
    login_url = 'https://users.premierleague.com/accounts/login/'

    email = input("Enter your FPL email: ")
    password = getpass.getpass("Enter your FPL password: ")

    payload = {
        'login': email,
        'password': password,
        'redirect_uri': 'https://fantasy.premierleague.com/',
    }

    headers = {
        'Referer': login_url,
        'User-Agent': 'Mozilla/5.0'
    }

    response = session.post(login_url, data=payload, headers=headers)
    
    if response.status_code != 200 or 'Invalid' in response.text:
        raise Exception('Login failed. Check your credentials.')

    print("✅ Successfully logged in!")
    return session


def fetch_bootstrap_data():
    url = 'https://fantasy.premierleague.com/api/bootstrap-static/'
    response = requests.get(url)
    return response.json()


def fetch_fixtures():
    url = 'https://fantasy.premierleague.com/api/fixtures/'
    response = requests.get(url)
    return response.json()


def fetch_my_team(session):
    url = f"https://fantasy.premierleague.com/api/my-team/{TEAM_ID}/"
    response = session.get(url)
    return response.json()


def calculate_fixture_difficulty(fixtures, player_team_id):
    upcoming_fixtures = [
        fixture for fixture in fixtures
        if fixture['team_h'] == player_team_id or fixture['team_a'] == player_team_id
    ]
    upcoming_fixtures = sorted(upcoming_fixtures, key=lambda x: x['event'])[:FIXTURE_LOOKAHEAD]
    total_difficulty = sum(
        fixture['team_h_difficulty'] if fixture['team_h'] == player_team_id else fixture['team_a_difficulty']
        for fixture in upcoming_fixtures
    )
    return total_difficulty


def get_best_players(data, fixtures, top_n=10):
    players = pd.DataFrame(data['elements'])
    teams = pd.DataFrame(data['teams'])

    players['full_name'] = players['first_name'] + ' ' + players['second_name']
    team_map = dict(zip(teams['id'], teams['name']))
    players['team_name'] = players['team'].map(team_map)

    fixture_difficulties = {}
    for _, row in players.iterrows():
        fixture_difficulties[row['id']] = calculate_fixture_difficulty(fixtures, row['team'])

    players['fixture_difficulty'] = players['id'].map(fixture_difficulties)
    players['form'] = players['form'].astype(float)

    top_players = players.sort_values(
        by=['form', 'total_points', 'fixture_difficulty'],
        ascending=[False, False, True]
    ).head(top_n)

    return top_players[['full_name', 'team_name', 'form', 'total_points', 'now_cost', 'fixture_difficulty']]


def suggest_transfers_out(my_team_data, fpl_data, fixtures):
    players = pd.DataFrame(fpl_data['elements'])
    my_player_ids = [p['element'] for p in my_team_data['picks']]
    my_players = players[players['id'].isin(my_player_ids)]
    my_players['full_name'] = my_players['first_name'] + ' ' + my_players['second_name']
    my_players['form'] = my_players['form'].astype(float)

    fixture_difficulties = {}
    for _, row in my_players.iterrows():
        fixture_difficulties[row['id']] = calculate_fixture_difficulty(fixtures, row['team'])

    my_players['fixture_difficulty'] = my_players['id'].map(fixture_difficulties)

    transfers_out = my_players[
        (my_players['form'] < 2.0) |
        (my_players['status'] != 'a') |
        (my_players['fixture_difficulty'] > (FIXTURE_LOOKAHEAD * 3))
    ]

    return transfers_out[['full_name', 'form', 'status', 'total_points', 'fixture_difficulty']]


def export_dataframes(best_players, transfers_out):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    best_players.to_csv(f'best_players_{timestamp}.csv', index=False)
    transfers_out.to_csv(f'transfers_out_{timestamp}.csv', index=False)

    with pd.ExcelWriter(f'fpl_suggestions_{timestamp}.xlsx') as writer:
        best_players.to_excel(writer, sheet_name='Best Players', index=False)
        transfers_out.to_excel(writer, sheet_name='Transfers Out', index=False)

    print(f"📁 Exported suggestions to CSV and Excel.")


def main():
    session = login_fpl()
    fpl_data = fetch_bootstrap_data()
    fixtures = fetch_fixtures()
    my_team_data = fetch_my_team(session)

    print("\n🔼 Best Players to Pick:")
    best_players = get_best_players(fpl_data, fixtures)
    print(best_players)

    print("\n🔽 Suggested Transfers Out:")
    transfers_out = suggest_transfers_out(my_team_data, fpl_data, fixtures)
    print(transfers_out)

    export_dataframes(best_players, transfers_out)


if __name__ == "__main__":
    main()
