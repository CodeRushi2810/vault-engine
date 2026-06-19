import os
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, classification_report
import pickle
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.system_logger import setup_logger
logger = setup_logger("ml_trainer")



def train_model():
    log_file = os.path.join(BASE_DIR, "data", "trade_logs.csv")
    model_file = os.path.join(BASE_DIR, "backtesting", "bot_brain.pkl")
    
    if not os.path.exists(log_file):
        logger.info("No trade logs found. Run engine.py first!")
        return
        
    logger.info("Loading trade logs...")
    df = pd.read_csv(log_file)
    
    # Restrict ML data to strictly before May 2026 for Walk-Forward validation
    df['Entry_Time'] = pd.to_datetime(df['Entry_Time'])
    split_date = pd.to_datetime("2026-05-01")
    
    train_df = df[df['Entry_Time'] < split_date]
    test_df = df[(df['Entry_Time'] >= split_date) & (df['Entry_Time'] < '2026-05-01')]
    
    model_df = pd.concat([train_df, test_df])
    
    # The goal: Predict if a given Strategy applied to a given Setup will Win (1) or Lose (0).
    # The live bot will query this model for all available strategies and pick the one with the highest Win probability.
    
    drop_cols = ['Entry_Time', 'Exit_Time', 'Stock', 'Entry_Price', 'Exit_Price', 'PnL_Percent']
    model_df = model_df.drop(columns=[col for col in drop_cols if col in model_df.columns])
    
    # Drop rows with NaN features (e.g. initial 200 candles where SMA_200 is NaN)
    model_df = model_df.dropna()
    
    if model_df.empty:
        logger.info("Not enough data to train after dropping NaNs!")
        return
    
    # One-hot encode the Strategy names
    model_df = pd.get_dummies(model_df, columns=['Strategy'])
    
    y = model_df['Win_Loss']
    X = model_df.drop(columns=['Win_Loss'])
    
    # CRITICAL: We must split chronologically to prevent lookahead bias in training!
    # We train on the older trades (first 80%) and test on the unseen newer trades (last 20%).
    split_idx = int(len(model_df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    logger.info(f"Training XGBoost on {len(X_train)} historical trades...")
    
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.05,
        random_state=42
    )
    
    model.fit(X_train, y_train)
    
    logger.info("Evaluating model on unseen future trades...")
    preds = model.predict(X_test)
    
    logger.info(f"\nModel Accuracy on future trades: {accuracy_score(y_test, preds):.2%}")
    logger.info("\nDetailed Classification Report:")
    logger.info(classification_report(y_test, preds))
    
    # Save the model
    with open(model_file, 'wb') as f:
        # We save both the model and the expected feature columns
        pickle.dump({'model': model, 'features': X.columns.tolist()}, f)
        
    logger.info(f"\nModel successfully saved to {model_file}!")
    logger.info("Your Self-Training Trading Brain is ready!")

if __name__ == "__main__":
    train_model()
