"""Compatibility wrapper for storage lane layout.

Implementation ownership has moved to `app.storage.layout`.
"""

from app.storage.layout import StorageLane, StorageLayout, storage_layout_from_config

__all__ = ["StorageLane", "StorageLayout", "storage_layout_from_config"]

