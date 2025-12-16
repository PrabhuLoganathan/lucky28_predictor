import os
from twilio.rest import Client
from pathlib import Path
from dotenv import load_dotenv

def test_send():
    # Load .env
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_num = os.environ.get("TWILIO_WHATSAPP_NUMBER")
    to_num = os.environ.get("ADMIN_PHONE")

    print(f"Using SID: {sid}")
    print(f"Using From: {from_num}")
    print(f"Using To:   {to_num}")

    if not all([sid, token, from_num, to_num]):
        print("ERROR: Missing one or more variables.")
        return

    client = Client(sid, token)
    
    # Ensure whatsapp prefix
    if not from_num.startswith("whatsapp:"):
        from_num = f"whatsapp:{from_num}"
    if not to_num.startswith("whatsapp:"):
        to_num = f"whatsapp:{to_num}"

    try:
        msg = client.messages.create(
            body="Test Message from Lucky28",
            from_=from_num,
            to=to_num
        )
        print(f"SUCCESS! Message SID: {msg.sid}")
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    test_send()
