import os
import requests
from dotenv import load_dotenv
from core.system_logger import setup_logger

logger = setup_logger('discord')

def send_discord_message(message):
    load_dotenv()
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

    if not DISCORD_WEBHOOK_URL:
        logger.error('Discord Webhook URL not found in .env')
        return False

    # Discord doesn't parse HTML tags natively in basic text payloads. 
    # We strip out basic HTML bold tags and replace them with Markdown **
    message = message.replace('<b>', '**').replace('</b>', '**')
    message = message.replace('<i>', '*').replace('</i>', '*')

    payload = {
        'content': message
    }
    
    try:
        from core.agent_state import append_agent_status, update_agent_status
        append_agent_status("DiscordBot", f"Transmitted: {message}")
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        # Discord returns 204 No Content on success
        if response.status_code in [200, 204]:
            logger.info('Discord message sent successfully!')
            return True
        else:
            logger.error(f'Failed to send Discord message: {response.text}')
            return False
    except Exception as e:
        logger.error(f'Error sending Discord message: {e}')
        return False
