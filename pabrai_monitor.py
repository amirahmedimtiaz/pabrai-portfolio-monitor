import os
import pandas as pd
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime

# Load configuration
load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

CSV_URL = "https://wagonsetf.filepoint.live/assets/data/FilepointWagonsETF.40P8.P8_ETF_Holdings.csv"
PREVIOUS_FILE = "previous_holdings.csv"
CURRENT_FILE = "latest_holdings.csv"

def download_csv(url, filename):
    print(f"Downloading {url}...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return True
    else:
        print(f"Failed to download: {response.status_code}")
        return False

def clean_currency(value):
    if pd.isna(value) or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        clean = value.replace('$', '').replace(',', '').replace('%', '').strip()
        if clean.startswith('(') and clean.endswith(')'):
            clean = '-' + clean[1:-1]
        try:
            return float(clean)
        except ValueError:
            return 0.0
    return 0.0

def compare_holdings(old_df, new_df):
    mapping = {
        'Ticker': 'StockTicker',
        'Company': 'SecurityName',
        'Shares Held': 'Shares',
        'Market Value': 'MarketValue'
    }
    old_df = old_df.rename(columns=mapping)
    new_df = new_df.rename(columns=mapping)

    old_df.set_index('StockTicker', inplace=True)
    new_df.set_index('StockTicker', inplace=True)

    summary = []

    # 1. New Positions
    new_tickers = new_df.index.difference(old_df.index)
    for ticker in new_tickers:
        row = new_df.loc[ticker]
        val = clean_currency(row['MarketValue'])
        shares = clean_currency(row['Shares'])
        summary.append(f'<span class="badge badge-new">NEW POSITION</span> <b>{row["SecurityName"]} ({ticker})</b>: {shares:,.0f} shares, Value: ${val:,.2f}')

    # 2. Exited Positions
    exited_tickers = old_df.index.difference(new_df.index)
    for ticker in exited_tickers:
        row = old_df.loc[ticker]
        summary.append(f'<span class="badge badge-exit">EXITED POSITION</span> <b>{row["SecurityName"]} ({ticker})</b>: Position closed.')

    # 3. Changes in existing positions
    common_tickers = old_df.index.intersection(new_df.index)
    for ticker in common_tickers:
        old_row = old_df.loc[ticker]
        new_row = new_df.loc[ticker]

        old_shares = clean_currency(old_row['Shares'])
        new_shares = clean_currency(new_row['Shares'])
        
        if old_shares != new_shares:
            diff = new_shares - old_shares
            if diff > 0:
                badge = '<span class="badge badge-increase">INCREASED</span>'
            else:
                badge = '<span class="badge badge-decrease">DECREASED</span>'
            
            summary.append(f'{badge} <b>{new_row["SecurityName"]} ({ticker})</b>: Shares changed from {old_shares:,.0f} to {new_shares:,.0f} (Delta: {diff:+,.0f})')

    return summary

def format_dataframe(df):
    formatted_df = df.copy()
    formatted_df['numeric_mv'] = formatted_df['MarketValue'].apply(clean_currency)
    formatted_df = formatted_df.sort_values(by='numeric_mv', ascending=False)
    
    cols_to_format = {
        'Shares': '{:,.0f}',
        'Price': '${:,.2f}',
        'MarketValue': '${:,.2f}',
        'NetAssets': '${:,.2f}'
    }
    
    for col, fmt in cols_to_format.items():
        if col in formatted_df.columns:
            formatted_df[col] = formatted_df[col].apply(lambda x: fmt.format(clean_currency(x)))
            
    return formatted_df.drop(columns=['numeric_mv'])

def send_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Gmail credentials not set in .env")
        return

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = RECIPIENT_EMAIL
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

def save_historical_snapshot(df):
    now = datetime.now()
    quarter = (now.month - 1) // 3 + 1
    year = now.year
    history_dir = "history"
    
    if not os.path.exists(history_dir):
        os.makedirs(history_dir)
    
    filename = f"{history_dir}/holdings_{year}_Q{quarter}.csv"
    
    # Only save if this quarter's file doesn't exist yet
    if not os.path.exists(filename):
        print(f"Saving new quarterly snapshot: {filename}")
        df.to_csv(filename, index=False)

def main():
    if not download_csv(CSV_URL, CURRENT_FILE):
        return

    new_df = pd.read_csv(CURRENT_FILE)
    
    # Save historical snapshot if needed
    save_historical_snapshot(new_df)
    
    if os.path.exists(PREVIOUS_FILE):
        old_df = pd.read_csv(PREVIOUS_FILE)
        changes = compare_holdings(old_df, new_df)
    else:
        changes = ["Initial run: No previous data to compare against."]
        old_df = pd.DataFrame(columns=new_df.columns)

    display_df = format_dataframe(new_df)
    date_str = datetime.now().strftime("%B %d, %Y")
    subject = f"📊 Pabrai Funds Portfolio Update - {date_str}"
    
    html_content = f"""
    <html>
    <head>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 20px; background-color: #f4f7f6; }}
        .container {{ max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        .header {{ border-bottom: 2px solid #2c3e50; padding-bottom: 10px; margin-bottom: 20px; }}
        h2 {{ color: #2c3e50; margin: 0; }}
        h3 {{ color: #34495e; border-left: 4px solid #3498db; padding-left: 10px; margin-top: 30px; }}
        .date {{ color: #7f8c8d; font-size: 0.9em; }}
        
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 0.75em; font-weight: bold; color: white; display: inline-block; margin-right: 10px; min-width: 80px; text-align: center; }}
        .badge-new {{ background-color: #27ae60; }}
        .badge-exit {{ background-color: #c0392b; }}
        .badge-increase {{ background-color: #2ecc71; }}
        .badge-decrease {{ background-color: #e67e22; }}
        
        .change-item {{ padding: 10px; border-bottom: 1px solid #eee; }}
        .change-item:last-child {{ border-bottom: none; }}
        
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; font-size: 0.85em; }}
        th {{ background-color: #2c3e50; color: white; padding: 12px 8px; text-align: left; }}
        td {{ border-bottom: 1px solid #ddd; padding: 10px 8px; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        tr:hover {{ background-color: #f1f1f1; }}
        
        .footer {{ margin-top: 40px; font-size: 0.8em; color: #95a5a6; text-align: center; border-top: 1px solid #eee; padding-top: 20px; }}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Pabrai Funds Portfolio Summary</h2>
                <div class="date">{date_str}</div>
            </div>
    """

    if changes:
        html_content += "<h3>🔄 Recent Portfolio Changes</h3>"
        for change in changes:
            html_content += f'<div class="change-item">{change}</div>'
    else:
        html_content += '<p style="color: #7f8c8d;">No changes detected in holdings or share counts since the last update.</p>'

    html_content += """
            <h3>📈 Full Portfolio Snapshot (Sorted by Market Value)</h3>
            <div style="overflow-x: auto;">
    """
    html_content += display_df.to_html(classes='table', index=False, escape=False)
    
    html_content += """
            </div>
            <div class="footer">
                Automated Portfolio Monitor • Data sourced from Wagons ETF
            </div>
        </div>
    </body>
    </html>
    """

    send_email(subject, html_content)
    os.replace(CURRENT_FILE, PREVIOUS_FILE)

if __name__ == "__main__":
    main()
