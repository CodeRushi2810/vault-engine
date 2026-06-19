from .macd_crossover import MACDCrossoverStrategy

def get_all_strategies():
    return [
        MACDCrossoverStrategy()
    ]
