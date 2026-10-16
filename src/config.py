import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    # Load .env from project root
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass

# Application Version (managed directly in code repository)
VERSION = "1.11.0"

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "fantasy.db"
HEADSHOTS_DIR = DATA_DIR / "headshots"
PLAYERS_CACHE_FILE = DATA_DIR / "players.json"

# League Configuration (populated from .env or environment variables)
DEFAULT_LEAGUE_ID = os.getenv("LEAGUE_ID", "")
DEFAULT_TEAM_NAME = os.getenv("TEAM_NAME", "") or os.getenv("DEFAULT_TEAM_NAME", "")
CURRENT_SEASON = os.getenv("CURRENT_SEASON", "2026")
DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", 20))

# Sync Schedule Configuration (every 30 minutes on the hour and half-hour)
SYNC_CRON = os.getenv("SYNC_CRON", "0,30 * * * *")
SYNC_INTERVAL_DESC = "Every 30 min (:00, :30)"

# Colors & Visualization
TEAM_PALETTE = [
    '#38bdf8',  # Sky Blue
    '#34d399',  # Emerald Green
    '#f43f5e',  # Rose
    '#a855f7',  # Purple
    '#fb923c',  # Orange
    '#f472b6',  # Pink
    '#2dd4bf',  # Teal
    '#818cf8',  # Indigo
    '#facc15',  # Yellow
    '#4ade80',  # Lime
]

FREE_AGENT_COLOR = '#94a3b8'  # Slate grey

# Database sync metadata keys
METADATA_LAST_SYNC = "last_sync_timestamp"
METADATA_VERSION = "schema_version"

# Full NFL Team Franchise Names
NFL_TEAM_NAMES = {
    'ARI': 'Arizona Cardinals',
    'ATL': 'Atlanta Falcons',
    'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers',
    'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals',
    'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions',
    'GB':  'Green Bay Packers',
    'HOU': 'Houston Texans',
    'IND': 'Indianapolis Colts',
    'JAX': 'Jacksonville Jaguars',
    'KC':  'Kansas City Chiefs',
    'LAC': 'Los Angeles Chargers',
    'LAR': 'Los Angeles Rams',
    'LV':  'Las Vegas Raiders',
    'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings',
    'NE':  'New England Patriots',
    'NO':  'New Orleans Saints',
    'NYG': 'New York Giants',
    'NYJ': 'New York Jets',
    'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers',
    'SEA': 'Seattle Seahawks',
    'SF':  'San Francisco 49ers',
    'TB':  'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders',
    'FA':  'Free Agent',
}

# Official NFL Team Primary Colors
NFL_TEAM_COLORS = {
    'ARI': '#97233F',  # Arizona Cardinals
    'ATL': '#A71930',  # Atlanta Falcons
    'BAL': '#241773',  # Baltimore Ravens
    'BUF': '#00338D',  # Buffalo Bills
    'CAR': '#0085CA',  # Carolina Panthers
    'CHI': '#0B162A',  # Chicago Bears
    'CIN': '#FB4F14',  # Cincinnati Bengals
    'CLE': '#FF3C00',  # Cleveland Browns
    'DAL': '#003594',  # Dallas Cowboys
    'DEN': '#FB4F14',  # Denver Broncos
    'DET': '#0076B6',  # Detroit Lions
    'GB':  '#203731',  # Green Bay Packers
    'HOU': '#03202F',  # Houston Texans
    'IND': '#002C5F',  # Indianapolis Colts
    'JAX': '#006778',  # Jacksonville Jaguars
    'KC':  '#E31837',  # Kansas City Chiefs
    'LAC': '#0080C6',  # Los Angeles Chargers
    'LAR': '#003594',  # Los Angeles Rams
    'LV':  '#000000',  # Las Vegas Raiders
    'MIA': '#008E97',  # Miami Dolphins
    'MIN': '#4F2683',  # Minnesota Vikings
    'NE':  '#002244',  # New England Patriots
    'NO':  '#D3BC8D',  # New Orleans Saints
    'NYG': '#0B2265',  # New York Giants
    'NYJ': '#125740',  # New York Jets
    'PHI': '#004C54',  # Philadelphia Eagles
    'PIT': '#FFB612',  # Pittsburgh Steelers
    'SEA': '#002244',  # Seattle Seahawks
    'SF':  '#AA0000',  # San Francisco 49ers
    'TB':  '#D50A0A',  # Tampa Bay Buccaneers
    'TEN': '#0C2340',  # Tennessee Titans
    'WAS': '#5A1414',  # Washington Commanders
    'FA':  '#94A3B8',  # Free Agent
}
