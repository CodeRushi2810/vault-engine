class Strategy:
    def __init__(self, name):
        self.name = name

    def generate_signal(self, current_candle) -> tuple[int, float]:
        """
        Takes the current row (which includes shifted features).
        Returns: (Direction, TSL_Pct).
        Direction: 1 for BUY, -1 for SELL, 0 for HOLD.
        TSL_Pct: Trailing Stop Loss percentage (e.g., 0.03 for 3%). If direction is not 1, this can be 0.0.
        """
        raise NotImplementedError
