"""
Configuration management for SFDC Deduplication Agent
Loads and validates environment variables
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration"""

    # Salesforce
    SF_USERNAME: str = os.getenv("SF_USERNAME", "")
    SF_PASSWORD: str = os.getenv("SF_PASSWORD", "")
    SF_SECURITY_TOKEN: str = os.getenv("SF_SECURITY_TOKEN", "")

    # Claude API
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # LangSmith (optional)
    LANGCHAIN_TRACING_V2: str = os.getenv("LANGCHAIN_TRACING_V2", "false")
    LANGCHAIN_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "sfdc-dedup-agent")

    # Server
    PORT: int = int(os.getenv("PORT", 8000))
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # Railway
    RAILWAY_ENVIRONMENT: str = os.getenv("RAILWAY_ENVIRONMENT", "development")

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """
        Validate required configuration

        Returns:
            Tuple of (is_valid, list of missing variables)
        """
        missing = []

        if not cls.SF_USERNAME:
            missing.append("SF_USERNAME")
        if not cls.SF_PASSWORD:
            missing.append("SF_PASSWORD")
        if not cls.SF_SECURITY_TOKEN:
            missing.append("SF_SECURITY_TOKEN")
        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")

        return len(missing) == 0, missing

    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production"""
        return cls.RAILWAY_ENVIRONMENT == "production"

    @classmethod
    def langsmith_enabled(cls) -> bool:
        """Check if LangSmith is enabled"""
        return cls.LANGCHAIN_TRACING_V2.lower() == "true" and bool(cls.LANGCHAIN_API_KEY)


# Global config instance
config = Config()
