import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

API_URL = "https://api.buffer.com"
JST = ZoneInfo("Asia/Tokyo")
POST_TIMES = ["07:30", "09:00", "11:00", "12:30", "15:00", "18:00", "20:00", "22:00"]

API_KEY = os.getenv("BUFFER_API_KEY", "").strip()
CHANNEL_NAME = os.getenv("BUFFER_CHANNEL_NAME", "10min_kaiketsu").strip()
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

if not API_KEY:
    print("ERROR: BUFFER_API_KEY is not set.")
    sys.exit(1)

def graphql(query: str):
    body = json.dumps({"query": query}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Buffer HTTP {e.code}: {detail}") from e

    if payload.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {payload['errors']}")
    return payload.get("data") or {}

def get_organization_id():
    data = graphql(
        """
        query GetOrganizations {
          account {
            organizations {
              id
              name
            }
          }
        }
        """
    )
    orgs = ((data.get("account") or {}).get("organizations") or [])
    if not orgs:
        raise RuntimeError("No Buffer organization found.")
    return orgs[0]["id"]

def get_target_channel(org_id: str):
    query = f'''
    query GetChannels {{
      channels(input: {{ organizationId: "{org_id}" }}) {{
        id
        name
        displayName
        service
        isQueuePaused
      }}
    }}
    '''
    data = graphql(query)
    channels = data.get("channels") or []
    wanted = CHANNEL_NAME.lower().lstrip("@")

    exact = []
    x_channels = []
    for channel in channels:
        service = str(channel.get("service", "")).lower()
        if service in ("twitter", "x"):
            x_channels.append(channel)
        names = {
            str(channel.get("name", "")).lower().lstrip("@"),
            str(channel.get("displayName", "")).lower().lstrip("@"),
        }
        if wanted in names:
            exact.append(channel)

    if exact:
        return exact[0]
    if len(x_channels) == 1:
        return x_channels[0]

    summary = [(c.get("name"), c.get("displayName"), c.get("service")) for c in channels]
    raise RuntimeError(f"Target X channel not found. Available channels: {summary}")

def get_scheduled_posts(org_id: str, channel_id: str):
    query = f'''
    query GetScheduledPosts {{
      posts(
        input: {{
          organizationId: "{org_id}",
          sort: [
            {{ field: dueAt, direction: asc }},
            {{ field: createdAt, direction: asc }}
          ],
          filter: {{
            status: scheduled,
            channelIds: ["{channel_id}"]
          }}
        }}
      ) {{
        edges {{
          node {{
            id
            text
            dueAt
            channelId
          }}
        }}
      }}
    }}
    '''
    data = graphql(query)
    edges = ((data.get("posts") or {}).get("edges") or [])
    return [edge.get("node") or {} for edge in edges]

def gql_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

def create_post(channel_id: str, text: str, due_at_utc: str):
    query = f'''
    mutation CreatePost {{
      createPost(input: {{
        text: {gql_string(text)},
        channelId: "{channel_id}",
        schedulingType: automatic,
        mode: customScheduled,
        dueAt: "{due_at_utc}"
      }}) {{
        ... on PostActionSuccess {{
          post {{
            id
            text
            dueAt
          }}
        }}
        ... on MutationError {{
          message
        }}
      }}
    }}
    '''
    data = graphql(query)
    result = data.get("createPost") or {}
    if result.get("message"):
        raise RuntimeError(f"Buffer rejected the post: {result['message']}")
    post = result.get("post")
    if not post:
        raise RuntimeError(f"Unexpected Buffer response: {result}")
    return post

def load_content_bank():
    with open("content_bank.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    posts = data.get("posts") or []
    if len(posts) < 8:
        raise RuntimeError("content_bank.json must contain at least 8 posts.")
    return posts

def select_eight(posts, target_date):
    start = (target_date.toordinal() * 8) % len(posts)
    return [posts[(start + i) % len(posts)] for i in range(8)]

def main():
    now = datetime.now(JST)
    org_id = get_organization_id()
    channel = get_target_channel(org_id)

    if channel.get("isQueuePaused"):
        raise RuntimeError("Buffer queue is paused for the target X channel.")

    scheduled = get_scheduled_posts(org_id, channel["id"])
    existing_due = {str(post.get("dueAt")) for post in scheduled}

    selected = select_eight(load_content_bank(), now.date())
    created = 0

    for idx, hhmm in enumerate(POST_TIMES):
        hour, minute = map(int, hhmm.split(":"))
        local_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if local_dt <= now:
            print(f"SKIP past slot: {hhmm}")
            continue

        due_at = (
            local_dt.astimezone(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        if due_at in existing_due:
            print(f"SKIP already scheduled: {hhmm}")
            continue

        text = selected[idx]["text"].strip()
        if not text:
            print(f"SKIP blank content: {hhmm}")
            continue

        print(f"{'DRY RUN' if DRY_RUN else 'CREATE'} {hhmm}: {text[:55]!r}")
        if not DRY_RUN:
            post = create_post(channel["id"], text, due_at)
            print(f"  -> created {post.get('id')} dueAt={post.get('dueAt')}")
        created += 1

    print(f"DONE channel={channel.get('name')} created={created}")

if __name__ == "__main__":
    main()
