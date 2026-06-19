import os
import re

files_to_refactor = {
    'bootup.py': 'bootup',
    'core/live_feed_server.py': 'live_feed',
    'core/run_pipeline.py': 'pipeline',
    'backtesting/engine.py': 'bt_engine',
    'backtesting/ml_trainer.py': 'ml_trainer',
    'backtesting/state_machine_engine.py': 'sm_engine',
    'core/data_utils.py': 'data_utils',
    'core/fetch_data.py': 'fetch_data',
    'backtesting/logger.py': 'trade_logger',
    'core/live_engine.py': 'live_engine'
}

for filepath, logger_name in files_to_refactor.items():
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    # Skip if already imported from system_logger
    if 'from core.system_logger import setup_logger' not in text:
        import_stmt = f'\nfrom core.system_logger import setup_logger\nlogger = setup_logger("{logger_name}")\n\n'
        
        lines = text.split('\n')
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('import ') or line.startswith('from '):
                insert_idx = i + 1
        
        lines.insert(insert_idx, import_stmt)
        text = '\n'.join(lines)

    def replacer(match):
        content = match.group(1)
        if 'Error' in content or 'Failed' in content or 'Exception' in content:
            return f'logger.error({content})'
        elif 'Warning' in content:
            return f'logger.warning({content})'
        else:
            return f'logger.info({content})'
            
    # Replace print(...) with logger.info(...)
    text = re.sub(r'print\((.*?)\)', replacer, text)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f'Refactored {filepath}')
