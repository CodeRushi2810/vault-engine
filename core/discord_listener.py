import discord
import os
import pandas as pd
import requests
from dotenv import load_dotenv
import asyncio
from datetime import datetime
import logging
from core.system_logger import setup_logger

logger = setup_logger("discord_bot")

# Route discord logs to system_logger
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.INFO)
for handler in discord_logger.handlers[:]:
    discord_logger.removeHandler(handler)
discord_logger.handlers = logger.handlers
discord_logger.propagate = False

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

def get_stock_name(symbol):
    return STOCK_NAMES.get(symbol, symbol)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

if not TOKEN:
    logger.error("DISCORD_BOT_TOKEN not found in .env. Bot will not start.")
    exit(1)

# Set up intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read commands

client = discord.Client(intents=intents)

def get_today_summary():
    """Reads the ledger and summarizes today's performance and open positions."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ledger_path = os.path.join(base_dir, 'data', 'paper_trade_logs.csv')
    
    if not os.path.exists(ledger_path):
        return discord.Embed(title="No Data", description="No trading history found. The bot hasn't executed any paper trades yet.", color=0x808080)
        
    try:
        df = pd.read_csv(ledger_path)
        if df.empty:
            return discord.Embed(title="No Data", description="Ledger is empty. No trades yet.", color=0x808080)
            
        # Convert times
        df['Entry_Time'] = pd.to_datetime(df['Entry_Time'])
        df['Exit_Time'] = pd.to_datetime(df['Exit_Time'])
        
        # Get today's realized PnL
        today = datetime.now().date()
        closed_today = df[(df['Status'] == 'CLOSED') & (df['Exit_Time'].dt.date == today)]
        realized_pnl = closed_today['PnL_Amount'].sum() if not closed_today.empty else 0
        wins = len(closed_today[closed_today['PnL_Amount'] > 0])
        losses = len(closed_today[closed_today['PnL_Amount'] <= 0])
        
        # Get open positions
        open_positions = df[df['Status'] == 'OPEN']
        open_count = len(open_positions)
        
        # Fetch Live Prices to match Dashboard
        live_prices = {}
        try:
            res = requests.get("http://localhost:8000/api/live-prices", timeout=2)
            if res.status_code == 200:
                data = res.json()
                for stock, info in data.items():
                    if 'ltp' in info:
                        live_prices[stock] = info['ltp']
        except:
            pass
            
        unrealized_pnl = 0
        total_invested = open_positions['Cost_Basis'].sum() if not open_positions.empty else 0
        
        # Recalculate PnL dynamically using live market prices
        if not open_positions.empty:
            open_positions = open_positions.copy()
            for idx, row in open_positions.iterrows():
                stock = row['Stock']
                entry_price = row['Entry_Price']
                shares = row['Shares']
                
                # Use live price if available, else fallback to what was saved in the CSV
                current_price = live_prices.get(stock, row.get('Exit_Price', entry_price))
                if pd.isna(current_price) or current_price == 0:
                    current_price = entry_price
                    
                u_pnl = (current_price - entry_price) * shares
                open_positions.at[idx, 'PnL_Amount'] = u_pnl
                unrealized_pnl += u_pnl
                
                # Update PnL_Percent
                if row['Cost_Basis'] > 0:
                    open_positions.at[idx, 'PnL_Percent'] = (u_pnl / row['Cost_Basis']) * 100
        
        # Build Embed
        embed_color = 0x22c55e if unrealized_pnl >= 0 else 0xef4444
        embed = discord.Embed(title=f"📊 DAILY REPORT: {today.strftime('%d %b %Y')}", color=embed_color)
        
        # Daily Performance Section
        pnl_icon = "🟢" if realized_pnl >= 0 else "🔴"
        pnl_str = f"+Rs {realized_pnl:,.2f}" if realized_pnl >= 0 else f"-Rs {abs(realized_pnl):,.2f}"
        
        if not closed_today.empty:
            chunks = []
            current_chunk = ""
            for _, row in closed_today.iterrows():
                name = get_stock_name(row['Stock'])
                c_pnl = row['PnL_Amount']
                c_pct = row['PnL_Percent']
                c_icon = "🟩" if c_pnl >= 0 else "🟥"
                c_pnl_str = f"+Rs {c_pnl:,.2f}" if c_pnl >= 0 else f"-Rs {abs(c_pnl):,.2f}"
                c_pct_str = f"+{c_pct:.2f}%" if c_pct >= 0 else f"{c_pct:.2f}%"
                entry_str = f"**{name}**: {row['Shares']} shares | Entry: Rs {row['Entry_Price']:,.2f} | Exit: Rs {row['Exit_Price']:,.2f}\n└ Profit: {c_icon} {c_pnl_str} ({c_pct_str})\n\n"
                
                if len(current_chunk) + len(entry_str) > 1024:
                    chunks.append(current_chunk)
                    current_chunk = entry_str
                else:
                    current_chunk += entry_str
            if current_chunk:
                chunks.append(current_chunk)
                
            for i, chunk in enumerate(chunks):
                if i == 0:
                    title = f"Trades Closed Today ({wins} W / {losses} L)"
                    val = f"**Realized PnL:** {pnl_icon} {pnl_str}\n\n{chunk}"
                    if len(val) > 1024:
                        embed.add_field(name=title, value=f"**Realized PnL:** {pnl_icon} {pnl_str}\n\n", inline=False)
                        embed.add_field(name="Trades Closed (Cont.)", value=chunk, inline=False)
                    else:
                        embed.add_field(name=title, value=val, inline=False)
                else:
                    embed.add_field(name="Trades Closed (Cont.)", value=chunk, inline=False)
        else:
            embed.add_field(name=f"Trades Closed Today (0 W / 0 L)", value=f"**Realized PnL:** {pnl_icon} {pnl_str}\n\nNo trades closed today.", inline=False)
        
        # Calculate Uninvested Wallet Balance
        all_time_realized = df[df['Status'] == 'CLOSED']['PnL_Amount'].sum() if not df[df['Status'] == 'CLOSED'].empty else 0
        wallet_balance = 1000000 + all_time_realized - total_invested
        
        # Portfolio Section
        u_pnl_icon = "🟢" if unrealized_pnl >= 0 else "🔴"
        u_pnl_str = f"+Rs {unrealized_pnl:,.2f}" if unrealized_pnl >= 0 else f"-Rs {abs(unrealized_pnl):,.2f}"
        u_pnl_pct = (unrealized_pnl / total_invested * 100) if total_invested > 0 else 0
        
        port_str = f"> **Available Cash:** Rs {wallet_balance:,.2f}\n> **Capital Deployed:** Rs {total_invested:,.2f}\n> **Unrealized PnL:** {u_pnl_icon} {u_pnl_str} ({u_pnl_pct:.2f}%)"
        embed.add_field(name="💼 PORTFOLIO STATUS", value=port_str, inline=False)
        
        # Open Positions Details
        if open_count > 0:
            chunks = []
            current_chunk = ""
            for _, row in open_positions.iterrows():
                name = get_stock_name(row['Stock'])
                u_pnl = row['PnL_Amount']
                u_pnl_str = f"+Rs {u_pnl:,.2f}" if u_pnl >= 0 else f"-Rs {abs(u_pnl):,.2f}"
                u_icon = "🟩" if u_pnl >= 0 else "🟥"
                entry_str = f"**{name}**: {row['Shares']} shares @ Rs {row['Entry_Price']:,.2f}\n└ PnL: {u_icon} {u_pnl_str} ({row['PnL_Percent']:.2f}%)\n\n"
                
                if len(current_chunk) + len(entry_str) > 1024:
                    chunks.append(current_chunk)
                    current_chunk = entry_str
                else:
                    current_chunk += entry_str
            if current_chunk:
                chunks.append(current_chunk)
                
            for i, chunk in enumerate(chunks):
                title = f"📂 OPEN POSITIONS ({open_count})" if i == 0 else "📂 OPEN POSITIONS (Cont.)"
                embed.add_field(name=title, value=chunk, inline=False)
        else:
            embed.add_field(name=f"📂 OPEN POSITIONS (0)", value="None", inline=False)
            
        return embed
        
    except Exception as e:
        return discord.Embed(title="Error", description=f"Error reading ledger: {str(e)}", color=0xff0000)

from discord import app_commands

tree = app_commands.CommandTree(client)

@tree.command(name="summary", description="Get a detailed daily portfolio summary and open positions.")
async def summary_command(interaction: discord.Interaction):
    # Slash commands require you to acknowledge the interaction within 3 seconds.
    # Deferring gives us time to calculate the data.
    await interaction.response.defer()
    response_embed = get_today_summary()
    await interaction.followup.send(embed=response_embed)

@tree.command(name="ping", description="Check if the trading engine is online.")
async def ping_command(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! AETHER execution engine is online and monitoring.")

@client.event
async def on_ready():
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    try:
        synced = await tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

if __name__ == '__main__':
    client.run(TOKEN, log_handler=None)
