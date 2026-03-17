"""
ContentBank configuration.
Settings are loaded from environment variables and/or a .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CB_",
        case_sensitive=False,
    )

    # --- Node identity ---
    node_id: str  # urn:cb:node:{uuid} — must be set in environment
    node_type: str = "edge"  # edge | cloud | gateway

    # --- Database ---
    database_url: str = "postgresql+asyncpg://contentbank:contentbank@localhost:5432/contentbank"

    # --- IPFS ---
    ipfs_api_url: str = "http://127.0.0.1:5001"

    # --- API server ---
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # --- Shapes ---
    shapes_dir: Path = Path(__file__).parent.parent.parent / "shapes"

    # --- Replication ---
    replication_sync_interval_seconds: int = 60
    replication_batch_size: int = 500

    # --- Auth ---
    # ECDH key pair for this node (base64url encoded)
    node_private_key: str = ""
    node_public_key: str = ""

    # JWT settings
    jwt_algorithm: str = "ES256"
    jwt_expiry_seconds: int = 300


# Module-level singleton — loaded once at startup
settings = Settings()
