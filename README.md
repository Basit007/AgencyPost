# AgencyPost – Local Social Media Auto-Poster

Fully local background service that watches client folders and posts fully-edited videos to **YouTube, Facebook, Instagram, and TikTok**.

## Features

- Drop a video into `clients/<client_slug>/ready/` → automatically queued
- Optional scheduling via `.schedule` sidecar file (ISO datetime UTC)
- SQLite database (no external DB needed)
- Pure background service + logs (no web UI required)
- Designed for agencies managing many doctor/client accounts

## Quick Start

```bash
# 1. Clone / download this repo
cd AgencyPost

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create a client folder
mkdir -p clients/dr_smith/ready
mkdir -p clients/dr_smith/posted
mkdir -p clients/dr_smith/failed

# 5. Run the service
python main.py
```

## How to Schedule a Post

Next to your video file create a text file with the same name + `.schedule`:

```
video.mp4
video.schedule   ← content example: 2026-09-30T14:00:00
```

The time must be in UTC (ISO format).

## Captions (optional)

Create `clients/dr_smith/captions.json`:

```json
{
  "title": "Default title",
  "caption": "Default caption with #hashtags",
  "youtube": {
    "title": "YouTube specific title",
    "caption": "YouTube description"
  },
  "instagram": {
    "caption": "Instagram caption"
  }
}
```

## Connecting Accounts

Currently the poster functions are stubs.  
You need to:

1. Create developer apps on Google, Meta, and TikTok
2. Run OAuth flows and store the tokens in the `accounts` table
3. Implement the real upload logic inside `posters/*.py`

I can provide complete working upload + OAuth helper code for each platform on request.

## Logs

All activity is written to `logs/posting.log` and also printed to the console.

## License

MIT – use freely for your agency.
