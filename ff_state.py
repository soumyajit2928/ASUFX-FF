import json
import os
from datetime import datetime, timezone

import psycopg


def load_state(job_name, default):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT state FROM ff_job_state WHERE job_name = %s",
            (job_name,),
        ).fetchone()
    return row[0] if row else default


def save_state(job_name, state):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(
            """INSERT INTO ff_job_state (job_name, state, updated_at)
               VALUES (%s, %s::jsonb, %s)
               ON CONFLICT (job_name) DO UPDATE
               SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at""",
            (job_name, json.dumps(state), datetime.now(timezone.utc)),
        )
        conn.commit()
