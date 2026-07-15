import time
import jwt
import requests
from celery import Celery
from config import settings

def get_installation_token(installation_id: int) -> str:
    if not settings.github_app_id or not settings.github_private_key_path or not installation_id:
        return settings.github_token

    with open(settings.github_private_key_path, 'r') as f:
        private_key = f.read()

    payload = {
        'iat': int(time.time()) - 60,  # 60s past to account for clock skew
        'exp': int(time.time()) + (10 * 60),
        'iss': settings.github_app_id
    }
    encoded_jwt = jwt.encode(payload, private_key, algorithm='RS256')

    headers = {
        "Authorization": f"Bearer {encoded_jwt}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()['token']

# Initialize Celery
app = Celery(
    "stella",
    broker=settings.redis_url,
    backend=settings.redis_url
)

@app.task(name="process_stella_task")
def process_stella_task(webhook_payload: dict):
    """
    This is where Phase 2 will live. 
    For now, we just print the payload to prove the queue works and send an ack comment.
    """
    issue_url = webhook_payload.get("issue", {}).get("html_url")
    comments_url = webhook_payload.get("issue", {}).get("comments_url")
    comment_body = webhook_payload.get("comment", {}).get("body")
    installation_id = webhook_payload.get("installation", {}).get("id")
    
    print(f"--- STELLA WORKER ACTIVATED ---")
    print(f"Received task for issue: {issue_url}")
    print(f"Comment was: {comment_body}")
    print(f"-------------------------------")

    if comments_url:
        try:
            token = get_installation_token(installation_id)
        except Exception as e:
            print(f"Failed to get installation token: {e}")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        data = {
            "body": "Stella is on it! I'll start working on this issue right away."
        }
        try:
            response = requests.post(comments_url, headers=headers, json=data)
            response.raise_for_status()
            print("Successfully posted acknowledgment comment.")
        except requests.RequestException as e:
            print(f"Failed to post comment: {e}")