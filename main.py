import hmac
import hashlib
from fastapi import FastAPI, Request, HTTPException, Header
from config import settings
from worker import process_stella_task

app = FastAPI(title="Stella Webhook Server")

def verify_github_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify that the payload was sent from GitHub by validating SHA-256."""
    if not signature_header:
        return False
    
    hash_object = hmac.new(
        settings.github_webhook_secret.encode('utf-8'),
        msg=payload_body,
        digestmod=hashlib.sha256
    )
    expected_signature = "sha256=" + hash_object.hexdigest()
    
    return hmac.compare_digest(expected_signature, signature_header)

@app.post("/webhook/github")
async def github_webhook(request: Request, x_hub_signature_256: str = Header(default=None)):
    # 1. Get raw body
    payload_body = await request.body()
    
    # 2. Verify signature
    if not verify_github_signature(payload_body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Request signatures didn't match!")
    
    # 3. Parse JSON
    payload = await request.json()
    event = request.headers.get("X-GitHub-Event", "")

    # 4. Filter for Issue Comments
    if event == "issue_comment":
        action = payload.get("action")
        comment_body = payload.get("comment", {}).get("body", "")
        is_bot = payload.get("comment", {}).get("user", {}).get("type") == "Bot"

        # 5. Trigger Stella if @coding-agent-stella is mentioned, it's a new comment, and not by a bot
        if action == "created" and "@coding-agent-stella" in comment_body.lower() and not is_bot:
            
            # Push to Celery Queue
            process_stella_task.delay(payload)
            
            return {"status": "success", "message": "Stella is on it!"}

    # Ignore other events
    return {"status": "ignored", "message": "Not a Stella command."}

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "Stella"}