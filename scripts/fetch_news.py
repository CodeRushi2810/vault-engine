import os
import json
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import google.generativeai as genai

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.config import STOCKS

load_dotenv(os.path.join(BASE_DIR, '.env'))
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("GEMINI_API_KEY is not set. Please set it in your .env file.")
    sys.exit(1)

genai.configure(api_key=api_key)

def get_stock_name(symbol):
    STOCK_NAMES = {
      'ANANTRAJ': 'Anant Raj',
      'BBOX': 'Black Box',
      'CGPOWER': 'CG Power & Inds',
      'EICHERMOT': 'Eicher Motors',
      'HFCL': 'HFCL Ltd',
      'JBMA': 'JBM Auto',
      'MTARTECH': 'MTAR Technologies',
      'NETWEB': 'Netweb Technologies',
      'POWERINDIA': 'Hitachi Energy India',
      'SCHNEIDER': 'Schneider Electric',
      'WAAREEENER': 'Waaree Energies',
      'INFY': 'Infosys',
      'TRENT': 'Trent',
      'SBIN': 'State Bank Of India',
      'JUBLFOOD': 'Jubilant FoodWorks'
    }
    return STOCK_NAMES.get(symbol, symbol)

def fetch_google_news(query):
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        news_items = []
        for item in root.findall('.//item')[:3]: # top 3
            title = item.find('title').text if item.find('title') is not None else ''
            link = item.find('link').text if item.find('link') is not None else ''
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
            
            # Google News RSS pubDate format is typically: 'Thu, 18 Jun 2026 10:23:00 GMT'
            # We can simplify it slightly for UI (e.g., '18 Jun 2026')
            if pub_date:
                try:
                    parts = pub_date.split()
                    # extract '18 Jun 2026' from 'Thu, 18 Jun 2026 ...'
                    if len(parts) >= 4:
                        pub_date = f"{parts[1]} {parts[2]} {parts[3]}"
                except Exception:
                    pass

            if title:
                news_items.append({'title': title, 'url': link, 'date': pub_date})
        return news_items
    except Exception as e:
        print(f"RSS error for {query}: {e}")
        return []

def main():
    print("Fetching raw news from Google News RSS for all stocks...")
    
    all_news = {}
    news_data_output = {}
    
    for stock in STOCKS:
        friendly = get_stock_name(stock)
        print(f"  -> Fetching news for {friendly} ({stock})...")
        
        results = fetch_google_news(f"{friendly} stock India")
        stock_news = []
        links = []
        
        for n in results:
            stock_news.append(f"Title: {n['title']}")
            links.append(n)
            
        all_news[stock] = stock_news
        news_data_output[stock] = {
            "sentiment": "Neutral",
            "analysis": "No significant news found today.",
            "links": links
        }

    print("\nConstructing single consolidated prompt for Gemini...")
    prompt = "You are a professional financial analyst. Below is the latest news headlines for several Indian stocks. For each stock, read the headlines and provide a brief 2-3 sentence analysis of whether the overall sentiment is bullish, bearish, or neutral for its stock price.\n\n"
    
    stocks_with_news = []
    for stock, headlines in all_news.items():
        if headlines:
            prompt += f"STOCK: {get_stock_name(stock)} (NSE: {stock})\n"
            prompt += "\n".join(headlines) + "\n\n"
            stocks_with_news.append(stock)
            
    prompt += "You MUST return the response strictly as a raw JSON dictionary where the keys are the NSE symbols, and the values are objects with 'sentiment' (must be exactly 'Bullish', 'Bearish', or 'Neutral') and 'analysis'. Do NOT include markdown blocks or backticks. Example format:\n"
    prompt += '{\n  "RELIANCE": {"sentiment": "Bullish", "analysis": "..."},\n  "INFY": {"sentiment": "Bearish", "analysis": "..."}\n}'

    if stocks_with_news:
        print("Calling Gemini 1.5 API (1 single request for all stocks)...")
        try:
            # We use gemini-pro-latest as the free tier limit is separate and much larger
            model = genai.GenerativeModel('gemini-pro-latest')
            response = model.generate_content(prompt)
            clean_json = response.text.replace('```json', '').replace('```', '').strip()
            gemini_results = json.loads(clean_json)
            
            for stock, result in gemini_results.items():
                if stock in news_data_output:
                    news_data_output[stock]['sentiment'] = result.get('sentiment', 'Neutral')
                    news_data_output[stock]['analysis'] = result.get('analysis', '')
                    print(f"[{stock}] Analysis Complete: {news_data_output[stock]['sentiment']}")
        except Exception as e:
            print(f"Gemini API failed: {e}")

    out_path = os.path.join(BASE_DIR, "dashboard", "public", "news_data.json")
    with open(out_path, 'w') as f:
        json.dump(news_data_output, f, indent=4)
    print(f"\nSuccessfully saved consolidated news data to {out_path}")

if __name__ == "__main__":
    main()
