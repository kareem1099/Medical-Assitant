from src.stores.metadata.MongoMetadataProvider import MongoMetadataProvider


class BaseController:
    """Shared controller dependency boundary for authenticated use cases."""

    def __init__(self, metadata_provider: MongoMetadataProvider):
        self.metadata = metadata_provider
