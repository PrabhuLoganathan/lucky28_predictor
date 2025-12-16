import os
import json
import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_number = os.environ.get("TWILIO_WHATSAPP_NUMBER")
        self.template_sid = os.environ.get("TWILIO_TEMPLATE_SID")
        
        if self.account_sid and self.auth_token:
            self.client = Client(self.account_sid, self.auth_token)
        else:
            self.client = None
    def send_message_raw(self, to_number, body_text):
        """
        Sends a raw text message. Does NOT handle fallback to template 
        (because templates are specific structures).
        Best effort delivery primarily for ALERTING within 24h window.
        """
        if not self.client or not self.from_number:
            return False

        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"
        
        if not self.from_number.startswith("whatsapp:"):
            from_ = f"whatsapp:{self.from_number}"
        else:
            from_ = self.from_number

        try:
            self.client.messages.create(
                from_=from_,
                to=to_number,
                body=body_text
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send raw WhatsApp: {e}")
            return False


    def send_winner_notification(self, to_number, game_round):
        """
        Sends a winner notification. 
        Tries free-text first. If valid user window (24h) check fails (Error 63016),
        falls back to Content Template.
        """
        if not self.client or not self.from_number:
            logger.error("Cannot send WhatsApp: Client or From Number missing.")
            return False

        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:{to_number}"
        
        if not self.from_number.startswith("whatsapp:"):
            from_ = f"whatsapp:{self.from_number}"
        else:
            from_ = self.from_number

        print(f"DEBUG: RAW TWILIO_WHATSAPP_NUMBER: {self.from_number}")
        print(f"DEBUG: Using From: {from_} To: {to_number}")
        print(f"DEBUG: AccountSID: {self.account_sid[:4]}...{self.account_sid[-4:] if self.account_sid else 'None'}")

        # Text Body for Free-form
        body_text = (
            f"🏆 *Winner Announced!* 🏆\n\n"
            f"Game: *{game_round.game_no}*\n"
            f"Result: *{game_round.winning_number}*\n"
            f"Reward: {game_round.reward_type}\n\n"
            f"Check dashboard for details!"
        )

        try:
            print(f"Attempting free-text WhatsApp to {to_number}")
            msg = self.client.messages.create(
                from_=from_,
                to=to_number,
                body=body_text
            )
            print(f"WhatsApp sent (Free-text). SID: {msg.sid}")
            return True

        except TwilioRestException as e:
            if e.code == 63016:
                print("Outside 24h window (Error 63016). Falling back to Template.")
                return self._send_template(to_number, from_, game_round)
            else:
                logger.error(f"Twilio Error: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error sending WhatsApp: {e}")
            return False

    def _send_template(self, to_number, from_number, game_round):
        if not self.template_sid:
            logger.error("No TWILIO_TEMPLATE_SID configured for fallback.")
            return False

        # Simplified variables - assumes template uses {{1}} for GameNo and {{2}} for Result
        # You might need to adjust based on ACTUAL template variable mapping
        variables = {
            "1": str(game_round.game_no),
            "2": str(game_round.winning_number)
        }

        try:
            msg = self.client.messages.create(
                from_=from_number,
                to=to_number,
                content_sid=self.template_sid,
                content_variables=json.dumps(variables)
            )
            logger.info(f"WhatsApp sent (Template). SID: {msg.sid}")
            return True
        except Exception as e:
            logger.error(f"Failed to send WhatsApp Template: {e}")
            return False
