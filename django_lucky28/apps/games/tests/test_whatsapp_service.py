from django.test import SimpleTestCase
from unittest.mock import MagicMock, patch
from games.services.whatsapp import WhatsAppService
from twilio.base.exceptions import TwilioRestException

class MockGameRound:
    def __init__(self):
        self.game_no = "12345"
        self.winning_number = 7
        self.reward_type = "Big/Prime"

class WhatsAppServiceTest(SimpleTestCase):
    
    @patch.dict('os.environ', {
        'TWILIO_ACCOUNT_SID': 'AC_MOCK',
        'TWILIO_AUTH_TOKEN': 'AUTH_MOCK',
        'TWILIO_WHATSAPP_NUMBER': '+555555',
        'TWILIO_TEMPLATE_SID': 'HX_MOCK_TEMPLATE'
    })
    @patch('games.services.whatsapp.Client')
    def test_send_free_text_success(self, MockClient):
        # Setup Mock
        mock_messages = MagicMock()
        mock_messages.create.return_value.sid = "SM_MOCK_SUCCESS"
        MockClient.return_value.messages = mock_messages

        service = WhatsAppService()
        game = MockGameRound()
        
        result = service.send_winner_notification("123456789", game)
        
        self.assertTrue(result)
        # Verify create called once
        mock_messages.create.assert_called_once()
        args, kwargs = mock_messages.create.call_args
        self.assertIn("body", kwargs) # It was a body message, not content_sid
        self.assertNotIn("content_sid", kwargs)

    @patch.dict('os.environ', {
        'TWILIO_ACCOUNT_SID': 'AC_MOCK',
        'TWILIO_AUTH_TOKEN': 'AUTH_MOCK',
        'TWILIO_WHATSAPP_NUMBER': '+555555',
        'TWILIO_TEMPLATE_SID': 'HX_MOCK_TEMPLATE'
    })
    @patch('games.services.whatsapp.Client')
    def test_send_fallback_on_63016(self, MockClient):
        # Setup Mock to fail first time with 63016
        mock_messages = MagicMock()
        
        # Define side effect: First call raises 63016, Second call succeeds
        error_63016 = TwilioRestException(status=400, uri='/', msg='Outside window', code=63016)
        
        # We need check if 'body' is in kwargs to decide whether to fail or succeed
        def create_side_effect(*args, **kwargs):
            if 'body' in kwargs:
                # This is the free-text attempt
                raise error_63016
            else:
                # This is the template attempt
                match = MagicMock()
                match.sid = "SM_TEMPLATE_SUCCESS"
                return match

        mock_messages.create.side_effect = create_side_effect
        MockClient.return_value.messages = mock_messages

        service = WhatsAppService()
        game = MockGameRound()
        
        result = service.send_winner_notification("123456789", game)
        
        self.assertTrue(result)
        # Verify create called twice
        self.assertEqual(mock_messages.create.call_count, 2)
        
        # First call was text
        call1_kwargs = mock_messages.create.call_args_list[0].kwargs
        self.assertIn("body", call1_kwargs)
        
        # Second call was template
        call2_kwargs = mock_messages.create.call_args_list[1].kwargs
        self.assertIn("content_sid", call2_kwargs)
        self.assertEqual(call2_kwargs["content_sid"], "HX_MOCK_TEMPLATE")

