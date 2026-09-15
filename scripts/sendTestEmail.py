import sys
import os

# Add the parent directory to the path so we can import core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.email_notifier import send_email_alert

if __name__ == "__main__":
    print("Sending BUY test email...")
    buy_message = "🟢 Bought 50 TATAPOWER at Rs 364.00"
    success_buy = send_email_alert(buy_message, "Marketing Template Test - BUY")
    print(f"Buy Email Sent: {success_buy}")

    print("\nSending SELL test email...")
    sell_message = "🟢 Sold 30 ABB at Rs 7,447.50 | Entry: Rs 7,200.00 | PnL: +Rs 7,425.00 (+10.5%)"
    success_sell = send_email_alert(sell_message, "Marketing Template Test - SELL")
    print(f"Sell Email Sent: {success_sell}")
    
    print("\nCheck your inbox!")
