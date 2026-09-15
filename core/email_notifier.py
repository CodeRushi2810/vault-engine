import os
import smtplib
import re
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime

def generate_html_template(message):
    is_buy = "Bought" in message
    is_sell = "Sold" in message
    
    clean_msg = message.replace("**", "").replace("*", "")
    
    # Defaults
    action = "ALERT"
    theme_color = "#3b82f6"
    text_color = "#3b82f6"
    bg_color = "#101a2d"
    badge_bg = "#f8fcfa"
    badge_border = "#dcefe7"
    badge_text = "#477366"
    title_start = "You've received an "
    title_highlight = "alert."
    subtitle = "Your system has processed a new event."
    banner_title = "Vault Trading"
    banner_subtitle = "Automated execution log."
    
    stock_sym = "UNKNOWN"
    stock_name = "Unknown Stock"
    qty = "0"
    price = "0.00"
    total_val = 0.0
    total = "0.00"
    brokerage = "0.00"
    net_total = "0.00"
    hero_image = "" # Requires a hosted image URL in a real production system
    stock_logo = "https://logo.clearbit.com/groww.in"
    
    # Simple mapping for stock name/logos
    STOCK_NAMES = {
        "VOLTAS": "Voltas", "GVT&D": "GE T&D India", "JUBLFOOD": "Jubilant FoodWorks", 
        "ANANTRAJ": "Anant Raj", "BBOX": "Black Box", "CGPOWER": "CG Power", 
        "EICHERMOT": "Eicher Motors", "HFCL": "HFCL Ltd", "JBMA": "JBM Auto", 
        "MTARTECH": "MTAR Tech", "RELIANCE": "Reliance", "TATAPOWER": "Tata Power",
        "ABB": "ABB India"
    }
    
    # Try regex parsing: "Bought 10 VOLTAS at Rs 1,337.42"
    match = re.search(r'(Bought|Sold) (\d+) ([A-Za-z0-9&]+) at Rs ([\d,.]+)', clean_msg)
    if match:
        qty = match.group(2)
        stock_sym = match.group(3)
        stock_name = STOCK_NAMES.get(stock_sym, stock_sym)
        
        # Use Exact Github URLs
        stock_logo = f"https://raw.githubusercontent.com/CodeRushi2810/Vault-Assets/refs/heads/main/Vault%20Assets/logos/{stock_sym}.webp"
        
        price_str = match.group(4).replace(',', '')
        total_val = float(qty) * float(price_str)
        
        price = f"₹{float(price_str):,.2f}"
        total = f"₹{total_val:,.2f}"
        
    # Grid Variables
    lbl_price = "Price"
    val_price = "0.00"
    lbl_order_type = "Order Type"
    val_order_type = "Unknown"
    lbl_total = "Total"
    val_total = "0.00"
    r1_c4_display = "table-cell"
    row2_display = "none"
    lbl_r2 = ""
    val_r2 = ""
    profit_color = "inherit"
    row3_display = "none"
    val_total_buy = "0.00"
    val_total_sell = "0.00"
        
    if is_buy:
        action = "BUY"
        theme_color = "#1a0b2e" # Luxury Navy/Purple
        text_color = "#1a0b2e"
        bg_color = "#101a2d" 
        
        # New Image Assets
        hero_banner = "https://raw.githubusercontent.com/CodeRushi2810/Vault-Assets/refs/heads/main/Vault%20Assets/banners/buy_hero_banner.jpg"
        
        lbl_price = "Order Price"
        val_price = price
        lbl_order_type = "Order Type"
        val_order_type = "Market Order"
        lbl_total = "Amount Invested"
        val_total = total
        r1_c4_display = "table-cell"
        row2_display = "none"
        row3_display = "none"
            
    elif is_sell:
        action = "SELL"
        theme_color = "#0f2e21" # Luxury Emerald Green
        text_color = "#0f2e21"
        bg_color = "#1a0f0f" 
        
        # New Image Assets
        hero_banner = "https://raw.githubusercontent.com/CodeRushi2810/Vault-Assets/refs/heads/main/Vault%20Assets/banners/sell_hero_banner.jpg"
        
        # Parse PnL and Entry
        entry_price = "₹0.00"
        pnl = "₹0.00"
        total_buy = "₹0.00"
        
        entry_match = re.search(r'Entry: Rs ([\d,.]+)', clean_msg)
        pnl_match = re.search(r'PnL: ([+-]?Rs [\d,.]+ \([+-]?[\d.]+\%\))', clean_msg)
        
        if entry_match:
            ep = float(entry_match.group(1).replace(',', ''))
            entry_price = f"₹{ep:,.2f}"
            total_buy = f"₹{(float(qty) * ep):,.2f}"
            
        if pnl_match:
            pnl = pnl_match.group(1).replace('Rs ', '₹')
            
        lbl_price = "Buy Price"
        val_price = entry_price
        lbl_order_type = "Sell Price"
        val_order_type = price
        
        r1_c4_display = "none"
        row2_display = "block"
        lbl_r2 = "Profit Booked"
        val_r2 = pnl
        profit_color = "#12b886" # Success Green
        row3_display = "block"
        val_total_buy = total_buy
        val_total_sell = total
            
    timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")
    current_year = str(datetime.now().year)
    tx_id = f"BVLT-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4().hex)[:5].upper()}"
    
    template_path = os.path.join(os.path.dirname(__file__), 'email_template.html')
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception as e:
        print(f"Error reading HTML template: {e}")
        return clean_msg 
        
    html = html.replace('{{ACTION}}', action)
    html = html.replace('{{THEME_COLOR}}', theme_color)
    html = html.replace('{{TEXT_COLOR}}', text_color)
    html = html.replace('{{BG_COLOR}}', bg_color)
    html = html.replace('{{BADGE_BG}}', badge_bg)
    html = html.replace('{{BADGE_BORDER}}', badge_border)
    html = html.replace('{{BADGE_TEXT}}', badge_text)
    html = html.replace('{{STOCK_SYM}}', stock_sym)
    html = html.replace('{{STOCK_NAME}}', stock_name)
    html = html.replace('{{STOCK_LOGO}}', stock_logo)
    html = html.replace('{{HERO_BANNER}}', hero_banner)
    html = html.replace('{{QTY}}', qty)
    html = html.replace('{{LBL_PRICE}}', lbl_price)
    html = html.replace('{{VAL_PRICE}}', val_price)
    html = html.replace('{{LBL_ORDER_TYPE}}', lbl_order_type)
    html = html.replace('{{VAL_ORDER_TYPE}}', val_order_type)
    html = html.replace('{{LBL_TOTAL}}', lbl_total)
    html = html.replace('{{VAL_TOTAL}}', val_total)
    html = html.replace('{{R1_C4_DISPLAY}}', r1_c4_display)
    html = html.replace('{{ROW2_DISPLAY}}', row2_display)
    html = html.replace('{{LBL_R2}}', lbl_r2)
    html = html.replace('{{VAL_R2}}', val_r2)
    html = html.replace('{{PROFIT_COLOR}}', profit_color)
    html = html.replace('{{ROW3_DISPLAY}}', row3_display)
    html = html.replace('{{VAL_TOTAL_BUY}}', val_total_buy)
    html = html.replace('{{VAL_TOTAL_SELL}}', val_total_sell)
    html = html.replace('{{TIMESTAMP}}', timestamp)
    html = html.replace('{{TX_ID}}', tx_id)
    html = html.replace('{{YEAR}}', current_year)
    
    return html

def send_email_alert(message, subject="Vault Trading Alert"):
    load_dotenv()
    SENDER_EMAIL = os.environ.get("EMAIL_SENDER")
    SENDER_PASSWORD = os.environ.get("EMAIL_PASSWORD")
    RECEIVER_EMAIL = os.environ.get("EMAIL_RECEIVER")
    
    if not SENDER_EMAIL or not SENDER_PASSWORD or not RECEIVER_EMAIL:
        return False
        
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = subject
        
        # Attach plain text fallback
        msg.attach(MIMEText(message, 'plain'))
        
        # Attach rich HTML version
        html_content = generate_html_template(message)
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email alert: {e}")
        return False
