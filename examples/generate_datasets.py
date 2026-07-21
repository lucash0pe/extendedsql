"""Generate the demo sample datasets (deterministic).

Writes two small, self-contained CSVs into public/data/ for the website demo:
  - streams.csv  : music streaming plays (minutes per listener, region varies per play)
  - weather.csv  : daily weather readings (temp/humidity per city, seasonal by month)

Both mirror the shape ESQL likes: a few categorical grouping columns, numeric measures,
a categorical/temporal axis that cross-cuts a group (region / month-derived season), and a
boolean for WHERE. Run: uv run python examples/generate_datasets.py
"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "public" / "data"

rng = np.random.default_rng(42)


def _dates(n: int, start: date, end: date) -> list[date]:
    span = (end - start).days
    return [start + timedelta(days=int(d)) for d in rng.integers(0, span + 1, n)]


def make_streams(n: int = 2000) -> pd.DataFrame:
    listeners = ["Ada", "Ben", "Cy", "Dee", "Eli", "Fay", "Gus", "Hana"]
    genres = {
        "Nova": "Pop", "Riftwave": "Rock", "Blue Ember": "Jazz", "K.Low": "HipHop",
        "Marisol": "Classical", "Vantablack": "Rock", "Sol Fina": "Pop",
        "Echo Park": "HipHop", "The Larks": "Jazz", "Grův": "Pop",
    }
    artists = list(genres)
    regions = ["US", "UK", "EU", "JP"]

    artist = rng.choice(artists, n)
    rows = pd.DataFrame(
        {
            "listener": rng.choice(listeners, n),
            "artist": artist,
            "genre": [genres[a] for a in artist],
            "region": rng.choice(regions, n, p=[0.4, 0.25, 0.25, 0.1]),
            "minutes": rng.integers(1, 241, n),
            "premium": rng.random(n) < 0.42,
        }
    )
    d = _dates(n, date(2021, 1, 1), date(2023, 12, 31))
    rows["day"] = [x.day for x in d]
    rows["month"] = [x.month for x in d]
    rows["year"] = [x.year for x in d]
    rows["date"] = [x.isoformat() for x in d]
    return rows[["listener", "artist", "genre", "region", "minutes", "day", "month", "year", "date", "premium"]]


def make_weather(n: int = 2000) -> pd.DataFrame:
    city_region = {
        "Denver": "West", "Seattle": "West", "Austin": "South", "Miami": "South",
        "Boston": "East", "Newark": "East", "Chicago": "North", "Fargo": "North",
    }
    cities = list(city_region)
    station_of = {c: f"WX{ i:02d}" for i, c in enumerate(cities, start=1)}

    city = rng.choice(cities, n)
    d = _dates(n, date(2022, 1, 1), date(2023, 12, 31))
    month = np.array([x.month for x in d])
    # Seasonal temperature: cold in winter, hot in summer, plus per-reading noise.
    seasonal = 55 - 35 * np.cos((month - 1) / 12 * 2 * np.pi)
    temp = np.clip(np.round(seasonal + rng.normal(0, 8, n)).astype(int), -10, 110)

    rows = pd.DataFrame(
        {
            "station": [station_of[c] for c in city],
            "city": city,
            "region": [city_region[c] for c in city],
            "temp": temp,
            "humidity": rng.integers(10, 101, n),
            "rained": rng.random(n) < 0.3,
        }
    )
    rows["day"] = [x.day for x in d]
    rows["month"] = month
    rows["year"] = [x.year for x in d]
    rows["date"] = [x.isoformat() for x in d]
    return rows[["station", "city", "region", "temp", "humidity", "day", "month", "year", "date", "rained"]]


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, df in (("streams", make_streams()), ("weather", make_weather())):
        out = DATA / f"{name}.csv"
        df.to_csv(out, index=False)
        print(f"[ok] {name}: {len(df)} rows, {len(df.columns)} cols -> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
