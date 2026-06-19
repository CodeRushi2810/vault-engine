import pandas as pd
import pandas_ta as ta

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes technical indicators for a given DataFrame (OHLCV).
    CRITICALLY: Applies a strict .shift(1) to all computed features to prevent lookahead bias.
    The returned DataFrame will have the original columns plus the shifted feature columns.
    """
    if df.empty:
        return df

    # Ensure the dataframe is sorted by Timestamp
    df = df.sort_values('Timestamp').copy()
    
    # We will compute features into a separate dataframe, then shift it, then join.
    # This prevents accidentally shifting the OHLC prices themselves (which we need for execution at the open).
    features = pd.DataFrame(index=df.index)
    
    # 1. Moving Averages
    features['SMA_10'] = ta.sma(df['Close'], length=10)
    features['SMA_50'] = ta.sma(df['Close'], length=50)
    features['SMA_200'] = ta.sma(df['Close'], length=200)
    
    # 2. RSI
    features['RSI_14'] = ta.rsi(df['Close'], length=14)
    
    # 3. MACD
    macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd is not None:
        # Renaming columns for easier access
        macd.columns = ['MACD', 'MACD_Histogram', 'MACD_Signal']
        features = pd.concat([features, macd], axis=1)
        
        # Add Crossover booleans
        features['MACD_Cross_Up'] = ((features['MACD'] > features['MACD_Signal']) & (features['MACD'].shift(1) <= features['MACD_Signal'].shift(1))).astype(int)
        features['MACD_Cross_Down'] = ((features['MACD'] < features['MACD_Signal']) & (features['MACD'].shift(1) >= features['MACD_Signal'].shift(1))).astype(int)
        
    # 4. ATR (Volatility)
    features['ATR_14'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    features['ATR_Pct'] = (features['ATR_14'] * 2) / df['Close']
    
    # 5. Bollinger Bands
    bbands = ta.bbands(df['Close'], length=20, std=2)
    if bbands is not None:
        features['BB_Upper'] = bbands['BBU_20_2.0_2.0']
        features['BB_Lower'] = bbands['BBL_20_2.0_2.0']
        features['BB_Pct'] = bbands['BBP_20_2.0_2.0']
        
    # 6. Volume Features
    features['Volume_SMA_20'] = ta.sma(df['Volume'], length=20)
    features['Volume_Spike'] = df['Volume'] / features['Volume_SMA_20']
    
    # 7. Trend Distance
    features['Dist_SMA_50'] = (df['Close'] - features['SMA_50']) / df['Close']
    
    # 8. SuperTrend
    st = ta.supertrend(df['High'], df['Low'], df['Close'], length=7, multiplier=3.0)
    if st is not None:
        features['SuperTrend_Line'] = st['SUPERT_7_3.0']
        features['SuperTrend_Dir'] = st['SUPERTd_7_3.0']
        
    # 9. ADX (Trend Strength)
    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    if adx_df is not None:
        features['ADX_14'] = adx_df['ADX_14']
        features['RSI_Oversold_Recently'] = (features['RSI_14'].rolling(window=20).min() < 30).astype(int)
        
    # 10. Candlestick Patterns for Exit Logic
    is_red = (df['Close'] < df['Open']).astype(int)
    features['Two_Consecutive_Red'] = (is_red & is_red.shift(1).fillna(0).astype(int)).astype(int)
    
    # --- CRITICAL LOOKAHEAD BIAS PREVENTION ---
    # Shift all calculated features by 1.
    # A feature at index i now represents the indicator value computed entirely from data up to index i-1.
    shifted_features = features.shift(1)
    
    # Merge shifted features back into the main DataFrame
    df = pd.concat([df, shifted_features], axis=1)
    
    return df
