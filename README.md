# 🏈 Sleeper Fantasy Football Analytics Dashboard

A self-hosted, reactive fantasy football analytics suite built with **Marimo**, **Pandas**, and **SQLite**, designed to run 24/7 on a **Raspberry Pi** (or any server/Docker host).

---

## 📑 Table of Contents
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Database Schema](#database-schema)
- [Multi-Season & Year Separation](#multi-season--year-separation)
- [Docker & Containerization](#docker--containerization)
- [Raspberry Pi & Local Domain Setup (with Homebridge)](#raspberry-pi--local-domain-setup-with-homebridge)
- [Automated Data Sync (Every 30 Minutes: :00 & :30)](#automated-data-sync-every-30-minutes-00--30)
- [Deployment & Configuration](#deployment--configuration)

---

## 🛠️ Architecture & Tech Stack

```mermaid
flowchart TD
    SleeperAPI["Sleeper NFL API"] -->|"Twice Hourly Sync (:00 & :30)"| Sync["src/sync.py"]
    Sync -->|"Write / Update"| DB[("SQLite: data/fantasy.db")]
    DB -->|"Read Active Season"| Marimo["Marimo Dashboard (app.py)"]
    Marimo -->|"Port 8501 / 80"| Client["Local Devices (Mac, Phone, Tablet)"]
```

- **Frontend & UI**: [Marimo](https://marimo.io) (Reactive Python notebook & web application)
- **Data Engine**: Pandas + NumPy
- **Database**: SQLite 3 (`data/fantasy.db`)
- **Containerization**: Docker & Docker Compose (Debian-based Python 3.11 with cron + tzdata)

---

## 🗄️ Database Schema

The database is structured to store historical weekly statistics, player information, team standings, and roster snapshots.

```mermaid
erDiagram
    PLAYERS ||--o{ CURRENT_ROSTERS : "rostered in"
    TEAMS ||--o{ CURRENT_ROSTERS : "contains"
    TEAMS ||--o{ WEEKLY_MATCHUP_POINTS : "scored by"
    PLAYERS ||--o{ WEEKLY_MATCHUP_POINTS : "scored in"
    PLAYERS ||--o{ WEEKLY_NFL_STATS : "recorded for"

    PLAYERS {
        text player_id PK
        text full_name
        text position
        text nfl_team
        text status
        text injury_status
        integer age
        integer years_exp
        timestamp updated_at
    }

    TEAMS {
        integer roster_id PK
        text league_id PK
        text owner_id
        text team_name
        text owner_name
        integer wins
        integer losses
        real fpts
        real fpts_against
        timestamp updated_at
    }

    CURRENT_ROSTERS {
        text league_id PK
        integer roster_id PK
        text player_id PK
        integer is_starter
        timestamp updated_at
    }

    WEEKLY_MATCHUP_POINTS {
        text league_id PK
        text season PK
        integer week PK
        integer roster_id PK
        text player_id PK
        real points
        integer started
        timestamp updated_at
    }

    WEEKLY_NFL_STATS {
        text season PK
        integer week PK
        text player_id PK
        real points
        real pass_yd
        real pass_td
        real pass_int
        real rush_yd
        real rush_td
        real rec
        real rec_yd
        real rec_td
        timestamp updated_at
    }
```

### Table Breakdown

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| `players` | `player_id` | Sleeper master player database (names, positions, NFL teams, injury tags). |
| `teams` | `(roster_id, league_id)` | League teams, owner names, wins, losses, total points for (PF) and against (PA). |
| `current_rosters` | `(league_id, roster_id, player_id)` | Current active ownership and starter/bench designation snapshot. |
| `weekly_matchup_points` | `(league_id, season, week, roster_id, player_id)` | Fantasy points scored per player within specific league weekly matchups. |
| `weekly_nfl_stats` | `(season, week, player_id)` | Global NFL player box scores (passing, rushing, receiving, PPR points). |
| `sync_metadata` | `key` | System and synchronization metadata (e.g. `last_sync` timestamp). |

---

## 📅 Multi-Season & Year Separation

To ensure previous seasons do not mix into future seasons:

1. **Season Partitioning**:
   - `weekly_matchup_points` and `weekly_nfl_stats` store the `season` string (e.g. `'2025'`, `'2026'`).
2. **Strict Query Isolation**:
   - [`src/db.py:load_league_data()`](file:///Users/jonas/Documents/GitHub/NFL-Fantasy-Dashboard/src/db.py) automatically queries [`get_active_season()`](file:///Users/jonas/Documents/GitHub/NFL-Fantasy-Dashboard/src/db.py#L90-L105) (or takes an explicit `season` parameter) and filters:
     ```sql
     WHERE m.league_id = ? AND m.season = ?
     ```
   - This ensures aggregates (PPG, std deviation, consistency tiers, positional ranks) are calculated **strictly from the current active season**.
3. **Rollover to Next Year**:
   - When a new season starts, simply update `LEAGUE_ID` in your local `.env`.
   - The sync automatically downloads the new season's data into the database alongside previous seasons without overwriting historical records.

---

## 🐳 Docker & Containerization

### Quick Start with Docker Compose

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Sunkarr/NFL-Fantasy-Dashboard.git
   cd NFL-Fantasy-Dashboard
   ```
2. **Create your private configuration file**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your credentials:
   ```dotenv
   LEAGUE_ID=your_sleeper_league_id
   TEAM_NAME=your_team_name
   TZ=Europe/Berlin
   SYNC_CRON=0,30 * * * *
   PORT=8501
   ```
3. **Launch the container**:
   ```bash
   docker compose up -d --build
   ```
4. **Access the Dashboard**:
   Open `http://localhost:8501` (or your Raspberry Pi's local address).

---

## 🍓 Raspberry Pi & Local Domain Setup (with Homebridge)

Running **Homebridge and this dashboard together on the same Raspberry Pi works seamlessly** without port collisions or needing to rename your Pi.

### Why there is NO conflict:
- **Homebridge UI** typically runs on **port 8581**.
- **HomeKit Bridge (HAP)** uses ports **51826+**.
- **Marimo Dashboard** runs on **port 8501**.

---

### Option A: Use your Pi's Existing Hostname (Zero-Config)
If your Pi's current hostname is `homebridge` (or `raspberrypi`), keep it as-is. You can immediately access both services:
- **Homebridge UI**: `http://homebridge.local:8581`
- **Fantasy Dashboard**: `http://homebridge.local:8501`

---

### Option B: Clean Domain without Port (`http://fantasy.home` or `http://fantasy.lan`)
If you want a dedicated URL without port numbers (like `http://fantasy.home`), keep your Pi's hostname unchanged and route via local DNS + reverse proxy:

1. **Add a DNS Rewrite on your Router / Pi-hole / Fritz!Box**:
   - `fantasy.home` (or `fantasy.lan`) $\rightarrow$ `<Raspberry-Pi-IP>` (e.g. `192.168.1.50`)
2. **Reverse Proxy with Nginx (on Port 80)**:
   Nginx routes incoming HTTP requests based on the domain:
   ```nginx
   # /etc/nginx/sites-available/fantasy
   server {
       listen 80;
       server_name fantasy.home fantasy.lan;

       location / {
           proxy_pass http://127.0.0.1:8501;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
       }
   }
   ```
   Now `http://fantasy.home` directly opens the Fantasy Dashboard!

---

### Option C: Avahi mDNS Alias (`fantasy.local` without renaming Pi)
You can broadcast `fantasy.local` alongside your existing hostname by publishing an Avahi CNAME/alias service:
- Your Pi will respond to both `http://<existing-hostname>.local` AND `http://fantasy.local:8501`.

---

## ⏰ Automated Data Sync (Every 30 Minutes: :00 & :30)

The service automatically keeps data fresh across environments (via Docker cron and in-process background scheduler):
- **Interval**: Runs every 30 minutes, exactly at **:00** and **:30** (`0,30 * * * *`).
- **Live UI Auto-Refresh**: The top bar includes a reactive auto-refresh widget (30s, 1m, 5m options and on-demand button), and the bottom-right badge displays the active version and exact last data fetch timestamp (`Last data fetch: HH:MM`).
- **Execution logs**: Output is saved to `data/cron.log`.
- **Manual Sync**: To trigger a manual sync anytime:
  ```bash
  python -m src.sync --mode incremental
  ```

---

## 🚀 Deployment & Configuration

### 1. Initial Setup on the Pi
```bash
git clone https://github.com/Sunkarr/NFL-Fantasy-Dashboard.git
cd NFL-Fantasy-Dashboard
cp .env.example .env
nano .env  # Add your LEAGUE_ID and TEAM_NAME
docker compose up -d --build
```

### 2. Updating the Dashboard
When you make changes on your Mac and push to GitHub:
```bash
git add .
git commit -m "Update dashboard"
git push origin main
```
On the Raspberry Pi:
```bash
cd ~/NFL-Fantasy-Dashboard
git pull
docker compose up -d --build
```
