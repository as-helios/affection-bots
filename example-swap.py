from core import *

tokenA_address = ''
tokenA_info = get_token_info(tokenA_address)
tokenB_address = ''
tokenB_info = get_token_info(tokenB_address)

tokenA_amount = 369
slippage_percent = 5
dex = 'PulseX_v2'

wallet_address = ''
set_logging(wallet_address, 'INFO')
account = load_wallet(wallet_address, os.getenv('SECRET'))

estimated_swap_result = estimate_swap_result(
    dex,
    tokenA_address,
    tokenB_address,
    tokenA_amount
)
if estimated_swap_result:
    if swap_tokens(
            account,
            dex,
            [tokenA_address, tokenB_address],
            estimated_swap_result,
            slippage_percent,
            wallet_address
    ):
        logging.info("Swapped {} {} to {}".format(tokenA_amount, tokenA_info['symbol'], tokenB_info['symbol']))
else:
    logging.warning("No estimated swap result data")
