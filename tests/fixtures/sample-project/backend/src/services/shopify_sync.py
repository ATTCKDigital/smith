"""Shopify sync service (stub)."""

import logging

log = logging.getLogger(__name__)


def sync_product(product_id: int) -> bool:
    """Sync a single product to Shopify."""
    log.info("syncing %s", product_id)
    return True


class ShopifySyncService:
    def sync(self, product_id: int) -> bool:
        return sync_product(product_id)
