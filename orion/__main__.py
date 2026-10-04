import asyncio
import logging
from .config import get_config
from .telegram_app import serve

if __name__=='__main__':
    config=get_config()
    logging.basicConfig(level=getattr(logging,config.log_level,logging.INFO),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:asyncio.run(serve(config))
    except KeyboardInterrupt:pass
