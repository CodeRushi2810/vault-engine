from .base import Strategy

class MACDCrossoverStrategy(Strategy):
    def __init__(self):
        super().__init__("MACDCrossover")

    def generate_signal(self, row):
        # Entry Condition: MACD crosses ABOVE the Signal line AND stock was recently Oversold (RSI < 30)
        macd_cross = row.get('MACD_Cross_Up', 0) == 1
        recently_oversold = row.get('RSI_Oversold_Recently', 0) == 1
        
        if macd_cross and recently_oversold:
            return 1, 0.05 # 1 means BUY, 5% emergency Stop Loss
            
        return 0, 0.05
