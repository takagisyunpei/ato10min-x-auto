import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parent

API = "https://api.buffer.com"

KEY = os.environ["BUFFER_API_KEY"]
CHANNEL = os.getenv("BUFFER_CHANNEL_NAME", "10min_kaiketsu")

REPO = os.environ["GITHUB_REPOSITORY"]
MEDIA_SHA = os.environ["MEDIA_SHA"]

NOTE_URL = os.getenv("NOTE_URL", "https://note.com/ato10fun").strip()

TIMES = {
    "quick_reply": "07:00",
    "ng_ok": "09:30",
    "question": "12:00",
    "three_steps": "15:00",
    "work_aruaru": "18:00",
    "save_card": "20:30",
    "note": "22:00",
}


def gql(query):
    r = requests.post(
        API,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
        },
        json={"query": query},
        timeout=45,
    )

    r.raise_for_status()

    data = r.json()

    if data.get("errors"):
        raise RuntimeError(data["errors"])

    return data.get("data", {})


def get_org_id():
    data = gql(
        """
        query {
          account {
            organizations {
              id
            }
          }
        }
        """
    )

    return data["account"]["organizations"][0]["id"]


def get_channel_id(org_id):
    data = gql(
        f"""
        query {{
          channels(input: {{ organizationId: "{org_id}" }}) {{
            id
            name
            displayName
            service
          }}
        }}
        """
    )

    wanted = CHANNEL.lower().lstrip("@")

    for channel in data.get("channels", []):
        names = {
            str(channel.get("name", "")).lower().lstrip("@"),
            str(channel.get("displayName", "")).lower().lstrip("@"),
        }

        if wanted in names:
            return channel["id"]

    raise RuntimeError(f"Buffer channel not found: {CHANNEL}")


def wait_public(url):
    for _ in range(15):
        try:
            r = requests.get(url, timeout=30)

            if r.status_code == 200 and r.content:
                return

        except Exception:
            pass

        time.sleep(5)

    raise RuntimeError(
        f"Image is not publicly reachable: {url}"
    )


def create_post(channel_id, text, due_at, image_url=None):
    text_json = json.dumps(
        text,
        ensure_ascii=False,
    )

    if image_url:
        image_json = json.dumps(
            image_url,
            ensure_ascii=False,
        )

        assets = f"""
        assets: [
          {{
            image: {{
              url: {image_json}
            }}
          }}
        ],
        """

    else:
        assets = ""

    query = f"""
    mutation {{
      createPost(
        input: {{
          text: {text_json},
          channelId: "{channel_id}",
          schedulingType: automatic,
          mode: customScheduled,
          dueAt: "{due_at}",
          {assets}
        }}
      ) {{
        ... on PostActionSuccess {{
          post {{
            id
            dueAt
          }}
        }}

        ... on MutationError {{
          message
        }}
      }}
    }}
    """

    result = gql(query).get(
        "createPost",
        {},
    )

    if result.get("message"):
        raise RuntimeError(
            result["message"]
        )

    return result.get("post")


def build_text(item):
    text = item["post_text"].strip()

    if item["slot"] == "note":
        if NOTE_URL:
            text += (
                "\n\n"
                "▼10分で読める解決策はこちら\n"
                + NOTE_URL
            )

    return text


def get_due_time(hhmm, now):
    hour, minute = map(
        int,
        hhmm.split(":"),
    )

    due_local = datetime(
        now.year,
        now.month,
        now.day,
        hour,
        minute,
        tzinfo=JST,
    )

    return due_local


def main():
    payload_path = ROOT / "daily_payload.json"

    payload = json.loads(
        payload_path.read_text(
            encoding="utf-8",
        )
    )

    today = datetime.now(
        JST
    ).date().isoformat()

    if payload.get("date") != today:
        raise RuntimeError(
            "daily_payload.json date mismatch"
        )

    org = get_org_id()
    channel = get_channel_id(org)

    now = datetime.now(JST)

    for item in payload["items"]:
        slot = item["slot"]

        if slot not in TIMES:
            raise ValueError(
                f"Unknown slot: {slot}"
            )

        hhmm = TIMES[slot]

        due_local = get_due_time(
            hhmm,
            now,
        )

        if due_local <= now:
            print(
                "SKIP",
                slot,
                hhmm,
            )

            continue

        due_utc = (
            due_local
            .astimezone(timezone.utc)
            .isoformat(
                timespec="seconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )

        image_url = None

        image_path = str(
            item.get(
                "image_path",
                "",
            )
        ).strip()

        if image_path:
            image_url = (
                f"https://raw.githubusercontent.com/"
                f"{REPO}/"
                f"{MEDIA_SHA}/"
                f"{image_path}"
            )

            wait_public(
                image_url
            )

        text = build_text(item)

        post = create_post(
            channel,
            text,
            due_utc,
            image_url,
        )

        print(
            "CREATED",
            slot,
            hhmm,
            post,
        )


if __name__ == "__main__":
    main()
