import hmac
import hashlib
from fastapi import FastAPI, Request, HTTPException, Header
from stella.core.config import settings
from stella.core.worker import process_stella_task

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

def get_allowed_author_associations() -> set[str]:
    raw = getattr(settings, "allowed_author_associations", "OWNER,MEMBER,COLLABORATOR")
    if isinstance(raw, (set, list, tuple)):
        return {str(item).upper() for item in raw}
    return {item.strip().upper() for item in raw.split(",") if item.strip()}

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
        comment = payload.get("comment", {})
        comment_body = comment.get("body", "")
        is_bot = comment.get("user", {}).get("type") == "Bot"

        # 5. Trigger Stella if @coding-agent-stella is mentioned, it's a new comment, and not by a bot
        trigger_handle = f"@{getattr(settings, 'github_app_name', 'coding-agent-stella')}".lower()
        if (
            action == "created"
            and (trigger_handle in comment_body.lower() or "@coding-agent-stella" in comment_body.lower())
            and not is_bot
        ):
            sender = comment.get("user", {}).get("login", "unknown")
            author_association = str(comment.get("author_association", "UNKNOWN")).upper()
            issue_url = payload.get("issue", {}).get("html_url", "unknown")

            print(
                f"[Webhook] Received trigger mention from user '{sender}' "
                f"(Association: '{author_association}') on issue: {issue_url}"
            )

            # 6. Restrict triggers to authorized repository roles (DDoS / abuse prevention)
            allowed_associations = get_allowed_author_associations()
            if author_association not in allowed_associations:
                print(
                    f"[Webhook] REJECTED unauthorized trigger from user '{sender}' "
                    f"with association '{author_association}'"
                )
                return {
                    "status": "ignored",
                    "reason": "unauthorized_author_association",
                    "message": (
                        f"Unauthorized author association '{author_association}'. "
                        "Only repository maintainers can trigger Stella."
                    ),
                }

            print(
                f"[Webhook] AUTHORIZED trigger from user '{sender}' "
                f"({author_association}). Enqueuing task..."
            )
            # Push to Celery Queue
            process_stella_task.delay(payload)
            
            return {"status": "success", "message": "Stella is on it!"}

    # Ignore other events
    return {"status": "ignored", "message": "Not a Stella command."}

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "Stella"}