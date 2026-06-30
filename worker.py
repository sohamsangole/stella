from celery import Celery
from config import settings

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
    For now, we just print the payload to prove the queue works.
    """
    issue_url = webhook_payload.get("issue", {}).get("html_url")
    comment_body = webhook_payload.get("comment", {}).get("body")
    
    print(f"--- STELLA WORKER ACTIVATED ---")
    print(f"Received task for issue: {issue_url}")
    print(f"Comment was: {comment_body}")
    print(f"-------------------------------")